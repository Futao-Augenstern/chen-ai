import ast
import operator
import os
import subprocess
import json
import tempfile
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ToolResult:
    def __init__(self, success: bool, content: str, error: Optional[str] = None):
        self.success = success
        self.content = content
        self.error = error


class BaseTool:
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
        raise NotImplementedError


class WebSearchTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="web_search",
            description="搜索互联网获取信息",
            parameters={"query": "搜索关键词"},
        )

    def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        try:
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
                for item in data.get("RelatedTopics", [])[:5]:
                    if "Text" in item:
                        results.append(item["Text"])
                if results:
                    return ToolResult(True, "\n\n".join(results))
                return ToolResult(True, f"未找到与 '{query}' 相关的结果。")
        except Exception as e:
            return ToolResult(False, "", str(e))


class CodeExecutionTool(BaseTool):
    DANGEROUS_KEYWORDS: List[bytes] = [
        b"os.", b"sys.", b"subprocess", b"shutil", b"importlib",
        b"__import__", b"eval(", b"exec(", b"compile(",
        b"open(", b"Socket", b"urllib", b"requests",
    ]

    def __init__(self):
        super().__init__(
            name="execute_code",
            description="执行 Python 代码并返回结果",
            parameters={"code": "Python 代码字符串"},
        )

    def _is_safe(self, code: str) -> Tuple[bool, str]:
        code_bytes = code.encode("utf-8", errors="ignore")
        for kw in self.DANGEROUS_KEYWORDS:
            if kw in code_bytes:
                return False, f"代码包含禁止的关键词: {kw.decode()}"
        return True, ""

    def execute(self, code: str = "", **kwargs: Any) -> ToolResult:
        safe, reason = self._is_safe(code)
        if not safe:
            return ToolResult(False, "", reason)

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            result = subprocess.run(
                ["python", tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.cwd()),
            )
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr
            return ToolResult(True, output.strip() or "(无输出)")
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", "代码执行超时 (30秒)")
        except FileNotFoundError:
            return ToolResult(False, "", "Python 未安装或不在 PATH 中")
        except Exception as e:
            return ToolResult(False, "", str(e))
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass


class CalculatorTool(BaseTool):
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


class FileTool(BaseTool):
    """文件操作工具，默认限制在工作目录内以确保安全"""

    def __init__(self, safe_dirs: Optional[List[Path]] = None):
        super().__init__(
            name="file_operations",
            description="读取、写入、列出文件",
            parameters={
                "operation": "read / write / list",
                "path": "文件或目录路径",
            },
        )
        # 默认安全目录为当前工作目录
        if safe_dirs is None:
            safe_dirs = [Path.cwd().resolve()]
        self.SAFE_DIRS = [d.resolve() for d in safe_dirs]

    def add_safe_dir(self, dir_path: Path) -> None:
        """添加安全目录"""
        resolved = Path(dir_path).expanduser().resolve()
        if resolved not in self.SAFE_DIRS:
            self.SAFE_DIRS.append(resolved)

    def _is_safe_path(self, file_path: Path) -> bool:
        if self.SAFE_DIRS:
            resolved = file_path.resolve()
            for safe_dir in self.SAFE_DIRS:
                try:
                    resolved.relative_to(safe_dir)
                    return True
                except ValueError:
                    continue
            return False
        return True

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
                if file_path.stat().st_size > 1024 * 1024:
                    return ToolResult(False, "", "文件过大 (>1MB)")
                with open(file_path, "r", encoding="utf-8") as f:
                    return ToolResult(True, f.read())
            elif operation == "write":
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
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


class JSONTool(BaseTool):
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
            idx = int(query[query.index("[")+1:query.index("]")])
            if base:
                data = data.get(base, {})
            if isinstance(data, list) and 0 <= idx < len(data):
                rest = query[query.index("]")+1:]
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


class TimeTool(BaseTool):
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
            now = datetime.now(timezone(timedelta(hours=8)))
            if operation == "now":
                return ToolResult(
                    True,
                    json.dumps({
                        "iso": now.isoformat(),
                        "timestamp": int(now.timestamp()),
                        "date": now.strftime("%Y-%m-%d"),
                        "time": now.strftime("%H:%M:%S"),
                        "weekday": now.strftime("%A"),
                        "weekday_cn": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
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
                        f"时间差: {diff.days} 天 {diff.seconds // 3600} 小时 {(diff.seconds % 3600) // 60} 分钟",
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


class TextTool(BaseTool):
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
                import re as _re
                emails = _re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
                urls = _re.findall(r'https?://[^\s]+', text)
                phones = _re.findall(r'1[3-9]\d{9}', text)
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


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(WebSearchTool())
        self.register(CodeExecutionTool())
        self.register(CalculatorTool())
        self.register(FileTool())
        self.register(JSONTool())
        self.register(TimeTool())
        self.register(TextTool())

    def register(self, tool: BaseTool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self.tools.get(name)

    def execute(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(False, "", f"未知工具: {name}")
        return tool.execute(**kwargs)

    def list_tools(self) -> List[Dict[str, str]]:
        return [
            {"name": t.name, "description": t.description}
            for t in self.tools.values()
        ]