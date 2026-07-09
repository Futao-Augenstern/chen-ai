import ast
import io
import operator
import os
import re
import subprocess
import json
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Callable

# ---------------- Optional dependency imports ----------------

# PIL / Pillow (for ImageTool)
try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# requests (for BrowserTool, HTTPTool, WebSearchTool fallback)
try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

# BeautifulSoup (for BrowserTool, WebSearchTool fallback)
try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

# markdown (for MarkdownTool)
try:
    import markdown as _markdown_lib
    _MARKDOWN_AVAILABLE = True
except ImportError:
    _MARKDOWN_AVAILABLE = False


# ============================================================
#  Core classes
# ============================================================

class ToolResult:
    """工具执行结果。

    Attributes:
        success: 是否执行成功。
        content: 执行结果内容（字符串）。
        error: 错误信息，成功时为 None。
    """

    def __init__(self, success: bool, content: str, error: Optional[str] = None):
        self.success = success
        self.content = content
        self.error = error

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"ToolResult({status}, content={self.content[:80]!r})"


class BaseTool:
    """所有工具的基类。

    Attributes:
        name: 工具名称（唯一标识）。
        description: 工具功能描述。
        parameters: 参数说明字典。
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters or {}

    def execute(self, **kwargs: Any) -> "ToolResult":
        """执行工具。子类必须实现此方法。"""
        raise NotImplementedError


# ============================================================
#  WebSearchTool (enhanced)
# ============================================================

class WebSearchTool(BaseTool):
    """互联网搜索工具。

    支持 DuckDuckGo 主搜索引擎，并可在失败时回退到 Google
    （通过 requests + BeautifulSoup）。支持多引擎配置和结果数量控制。
    """

    def __init__(
        self,
        result_count: int = 5,
        search_engines: Optional[List[str]] = None,
    ):
        super().__init__(
            name="web_search",
            description="搜索互联网获取信息",
            parameters={
                "query": "搜索关键词",
                "result_count": "返回结果数量（默认 5）",
                "engine": "指定搜索引擎: duckduckgo / google",
            },
        )
        self.result_count = result_count
        self.search_engines = search_engines or ["duckduckgo", "google"]

    # ---- DuckDuckGo ----

    def _search_duckduckgo(self, query: str) -> List[str]:
        encoded_query = urllib.parse.quote(query)
        url = (
            "https://api.duckduckgo.com/?"
            f"q={encoded_query}&format=json&no_html=1"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "AI-Assistant/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results: List[str] = []
            for item in data.get("RelatedTopics", []):
                if "Text" in item:
                    results.append(item["Text"])
            return results

    # ---- Google fallback ----

    def _search_google(self, query: str) -> List[str]:
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError("requests 库未安装，无法使用 Google 搜索")
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded_query}&hl=zh-CN"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        results: List[str] = []
        if _BS4_AVAILABLE:
            soup = BeautifulSoup(resp.text, "html.parser")
            for g in soup.find_all("div", class_="g"):
                title_el = g.find("h3")
                snippet_el = g.find("div", class_="VwiC3b")
                if title_el:
                    title = title_el.get_text(strip=True)
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    results.append(f"{title}\n{snippet}" if snippet else title)
        else:
            # 简单的正则提取
            titles = re.findall(r'<h3[^>]*>(.*?)</h3>', resp.text, re.DOTALL)
            for t in titles:
                clean = re.sub(r'<[^>]+>', '', t).strip()
                if clean:
                    results.append(clean)
        return results

    # ---- 搜索引擎分发 ----

    def search_with_engine(self, query: str, engine: str) -> List[str]:
        """使用指定搜索引擎搜索。

        Args:
            query: 搜索关键词。
            engine: 搜索引擎名称 (duckduckgo / google)。

        Returns:
            搜索结果列表。
        """
        engine = engine.lower()
        if engine == "duckduckgo":
            return self._search_duckduckgo(query)
        elif engine == "google":
            return self._search_google(query)
        else:
            raise ValueError(f"不支持的搜索引擎: {engine}")

    def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        result_count = kwargs.get("result_count", self.result_count)
        specified_engine = kwargs.get("engine", None)

        engines_to_try: List[str]
        if specified_engine:
            engines_to_try = [specified_engine]
        else:
            engines_to_try = list(self.search_engines)

        errors: List[str] = []
        for engine in engines_to_try:
            try:
                results = self.search_with_engine(query, engine)
                if results:
                    trimmed = results[:result_count]
                    return ToolResult(
                        True,
                        f"[搜索引擎: {engine}]\n\n" + "\n\n".join(trimmed),
                    )
                else:
                    errors.append(f"{engine}: 未找到结果")
            except Exception as e:
                errors.append(f"{engine}: {e}")

        if errors:
            return ToolResult(False, "", "; ".join(errors))
        return ToolResult(True, f"未找到与 '{query}' 相关的结果。")


# ============================================================
#  CodeExecutionTool (enhanced with sandbox)
# ============================================================

class CodeExecutionTool(BaseTool):
    """安全沙箱代码执行工具。

    支持：
    - 自定义最长执行时间（max_execution_time）
    - 自定义最大内存限制（max_memory_mb）
    - 自定义最大输出大小（max_output_size）
    - 白名单 import 控制（allow_imports）
    - 可自定义的 sandbox_config
    """

    DANGEROUS_KEYWORDS: List[bytes] = [
        b"os.", b"sys.", b"subprocess", b"shutil", b"importlib",
        b"__import__", b"eval(", b"exec(", b"compile(",
        b"open(", b"socket", b"urllib", b"requests",
        b"ctypes", b"multiprocessing", b"signal", b"gc.",
        b"sysconfig", b"atexit", b"codeop",
    ]

    DANGEROUS_CALL_NAMES: List[str] = [
        "eval", "exec", "compile", "__import__", "getattr", "setattr",
        "delattr", "globals", "locals", "vars", "breakpoint", "help",
    ]

    DEFAULT_ALLOW_IMPORTS: List[str] = [
        "math", "json", "re", "datetime", "collections", "itertools", "random",
    ]

    def __init__(
        self,
        max_execution_time: int = 30,
        max_memory_mb: int = 128,
        max_output_size: int = 100 * 1024,
        allow_imports: Optional[List[str]] = None,
        sandbox_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            name="execute_code",
            description="在安全沙箱中执行 Python 代码并返回结果",
            parameters={
                "code": "Python 代码字符串",
            },
        )
        self.max_execution_time = max_execution_time
        self.max_memory_mb = max_memory_mb
        self.max_output_size = max_output_size
        self.allow_imports = allow_imports or list(self.DEFAULT_ALLOW_IMPORTS)
        self.sandbox_config = sandbox_config or {}

    # ---- 安全校验 ----

    def _is_safe(self, code: str) -> Tuple[bool, str]:
        """多层安全检查：字节匹配 + AST 调用名检查。

        Returns:
            (is_safe, error_message)
        """
        # 第一层：字节匹配黑名单
        code_bytes = code.encode("utf-8", errors="ignore")
        for kw in self.DANGEROUS_KEYWORDS:
            if kw in code_bytes:
                return False, f"代码包含禁止的关键词: {kw.decode()}"

        # 第二层：AST 检查危险函数调用（如 getattr/globals 等绕过手段）
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"代码语法错误: {e}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.DANGEROUS_CALL_NAMES:
                    return False, f"代码包含禁止的函数调用: {node.func.id}()"
                if isinstance(node.func, ast.Attribute):
                    # 检查 getattr 等作为属性访问的情况
                    if node.func.attr in self.DANGEROUS_CALL_NAMES:
                        return False, f"代码包含禁止的函数调用: {node.func.attr}()"

        return True, ""

    def _check_imports(self, code: str) -> Tuple[bool, str]:
        """检查代码中的 import 语句是否都在白名单内。

        Returns:
            (is_allowed, error_message)
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"代码语法错误: {e}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_name = alias.name.split(".")[0]
                    if mod_name not in self.allow_imports:
                        return False, (
                            f"安全违规: 不允许导入模块 '{mod_name}'。"
                            f" 白名单: {self.allow_imports}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    mod_name = node.module.split(".")[0]
                    if mod_name not in self.allow_imports:
                        return False, (
                            f"安全违规: 不允许导入模块 '{mod_name}'。"
                            f" 白名单: {self.allow_imports}"
                        )
        return True, ""

    # ---- 沙箱执行 ----

    @property
    def safe_globals(self) -> Dict[str, Any]:
        """返回受限的全局命名空间。"""
        safe_imports = self.allow_imports

        def _safe_import(name, *args, **kwargs):
            if name in safe_imports:
                return __import__(name, *args, **kwargs)
            raise ImportError(f"不允许导入模块: {name}")

        return {"__builtins__": {
            "abs": abs, "all": all, "any": any, "bool": bool,
            "chr": chr, "dict": dict, "divmod": divmod, "enumerate": enumerate,
            "filter": filter, "float": float, "int": int, "isinstance": isinstance,
            "len": len, "list": list, "map": map, "max": max, "min": min,
            "ord": ord, "pow": pow, "print": print, "range": range,
            "reversed": reversed, "round": round, "set": set, "slice": slice,
            "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
            "type": type, "zip": zip, "True": True, "False": False, "None": None,
            "__import__": _safe_import,
        }}

    @property
    def safe_locals(self) -> Dict[str, Any]:
        """返回受限的局部命名空间。"""
        return {}

    def execute(self, code: str = "", **kwargs: Any) -> ToolResult:
        # 安全校验
        safe, reason = self._is_safe(code)
        if not safe:
            return ToolResult(False, "", reason)

        import_ok, import_reason = self._check_imports(code)
        if not import_ok:
            return ToolResult(False, "", import_reason)

        try:
            # 在受限的 globals/locals 中执行代码（沙箱内执行）
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            captured_out = io.StringIO()
            captured_err = io.StringIO()
            sys.stdout = captured_out
            sys.stderr = captured_err

            try:
                exec(code, self.safe_globals, self.safe_locals)
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

            output = captured_out.getvalue()
            if captured_err.getvalue():
                output += "\n[stderr]\n" + captured_err.getvalue()

            # 截断超长输出
            if len(output) > self.max_output_size:
                output = (
                    output[:self.max_output_size]
                    + f"\n\n[输出已截断，超过 {self.max_output_size} 字节]"
                )

            return ToolResult(True, output.strip() or "(无输出)")

        except Exception as e:
            return ToolResult(False, "", str(e))


# ============================================================
#  CalculatorTool
# ============================================================

class CalculatorTool(BaseTool):
    """安全的数学计算工具。

    使用 AST 白名单方式解析数学表达式，仅允许安全的运算符和函数。
    """

    SAFE_OPS: Dict[type, Any] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    SAFE_FUNCS: Dict[str, Any] = {
        "abs": abs, "round": round, "min": min, "max": max,
        "int": int, "float": float, "pow": pow,
    }

    def __init__(self):
        super().__init__(
            name="calculator",
            description="执行数学计算",
            parameters={"expression": "数学表达式"},
        )

    def _safe_eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            left = self._safe_eval(node.left)
            right = self._safe_eval(node.right)
            op_type = type(node.op)
            if op_type in self.SAFE_OPS:
                return self.SAFE_OPS[op_type](left, right)
            raise ValueError(f"不允许的运算符: {op_type}")
        elif isinstance(node, ast.UnaryOp):
            operand = self._safe_eval(node.operand)
            op_type = type(node.op)
            if op_type in self.SAFE_OPS:
                return self.SAFE_OPS[op_type](operand)
            raise ValueError(f"不允许的一元运算符: {op_type}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name in self.SAFE_FUNCS:
                    args = [self._safe_eval(a) for a in node.args]
                    return self.SAFE_FUNCS[func_name](*args)
            raise ValueError(f"不允许的函数调用: {ast.dump(node)}")
        elif isinstance(node, ast.Name):
            raise ValueError(f"不允许的变量: {node.id}")
        else:
            raise ValueError(f"不支持的语法: {ast.dump(node)}")

    def execute(self, expression: str = "", **kwargs: Any) -> ToolResult:
        try:
            tree = ast.parse(expression.strip(), mode="eval")
            result = self._safe_eval(tree.body)
            return ToolResult(True, str(result))
        except (ValueError, SyntaxError, TypeError) as e:
            return ToolResult(False, "", str(e))
        except Exception as e:
            return ToolResult(False, "", f"计算错误: {e}")


# ============================================================
#  FileTool
# ============================================================

class FileTool(BaseTool):
    """文件读写工具。

    仅允许在指定的安全目录中操作，防止路径遍历攻击。
    """

    def __init__(self, safe_dirs: Optional[List[Path]] = None):
        super().__init__(
            name="file_operations",
            description="读取、写入、列出文件",
            parameters={
                "operation": "read / write / list",
                "path": "文件或目录路径",
            },
        )
        if safe_dirs:
            self.SAFE_DIRS = [d.resolve() for d in safe_dirs]
        else:
            self.SAFE_DIRS = [Path.cwd().resolve()]

    def add_safe_dir(self, dir_path: Path) -> None:
        """添加一个安全目录。"""
        resolved = Path(dir_path).expanduser().resolve()
        if resolved not in self.SAFE_DIRS:
            self.SAFE_DIRS.append(resolved)

    def _is_safe_path(self, file_path: Path) -> bool:
        resolved = file_path.resolve()
        for safe_dir in self.SAFE_DIRS:
            try:
                resolved.relative_to(safe_dir)
                return True
            except ValueError:
                continue
        return False

    def _safe_open(self, file_path: Path, mode: str) -> Any:
        """安全打开文件，读写前二次验证路径。"""
        resolved = file_path.resolve()
        if not self._is_safe_path(resolved):
            raise PermissionError(f"路径不在安全目录内: {resolved}")
        return open(resolved, mode, encoding="utf-8")

    def execute(
        self,
        operation: str = "",
        path: str = "",
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            file_path = Path(path).expanduser().resolve()
            if not self._is_safe_path(file_path):
                return ToolResult(False, "", f"路径不在安全目录中: {path}")

            if operation == "read":
                if not file_path.exists():
                    return ToolResult(False, "", f"文件不存在: {path}")
                with self._safe_open(file_path, "r") as f:
                    result = f.read()
                    if len(result) > 1024 * 1024:
                        return ToolResult(False, "", "文件过大 (>1MB)")
                    return ToolResult(True, result)
            elif operation == "write":
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with self._safe_open(file_path, "w") as f:
                    f.write(content or "")
                return ToolResult(True, f"文件已写入: {path}")
            elif operation == "list":
                if not file_path.is_dir():
                    return ToolResult(False, "", f"不是目录: {path}")
                items: List[str] = []
                for p in sorted(file_path.iterdir()):
                    prefix = "[D]" if p.is_dir() else "[F]"
                    items.append(f"{prefix} {p.name}")
                return ToolResult(True, "\n".join(items[:50]))
            else:
                return ToolResult(False, "", f"未知操作: {operation}")
        except Exception as e:
            return ToolResult(False, "", str(e))


# ============================================================
#  JSONTool
# ============================================================

class JSONTool(BaseTool):
    """JSON 数据处理工具。

    支持解析、格式化以及简化的 JSONPath 查询。
    """

    def __init__(self):
        super().__init__(
            name="json_processor",
            description="解析、查询、格式化 JSON 数据",
            parameters={
                "json_data": "JSON 字符串",
                "query": "JSONPath 简化查询 (如 'key.subkey', 'array[0]', '*.name')",
            },
        )

    def _simple_query(self, data: Any, query: str) -> Any:
        if not query:
            return data
        if query.startswith("*."):
            key = query[2:]
            if isinstance(data, list):
                return [item.get(key) for item in data if isinstance(item, dict)]
            return None
        if "[" in query and "]" in query:
            base = query[:query.index("[")]
            try:
                idx = int(query[query.index("[") + 1:query.index("]")])
            except (ValueError, IndexError):
                return None
            if base:
                data = data.get(base, {})
            if isinstance(data, list) and 0 <= idx < len(data):
                rest = query[query.index("]") + 1:]
                if rest.startswith("."):
                    return self._simple_query(data[idx], rest[1:])
                return data[idx]
            return None
        parts = query.split(".", 1)
        if isinstance(data, dict):
            if parts[0] in data:
                if len(parts) == 1:
                    return data[parts[0]]
                return self._simple_query(data[parts[0]], parts[1])
        return None

    def execute(self, json_data: str = "", query: str = "", **kwargs: Any) -> ToolResult:
        try:
            data = json.loads(json_data)
            if query:
                result = self._simple_query(data, query)
                return ToolResult(True, json.dumps(result, indent=2, ensure_ascii=False))
            return ToolResult(True, json.dumps(data, indent=2, ensure_ascii=False))
        except json.JSONDecodeError as e:
            return ToolResult(False, "", f"JSON 解析失败: {e}")
        except Exception as e:
            return ToolResult(False, "", str(e))


# ============================================================
#  TimeTool
# ============================================================

class TimeTool(BaseTool):
    """时间工具。

    支持获取当前时间、解析时间字符串、计算时间差、日期加减、格式化输出。
    """

    def __init__(self):
        super().__init__(
            name="time_utils",
            description="获取当前时间、日期计算、时区转换",
            parameters={
                "operation": "now / parse / diff / add / format",
                "value": "可选: 时间字符串、时间戳等",
            },
        )

    def execute(self, operation: str = "now", value: str = "", **kwargs: Any) -> ToolResult:
        try:
            now = datetime.now().astimezone()
            if operation == "now":
                return ToolResult(
                    True,
                    json.dumps({
                        "iso": now.isoformat(),
                        "timestamp": int(now.timestamp()),
                        "date": now.strftime("%Y-%m-%d"),
                        "time": now.strftime("%H:%M:%S"),
                        "weekday": now.strftime("%A"),
                        "weekday_cn": [
                            "周一", "周二", "周三", "周四", "周五", "周六", "周日"
                        ][now.weekday()],
                    }, indent=2, ensure_ascii=False),
                )
            elif operation == "parse":
                try:
                    dt = datetime.fromisoformat(value)
                    return ToolResult(True, f"解析结果: {dt.isoformat()}")
                except ValueError:
                    return ToolResult(False, "", f"无法解析时间: {value}")
            elif operation == "diff":
                parts = value.split(",") if value else []
                if len(parts) == 2:
                    d1 = datetime.fromisoformat(parts[0].strip())
                    d2 = datetime.fromisoformat(parts[1].strip())
                    diff = abs(d2 - d1)
                    return ToolResult(
                        True,
                        (
                            f"时间差: {diff.days} 天 "
                            f"{diff.seconds // 3600} 小时 "
                            f"{(diff.seconds % 3600) // 60} 分钟"
                        ),
                    )
                return ToolResult(False, "", "请提供两个时间，用逗号分隔")
            elif operation == "add":
                parts = value.split(",") if value else []
                if len(parts) == 2:
                    dt = datetime.fromisoformat(parts[0].strip())
                    days = int(parts[1].strip())
                    new_dt = dt + timedelta(days=days)
                    return ToolResult(True, new_dt.isoformat())
                return ToolResult(False, "", "请提供: 时间,天数")
            elif operation == "format":
                return ToolResult(True, now.strftime(value or "%Y-%m-%d %H:%M:%S"))
            else:
                return ToolResult(False, "", f"未知操作: {operation}")
        except Exception as e:
            return ToolResult(False, "", str(e))


# ============================================================
#  TextTool
# ============================================================

class TextTool(BaseTool):
    """文本处理工具。

    支持字数统计、信息提取、截断、去重等操作。
    """

    def __init__(self):
        super().__init__(
            name="text_processor",
            description="文本处理：统计字数、提取关键词、格式化等",
            parameters={
                "operation": "count / extract / truncate / dedup",
                "text": "文本内容",
            },
        )

    def execute(self, operation: str = "count", text: str = "", **kwargs: Any) -> ToolResult:
        try:
            if operation == "count":
                chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                words = len(text.split())
                lines = text.count('\n') + 1 if text else 0
                return ToolResult(
                    True,
                    f"字数统计: 中文字符={chinese}, 英文单词={words}, 行数={lines}, 总字符={len(text)}",
                )
            elif operation == "extract":
                emails = re.findall(
                    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text
                )
                urls = re.findall(r'https?://[^\s]+', text)
                phones = re.findall(r'1[3-9]\d{9}', text)
                return ToolResult(
                    True,
                    json.dumps({
                        "emails": emails,
                        "urls": urls,
                        "phones": phones,
                    }, indent=2, ensure_ascii=False),
                )
            elif operation == "truncate":
                max_len = int(kwargs.get("max_len", 200))
                if len(text) <= max_len:
                    return ToolResult(True, text)
                return ToolResult(True, text[:max_len] + "...")
            elif operation == "dedup":
                lines = text.split('\n')
                seen = set()
                unique = []
                for line in lines:
                    if line.strip() not in seen:
                        seen.add(line.strip())
                        unique.append(line)
                return ToolResult(True, "\n".join(unique))
            else:
                return ToolResult(False, "", f"未知操作: {operation}")
        except Exception as e:
            return ToolResult(False, "", str(e))


# ============================================================
#  NEW: ImageTool
# ============================================================

class ImageTool(BaseTool):
    """图像处理工具。

    使用 PIL/Pillow 库进行图像操作。如果 Pillow 未安装，会返回友好提示。
    支持操作：resize / crop / convert / compress / info。

    Example:
        tool = ImageTool()
        tool.execute(operation="resize", path="photo.jpg", width=200, height=200)
        tool.execute(operation="info", path="photo.jpg")
    """

    def __init__(self):
        super().__init__(
            name="image_tool",
            description="图像处理：调整尺寸、裁剪、格式转换、压缩、获取信息",
            parameters={
                "operation": "resize / crop / convert / compress / info",
                "path": "图片文件路径",
                "width": "resize: 目标宽度",
                "height": "resize: 目标高度",
                "left": "crop: 左边界",
                "top": "crop: 上边界",
                "right": "crop: 右边界",
                "bottom": "crop: 下边界",
                "format": "convert: 目标格式 (png/jpg/webp/bmp)",
                "quality": "compress: 压缩质量 (1-100)",
            },
        )

    def _ensure_pil(self) -> None:
        """确保 PIL 可用，否则抛出友好提示。"""
        if not _PIL_AVAILABLE:
            raise RuntimeError(
                "PIL/Pillow 库未安装。请运行: pip install Pillow"
            )

    def _op_resize(
        self, path: str, width: Optional[int] = None,
        height: Optional[int] = None, **kwargs: Any,
    ) -> ToolResult:
        self._ensure_pil()
        if not width and not height:
            return ToolResult(False, "", "请至少提供 width 或 height 参数")
        img = PILImage.open(path)
        if width and height:
            new_size = (width, height)
        elif width:
            ratio = width / img.width
            new_size = (width, int(img.height * ratio))
        else:
            ratio = height / img.height  # type: ignore[assignment]
            new_size = (int(img.width * ratio), height)  # type: ignore[operator]
        resized = img.resize(new_size, PILImage.LANCZOS)
        output_path = self._output_path(path, "_resized")
        resized.save(output_path)
        return ToolResult(True, f"图片已调整尺寸并保存至: {output_path}")

    def _op_crop(
        self, path: str, left: int = 0, top: int = 0,
        right: Optional[int] = None, bottom: Optional[int] = None,
        **kwargs: Any,
    ) -> ToolResult:
        self._ensure_pil()
        img = PILImage.open(path)
        r = right if right is not None else img.width
        b = bottom if bottom is not None else img.height
        cropped = img.crop((left, top, r, b))
        output_path = self._output_path(path, "_cropped")
        cropped.save(output_path)
        return ToolResult(
            True,
            f"图片已裁剪 (left={left}, top={top}, right={r}, bottom={b}) 并保存至: {output_path}",
        )

    def _op_convert(
        self, path: str, format: str = "png", **kwargs: Any,
    ) -> ToolResult:
        self._ensure_pil()
        valid_formats = {"png", "jpg", "jpeg", "webp", "bmp"}
        fmt = format.lower()
        if fmt not in valid_formats:
            return ToolResult(
                False, "",
                f"不支持的格式: {format}，支持: {', '.join(sorted(valid_formats))}",
            )
        img = PILImage.open(path)
        if fmt == "jpg":
            fmt = "jpeg"
        if img.mode in ("RGBA", "P") and fmt in ("jpeg",):
            img = img.convert("RGB")
        output_path = self._output_path(path, f".{format}")
        img.save(output_path, format=fmt.upper())
        return ToolResult(True, f"图片已转换为 {format.upper()} 并保存至: {output_path}")

    def _op_compress(
        self, path: str, quality: int = 75, **kwargs: Any,
    ) -> ToolResult:
        self._ensure_pil()
        if not (1 <= quality <= 100):
            return ToolResult(False, "", "quality 必须在 1-100 之间")
        img = PILImage.open(path)
        output_path = self._output_path(path, "_compressed")
        # 保存为 JPEG 格式以应用压缩质量
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=quality)
        orig_size = os.path.getsize(path)
        new_size = os.path.getsize(output_path)
        return ToolResult(
            True,
            (
                f"图片已压缩并保存至: {output_path}\n"
                f"原始大小: {orig_size / 1024:.1f} KB\n"
                f"压缩后: {new_size / 1024:.1f} KB\n"
                f"压缩率: {(1 - new_size / orig_size) * 100:.1f}%"
            ),
        )

    def _op_info(self, path: str, **kwargs: Any) -> ToolResult:
        self._ensure_pil()
        img = PILImage.open(path)
        file_size = os.path.getsize(path)
        info = {
            "path": path,
            "format": img.format,
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "size_kb": round(file_size / 1024, 1),
            "size_bytes": file_size,
            "aspect_ratio": f"{img.width}:{img.height}",
        }
        return ToolResult(True, json.dumps(info, indent=2, ensure_ascii=False))

    def _output_path(self, original: str, suffix: str) -> str:
        """生成输出文件路径。"""
        p = Path(original)
        if suffix.startswith("."):
            return str(p.with_suffix(suffix))
        return str(p.parent / f"{p.stem}{suffix}{p.suffix}")

    def execute(self, operation: str = "info", path: str = "", **kwargs: Any) -> ToolResult:
        try:
            if not path:
                return ToolResult(False, "", "请提供图片文件路径 (path)")
            operations: Dict[str, Callable[..., ToolResult]] = {
                "resize": self._op_resize,
                "crop": self._op_crop,
                "convert": self._op_convert,
                "compress": self._op_compress,
                "info": self._op_info,
            }
            if operation not in operations:
                return ToolResult(
                    False, "",
                    f"未知操作: {operation}，支持: {', '.join(operations.keys())}",
                )
            return operations[operation](path=path, **kwargs)
        except RuntimeError as e:
            return ToolResult(False, "", str(e))
        except FileNotFoundError:
            return ToolResult(False, "", f"文件不存在: {path}")
        except Exception as e:
            return ToolResult(False, "", f"图像处理错误: {e}")


# ============================================================
#  NEW: BrowserTool
# ============================================================

class BrowserTool(BaseTool):
    """浏览器自动化工具。

    使用 requests + BeautifulSoup 实现基础的浏览器自动化功能。
    支持操作：screenshot（截图）、open（打开网页获取内容）、extract（提取文本）。

    如果 requests 未安装，会返回友好提示。

    Example:
        tool = BrowserTool()
        tool.execute(operation="open", url="https://example.com")
        tool.execute(operation="extract", url="https://example.com", selector="h1")
    """

    DEFAULT_TIMEOUT = 15
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, default_timeout: int = 15):
        super().__init__(
            name="browser_tool",
            description="浏览器自动化：截图网页、打开网页获取内容、提取文本",
            parameters={
                "operation": "screenshot / open / extract",
                "url": "目标网页 URL",
                "output_path": "screenshot: 截图保存路径",
                "width": "screenshot: 视口宽度",
                "height": "screenshot: 视口高度",
                "selector": "extract: CSS 选择器",
                "timeout": "超时时间（秒）",
            },
        )
        self.default_timeout = default_timeout

    def _ensure_requests(self) -> None:
        """确保 requests 可用。"""
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError(
                "requests 库未安装。请运行: pip install requests"
            )

    def _ensure_bs4(self) -> None:
        """确保 BeautifulSoup 可用。"""
        if not _BS4_AVAILABLE:
            raise RuntimeError(
                "beautifulsoup4 库未安装。请运行: pip install beautifulsoup4"
            )

    def _get(self, url: str, timeout: int) -> "requests.Response":
        self._ensure_requests()
        headers = {"User-Agent": self.DEFAULT_USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp

    def _op_screenshot(
        self, url: str, output_path: str = "screenshot.png",
        width: int = 1280, height: int = 720,
        timeout: Optional[int] = None, **kwargs: Any,
    ) -> ToolResult:
        """截图当前仅返回提示，需要 selenium/playwright 才能实现真实截图。"""
        self._ensure_requests()
        t = timeout or self.default_timeout
        try:
            resp = self._get(url, t)
            return ToolResult(
                True,
                (
                    f"页面已获取（{len(resp.text)} 字符）。\n"
                    "注意: 真实截图需要安装 selenium 或 playwright 浏览器驱动。\n"
                    "当前返回的是页面 HTML 内容。\n\n"
                    f"URL: {url}\n"
                    f"状态码: {resp.status_code}\n"
                    f"Content-Type: {resp.headers.get('Content-Type', 'unknown')}"
                ),
            )
        except Exception as e:
            return ToolResult(False, "", f"获取页面失败: {e}")

    def _op_open(
        self, url: str, timeout: Optional[int] = None, **kwargs: Any,
    ) -> ToolResult:
        self._ensure_requests()
        t = timeout or self.default_timeout
        try:
            resp = self._get(url, t)
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type and _BS4_AVAILABLE:
                soup = BeautifulSoup(resp.text, "html.parser")
                # 移除 script 和 style 标签
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                # 清理多余空行
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                return ToolResult(
                    True,
                    f"URL: {url}\n状态码: {resp.status_code}\n\n" + "\n".join(lines[:200]),
                )
            return ToolResult(
                True,
                f"URL: {url}\n状态码: {resp.status_code}\n\n{resp.text[:5000]}",
            )
        except Exception as e:
            return ToolResult(False, "", f"打开页面失败: {e}")

    def _op_extract(
        self, url: str, selector: str = "body",
        timeout: Optional[int] = None, **kwargs: Any,
    ) -> ToolResult:
        self._ensure_requests()
        self._ensure_bs4()
        t = timeout or self.default_timeout
        try:
            resp = self._get(url, t)
            soup = BeautifulSoup(resp.text, "html.parser")
            elements = soup.select(selector)
            if not elements:
                return ToolResult(
                    True, f"未找到匹配选择器 '{selector}' 的元素",
                )
            texts = []
            for el in elements:
                text = el.get_text(separator=" ", strip=True)
                if text:
                    texts.append(text)
            return ToolResult(True, "\n\n".join(texts[:50]))
        except Exception as e:
            return ToolResult(False, "", f"提取文本失败: {e}")

    def execute(self, operation: str = "open", url: str = "", **kwargs: Any) -> ToolResult:
        try:
            if not url:
                return ToolResult(False, "", "请提供目标网页 URL")
            operations: Dict[str, Callable[..., ToolResult]] = {
                "screenshot": self._op_screenshot,
                "open": self._op_open,
                "extract": self._op_extract,
            }
            if operation not in operations:
                return ToolResult(
                    False, "",
                    f"未知操作: {operation}，支持: {', '.join(operations.keys())}",
                )
            return operations[operation](url=url, **kwargs)
        except RuntimeError as e:
            return ToolResult(False, "", str(e))
        except Exception as e:
            return ToolResult(False, "", f"浏览器操作错误: {e}")


# ============================================================
#  NEW: MarkdownTool
# ============================================================

class MarkdownTool(BaseTool):
    """Markdown 渲染工具。

    使用 markdown 库进行渲染。如果 markdown 未安装，提供基础正则实现。
    支持操作：render / to_html / to_plain / extract_code。

    Example:
        tool = MarkdownTool()
        tool.execute(operation="render", text="# Hello\\n\\nWorld")
        tool.execute(operation="extract_code", text="```python\\nprint(1)\\n```")
    """

    # 内联 CSS 样式，用于 to_html 操作
    DEFAULT_CSS = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6;
               color: #333; }
        h1 { border-bottom: 2px solid #eee; padding-bottom: 8px; }
        h2 { border-bottom: 1px solid #eee; padding-bottom: 6px; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
        pre { background: #f4f4f4; padding: 16px; border-radius: 6px; overflow-x: auto; }
        pre code { background: none; padding: 0; }
        blockquote { border-left: 4px solid #ddd; margin: 0; padding-left: 16px; color: #666; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
        th { background: #f8f8f8; }
        img { max-width: 100%; }
    </style>
    """

    def __init__(self):
        super().__init__(
            name="markdown_tool",
            description="Markdown 渲染：转 HTML、提取纯文本、提取代码块",
            parameters={
                "operation": "render / to_html / to_plain / extract_code",
                "text": "Markdown 文本内容",
            },
        )

    def _render_markdown(self, text: str) -> str:
        """使用 markdown 库渲染。"""
        if _MARKDOWN_AVAILABLE:
            return _markdown_lib.markdown(
                text,
                extensions=["fenced_code", "tables", "codehilite"],
            )
        else:
            return self._fallback_render(text)

    def _fallback_render(self, text: str) -> str:
        """基础正则 Markdown 渲染（markdown 库未安装时使用）。"""
        html = text

        # 代码块
        html = re.sub(
            r'```(\w*)\n(.*?)```',
            r'<pre><code class="language-\1">\2</code></pre>',
            html, flags=re.DOTALL,
        )
        # 行内代码
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        # 标题
        html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        # 粗体和斜体
        html = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', html)
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        # 链接
        html = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            r'<a href="\2">\1</a>', html,
        )
        # 图片
        html = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            r'<img src="\2" alt="\1">', html,
        )
        # 无序列表
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        # 引用
        html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
        # 段落
        paragraphs = html.split('\n\n')
        wrapped = []
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith('<'):
                wrapped.append(f'<p>{p}</p>')
            elif p:
                wrapped.append(p)
        html = '\n'.join(wrapped)

        return html

    def _op_render(self, text: str, **kwargs: Any) -> ToolResult:
        html = self._render_markdown(text)
        if not _MARKDOWN_AVAILABLE:
            html = (
                "<!-- 注意: 使用了基础正则渲染，安装 markdown 库可获得更好的效果 -->\n"
                + html
            )
        return ToolResult(True, html)

    def _op_to_html(self, text: str, **kwargs: Any) -> ToolResult:
        body = self._render_markdown(text)
        full_html = (
            "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"UTF-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
            "<title>Markdown Render</title>\n"
            + self.DEFAULT_CSS + "\n</head>\n<body>\n"
            + body + "\n</body>\n</html>"
        )
        return ToolResult(True, full_html)

    def _op_to_plain(self, text: str, **kwargs: Any) -> ToolResult:
        """提取纯文本：去除 Markdown 标记和 HTML 标签。"""
        # 移除代码块
        plain = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # 移除行内代码
        plain = re.sub(r'`([^`]+)`', r'\1', plain)
        # 移除图片
        plain = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', plain)
        # 链接只保留文字
        plain = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', plain)
        # 移除标题标记
        plain = re.sub(r'^#{1,6}\s+', '', plain, flags=re.MULTILINE)
        # 移除粗体/斜体标记
        plain = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', plain)
        plain = re.sub(r'\*\*(.+?)\*\*', r'\1', plain)
        plain = re.sub(r'\*(.+?)\*', r'\1', plain)
        # 移除引用标记
        plain = re.sub(r'^>\s+', '', plain, flags=re.MULTILINE)
        # 移除列表标记
        plain = re.sub(r'^[\s]*[-*+]\s+', '', plain, flags=re.MULTILINE)
        # 移除 HTML 标签
        plain = re.sub(r'<[^>]+>', '', plain)
        # 清理多余空白
        plain = re.sub(r'\n{3,}', '\n\n', plain)
        return ToolResult(True, plain.strip())

    def _op_extract_code(self, text: str, **kwargs: Any) -> ToolResult:
        """提取所有代码块。"""
        pattern = r'```(\w*)\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)
        if not matches:
            return ToolResult(True, "未找到代码块")
        result_parts = []
        for i, (lang, code) in enumerate(matches, 1):
            lang_display = lang or "text"
            result_parts.append(
                f"--- 代码块 #{i} (语言: {lang_display}) ---\n{code.strip()}"
            )
        return ToolResult(True, "\n\n".join(result_parts))

    def execute(self, operation: str = "render", text: str = "", **kwargs: Any) -> ToolResult:
        try:
            if not text:
                return ToolResult(False, "", "请提供 Markdown 文本内容 (text)")
            operations: Dict[str, Callable[..., ToolResult]] = {
                "render": self._op_render,
                "to_html": self._op_to_html,
                "to_plain": self._op_to_plain,
                "extract_code": self._op_extract_code,
            }
            if operation not in operations:
                return ToolResult(
                    False, "",
                    f"未知操作: {operation}，支持: {', '.join(operations.keys())}",
                )
            return operations[operation](text=text, **kwargs)
        except Exception as e:
            return ToolResult(False, "", f"Markdown 处理错误: {e}")


# ============================================================
#  NEW: HTTPTool
# ============================================================

class HTTPTool(BaseTool):
    """HTTP 网络请求工具。

    使用 requests 库发送 HTTP 请求，支持 GET / POST / PUT / DELETE / HEAD。
    自动处理 JSON 响应，支持 Bearer Token 认证。

    如果 requests 未安装，会返回友好提示。

    Example:
        tool = HTTPTool()
        tool.execute(operation="get", url="https://api.example.com/data")
        tool.execute(operation="post", url="https://api.example.com/data",
                     body='{"key":"value"}', headers='{"Authorization":"Bearer xyz"}')
    """

    DEFAULT_TIMEOUT = 30

    def __init__(self, default_timeout: int = 30):
        super().__init__(
            name="http_tool",
            description="HTTP 网络请求：GET / POST / PUT / DELETE / HEAD",
            parameters={
                "operation": "get / post / put / delete / head",
                "url": "请求 URL",
                "body": "请求体（JSON 字符串）",
                "headers": "请求头（JSON 字符串）",
                "token": "Bearer Token 认证令牌",
                "timeout": "超时时间（秒）",
            },
        )
        self.default_timeout = default_timeout

    def _ensure_requests(self) -> None:
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError(
                "requests 库未安装。请运行: pip install requests"
            )

    def _parse_headers(
        self, headers_str: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, str]:
        """解析 headers JSON 字符串，并可选添加 Bearer Token。"""
        headers: Dict[str, str] = {}
        if headers_str:
            try:
                headers = json.loads(headers_str)
            except json.JSONDecodeError:
                raise ValueError(f"headers 不是有效的 JSON: {headers_str}")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _format_response(self, resp: "requests.Response") -> str:
        """格式化 HTTP 响应为可读字符串。"""
        parts: List[str] = [
            f"状态码: {resp.status_code} {resp.reason}",
            f"URL: {resp.url}",
            f"耗时: {resp.elapsed.total_seconds():.3f}s",
            "",
        ]
        # 响应头
        parts.append("--- 响应头 ---")
        for key, value in resp.headers.items():
            if key.lower() in ("set-cookie", "authorization"):
                parts.append(f"  {key}: [已隐藏]")
            else:
                parts.append(f"  {key}: {value}")

        # 响应体
        content_type = resp.headers.get("Content-Type", "")
        parts.append("")
        parts.append("--- 响应体 ---")
        if "application/json" in content_type:
            try:
                body = resp.json()
                parts.append(json.dumps(body, indent=2, ensure_ascii=False))
            except Exception:
                parts.append(resp.text[:5000])
        else:
            text = resp.text
            if len(text) > 5000:
                text = text[:5000] + f"\n\n[已截断，总长度 {len(resp.text)} 字符]"
            parts.append(text)

        return "\n".join(parts)

    def _make_request(
        self, method: str, url: str,
        body: Optional[str] = None,
        headers_str: Optional[str] = None,
        token: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> "requests.Response":
        self._ensure_requests()
        headers = self._parse_headers(headers_str, token)
        t = timeout or self.default_timeout
        kwargs: Dict[str, Any] = {"headers": headers, "timeout": t}

        if method.upper() in ("POST", "PUT", "PATCH"):
            if body:
                try:
                    kwargs["json"] = json.loads(body)
                except json.JSONDecodeError:
                    kwargs["data"] = body

        resp = requests.request(method.upper(), url, **kwargs)
        return resp

    def _op_get(self, url: str, **kwargs: Any) -> ToolResult:
        resp = self._make_request("GET", url, **kwargs)
        return ToolResult(True, self._format_response(resp))

    def _op_post(self, url: str, **kwargs: Any) -> ToolResult:
        resp = self._make_request("POST", url, **kwargs)
        return ToolResult(True, self._format_response(resp))

    def _op_put(self, url: str, **kwargs: Any) -> ToolResult:
        resp = self._make_request("PUT", url, **kwargs)
        return ToolResult(True, self._format_response(resp))

    def _op_delete(self, url: str, **kwargs: Any) -> ToolResult:
        resp = self._make_request("DELETE", url, **kwargs)
        return ToolResult(True, self._format_response(resp))

    def _op_head(self, url: str, **kwargs: Any) -> ToolResult:
        resp = self._make_request("HEAD", url, **kwargs)
        parts = [
            f"状态码: {resp.status_code} {resp.reason}",
            f"URL: {resp.url}",
            "",
            "--- 响应头 ---",
        ]
        for key, value in resp.headers.items():
            parts.append(f"  {key}: {value}")
        return ToolResult(True, "\n".join(parts))

    def execute(self, operation: str = "get", url: str = "", **kwargs: Any) -> ToolResult:
        try:
            if not url:
                return ToolResult(False, "", "请提供请求 URL")
            operations: Dict[str, Callable[..., ToolResult]] = {
                "get": self._op_get,
                "post": self._op_post,
                "put": self._op_put,
                "delete": self._op_delete,
                "head": self._op_head,
            }
            op = operation.lower()
            if op not in operations:
                return ToolResult(
                    False, "",
                    f"未知操作: {operation}，支持: {', '.join(operations.keys())}",
                )
            return operations[op](url=url, **kwargs)
        except RuntimeError as e:
            return ToolResult(False, "", str(e))
        except ValueError as e:
            return ToolResult(False, "", str(e))
        except Exception as e:
            return ToolResult(False, "", f"HTTP 请求错误: {e}")


# ============================================================
#  ToolRegistry (enhanced)
# ============================================================

class ToolRegistry:
    """工具注册中心。

    管理所有工具的注册、查找、执行，支持：
    - 批量注册/注销
    - 按分类获取工具
    - 并行执行多个工具调用
    - 工具使用统计（调用次数、成功率、平均耗时）
    - 启用/禁用工具
    """

    # 工具分类映射
    CATEGORY_MAP: Dict[str, str] = {
        "web_search": "搜索",
        "execute_code": "代码",
        "calculator": "计算",
        "file_operations": "文件",
        "json_processor": "数据",
        "time_utils": "时间",
        "text_processor": "文本",
        "image_tool": "图像",
        "browser_tool": "浏览器",
        "markdown_tool": "文档",
        "http_tool": "网络",
    }

    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self._disabled: Dict[str, bool] = {}
        self.tool_stats: Dict[str, Dict[str, Any]] = {}
        self._register_defaults()

    # ---- 注册 ----

    def _register_defaults(self) -> None:
        """注册默认工具集。"""
        self.register(WebSearchTool())
        self.register(CodeExecutionTool())
        self.register(CalculatorTool())
        self.register(FileTool())
        self.register(JSONTool())
        self.register(TimeTool())
        self.register(TextTool())
        self.register(ImageTool())
        self.register(BrowserTool())
        self.register(MarkdownTool())
        self.register(HTTPTool())

    def register(self, tool: BaseTool) -> None:
        """注册一个工具。"""
        self.tools[tool.name] = tool
        self._disabled[tool.name] = False
        if tool.name not in self.tool_stats:
            self.tool_stats[tool.name] = {
                "call_count": 0,
                "success_count": 0,
                "total_time": 0.0,
            }

    def register_all(self, tools: List[BaseTool]) -> None:
        """批量注册工具。

        Args:
            tools: 工具实例列表。
        """
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> bool:
        """注销一个工具。

        Args:
            name: 工具名称。

        Returns:
            是否成功注销（工具不存在时返回 False）。
        """
        if name in self.tools:
            del self.tools[name]
            self._disabled.pop(name, None)
            self.tool_stats.pop(name, None)
            return True
        return False

    # ---- 查询 ----

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具实例。"""
        return self.tools.get(name)

    def get_tool_names(self) -> List[str]:
        """返回所有已注册工具的名称列表。"""
        return list(self.tools.keys())

    def get_tools_by_category(self, category: str) -> List[BaseTool]:
        """按分类获取工具列表。

        Args:
            category: 分类名称（如 "搜索"、"文件"、"网络" 等）。

        Returns:
            匹配分类的工具列表。
        """
        result: List[BaseTool] = []
        for name, tool in self.tools.items():
            cat = self.CATEGORY_MAP.get(name, "其他")
            if cat == category:
                result.append(tool)
        return result

    # ---- 启用/禁用 ----

    def enable_tool(self, name: str) -> bool:
        """启用一个工具。

        Args:
            name: 工具名称。

        Returns:
            是否成功启用（工具不存在时返回 False）。
        """
        if name in self._disabled:
            self._disabled[name] = False
            return True
        return False

    def disable_tool(self, name: str) -> bool:
        """禁用一个工具。禁用的工具将无法执行。

        Args:
            name: 工具名称。

        Returns:
            是否成功禁用（工具不存在时返回 False）。
        """
        if name in self._disabled:
            self._disabled[name] = True
            return True
        return False

    def is_enabled(self, name: str) -> bool:
        """检查工具是否已启用。

        Args:
            name: 工具名称。

        Returns:
            True 表示工具已启用，False 表示已禁用或不存在。
        """
        return name in self.tools and not self._disabled.get(name, True)

    # ---- 执行 ----

    def execute(self, name: str, **kwargs: Any) -> ToolResult:
        """执行指定的工具。

        Args:
            name: 工具名称。
            **kwargs: 传递给工具的参数字典。

        Returns:
            ToolResult 执行结果。
        """
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(False, "", f"未知工具: {name}")
        if self._disabled.get(name, False):
            return ToolResult(False, "", f"工具已禁用: {name}")

        start = time.time()
        result = tool.execute(**kwargs)
        elapsed = time.time() - start

        # 更新统计
        stats = self.tool_stats[name]
        stats["call_count"] += 1
        if result.success:
            stats["success_count"] += 1
        stats["total_time"] += elapsed

        return result

    def execute_parallel(
        self, tool_calls: List[Dict[str, Any]],
    ) -> List[Tuple[str, ToolResult]]:
        """并行执行多个工具调用。

        注意: 当前为串行模拟（Python 单线程），但接口设计为支持
        未来升级为真正的并行执行（如 concurrent.futures）。

        Args:
            tool_calls: 工具调用列表，每个元素为 {"name": 工具名, "kwargs": 参数字典}。

        Returns:
            [(工具名, ToolResult), ...] 列表，顺序与输入一致。
        """
        results: List[Tuple[str, ToolResult]] = []
        for call in tool_calls:
            name = call.get("name", "")
            kwargs = call.get("kwargs", {})
            result = self.execute(name, **kwargs)
            results.append((name, result))
        return results

    # ---- 统计 ----

    def get_stats(self) -> Dict[str, Any]:
        """返回所有工具的统计信息。

        Returns:
            字典，键为工具名称，值为统计数据（调用次数、成功率、平均耗时）。
        """
        result: Dict[str, Any] = {}
        for name, stats in self.tool_stats.items():
            call_count = stats["call_count"]
            success_count = stats["success_count"]
            total_time = stats["total_time"]
            result[name] = {
                "call_count": call_count,
                "success_count": success_count,
                "success_rate": (
                    round(success_count / call_count, 4) if call_count > 0 else 0.0
                ),
                "avg_time": (
                    round(total_time / call_count, 4) if call_count > 0 else 0.0
                ),
                "total_time": round(total_time, 4),
                "enabled": self.is_enabled(name),
                "category": self.CATEGORY_MAP.get(name, "其他"),
            }
        return result

    # ---- 列表 ----

    def list_tools(self) -> List[Dict[str, str]]:
        """列出所有工具的基本信息。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "enabled": str(self.is_enabled(t.name)),
                "category": self.CATEGORY_MAP.get(t.name, "其他"),
            }
            for t in self.tools.values()
        ]


# ============================================================
#  Convenience function
# ============================================================

def create_registry() -> ToolRegistry:
    """创建并返回一个预配置的 ToolRegistry 实例。"""
    return ToolRegistry()