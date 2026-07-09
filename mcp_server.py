import json
import logging
import subprocess
import signal
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MCP_DIR = Path(__file__).parent / "mcp_data"
MCP_CONFIG_FILE = MCP_DIR / "mcp_config.json"


class MCPServer:
    def __init__(
        self,
        name: str,
        description: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        category: str = "tool",
        transport: str = "stdio",
        sse_url: Optional[str] = None,
        http_url: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ):
        self.name = name
        self.description = description
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.category = category
        self.enabled = False
        self.installed = False
        self.created_at = datetime.now().isoformat()
        # --- transport layer ---
        self.transport = transport
        self.sse_url = sse_url
        self.http_url = http_url
        # --- tags ---
        self.tags = tags or []
        # --- health check ---
        self.health_status = "unknown"
        self.last_health_check: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "category": self.category,
            "enabled": self.enabled,
            "installed": self.installed,
            "created_at": self.created_at,
            "transport": self.transport,
            "sse_url": self.sse_url,
            "http_url": self.http_url,
            "tags": self.tags,
            "health_status": self.health_status,
            "last_health_check": self.last_health_check,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServer":
        server = cls(
            name=data["name"],
            description=data["description"],
            command=data["command"],
            args=data.get("args", []),
            env=data.get("env", {}),
            category=data.get("category", "tool"),
            transport=data.get("transport", "stdio"),
            sse_url=data.get("sse_url"),
            http_url=data.get("http_url"),
            tags=data.get("tags", []),
        )
        server.enabled = data.get("enabled", False)
        server.installed = data.get("installed", False)
        server.created_at = data.get("created_at", datetime.now().isoformat())
        server.health_status = data.get("health_status", "unknown")
        server.last_health_check = data.get("last_health_check")
        return server

    def check_installed(self) -> bool:
        try:
            result = subprocess.run(
                [self.command, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Transport layer
    # ------------------------------------------------------------------
    def connect_sse(self, url: str) -> None:
        """Configure this server to use SSE transport.

        Sets transport to "sse" and stores the SSE endpoint URL.
        This is framework code; the actual SSE connection is managed
        by the MCP client runtime.
        """
        self.transport = "sse"
        self.sse_url = url
        self.http_url = None

    def connect_http(self, url: str) -> None:
        """Configure this server to use Streamable HTTP transport.

        Sets transport to "streamable-http" and stores the HTTP endpoint URL.
        This is framework code; the actual HTTP connection is managed
        by the MCP client runtime.
        """
        self.transport = "streamable-http"
        self.http_url = url
        self.sse_url = None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def check_health(self) -> str:
        """Check whether this MCP server is healthy.

        - For stdio transport: verifies the command exists and is executable.
        - For sse/streamable-http transport: attempts a lightweight HTTP request
          to the configured URL.

        Returns one of "healthy", "unhealthy", or "unknown".
        Side effect: updates self.health_status and self.last_health_check.
        """
        self.last_health_check = datetime.now().isoformat()

        if self.transport == "stdio":
            try:
                result = subprocess.run(
                    [self.command, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    self.health_status = "healthy"
                else:
                    self.health_status = "unhealthy"
            except Exception:
                self.health_status = "unhealthy"
        elif self.transport in ("sse", "streamable-http"):
            target_url = self.sse_url or self.http_url
            if not target_url:
                self.health_status = "unknown"
            else:
                try:
                    import urllib.request
                    req = urllib.request.Request(target_url, method="HEAD")
                    urllib.request.urlopen(req, timeout=5)
                    self.health_status = "healthy"
                except Exception:
                    self.health_status = "unhealthy"
        else:
            self.health_status = "unknown"

        return self.health_status


# ----------------------------------------------------------------------
# Preset MCP Servers
# ----------------------------------------------------------------------

PRESET_MCP_SERVERS: List[MCPServer] = [
    # --- existing servers ---
    MCPServer(
        name="GitHub",
        description="自然语言操作GitHub仓库/Issue/PR/CI。生态最广泛使用的Server。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        category="源码管理",
        tags=["github", "git", "ci", "issues"],
    ),
    MCPServer(
        name="Context7",
        description="实时查询最新版本文档，消除AI幻觉。支持1000+库的实时文档。",
        command="npx",
        args=["-y", "@upstash/context7-mcp"],
        env={"CONTEXT7_API_KEY": ""},
        category="开发工具",
        tags=["docs", "reference", "llm"],
    ),
    MCPServer(
        name="Sequential Thinking",
        description="逐步推理引擎，复杂问题拆解。支持思维链、分支、修正。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sequential-thinking"],
        category="推理",
        tags=["reasoning", "chain-of-thought", "problem-solving"],
    ),
    MCPServer(
        name="Filesystem",
        description="安全读写文件系统，支持指定工作目录范围。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
        category="系统",
        tags=["files", "io", "local"],
    ),
    MCPServer(
        name="Playwright",
        description="微软出品浏览器自动化(20k⭐)。AI像人类一样操作浏览器。",
        command="npx",
        args=["-y", "@playwright/mcp"],
        category="前端",
        tags=["browser", "testing", "automation", "e2e"],
    ),
    MCPServer(
        name="Puppeteer",
        description="无头Chrome控制。网页截图、PDF生成、自动化测试。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-puppeteer"],
        category="前端",
        tags=["browser", "testing", "headless", "screenshot"],
    ),
    MCPServer(
        name="Figma",
        description="设计稿对接。读取Figma文件、组件、样式。",
        command="npx",
        args=["-y", "figma-developer-mcp"],
        env={"FIGMA_ACCESS_TOKEN": ""},
        category="设计",
        tags=["design", "ui", "collaboration"],
    ),
    MCPServer(
        name="PostgreSQL",
        description="PostgreSQL数据库查询/管理。支持SQL查询、表结构探索。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        env={"DATABASE_URL": ""},
        category="数据库",
        tags=["database", "sql", "relational"],
    ),
    MCPServer(
        name="SQLite",
        description="本地轻量数据库。适合原型开发和数据分析。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sqlite"],
        env={"SQLITE_PATH": ""},
        category="数据库",
        tags=["database", "sql", "local", "embedded"],
    ),
    MCPServer(
        name="Docker",
        description="容器管理。镜像/容器/网络操作。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-docker"],
        category="DevOps",
        tags=["container", "infrastructure", "orchestration"],
    ),
    MCPServer(
        name="Brave Search",
        description="独立索引搜索引擎。支持网页搜索和本地搜索。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-brave-search"],
        env={"BRAVE_API_KEY": ""},
        category="搜索",
        tags=["search", "web", "privacy"],
    ),
    MCPServer(
        name="Tavily",
        description="AI原生搜索引擎，专门为LLM优化。支持深度搜索。",
        command="npx",
        args=["-y", "tavily-mcp"],
        env={"TAVILY_API_KEY": ""},
        category="搜索",
        tags=["search", "ai", "llm"],
    ),
    MCPServer(
        name="Firecrawl",
        description="精准网页抓取。支持JS渲染、Markdown转换。",
        command="npx",
        args=["-y", "firecrawl-mcp"],
        env={"FIRECRAWL_API_KEY": ""},
        category="搜索",
        tags=["scraping", "web", "markdown"],
    ),
    MCPServer(
        name="Exa",
        description="AI语义搜索+内容提取。原生日期筛选。",
        command="npx",
        args=["-y", "exa-mcp-server"],
        env={"EXA_API_KEY": ""},
        category="搜索",
        tags=["search", "semantic", "ai"],
    ),
    MCPServer(
        name="Arxiv",
        description="学术论文搜索。支持论文检索、摘要获取。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-arxiv"],
        category="学术",
        tags=["academic", "papers", "research"],
    ),
    MCPServer(
        name="Memory",
        description="知识图谱持久记忆。跨会话记忆、实体关系管理。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        category="知识",
        tags=["memory", "knowledge-graph", "persistence"],
    ),
    MCPServer(
        name="Fetch",
        description="HTTP请求。支持GET/POST/JSON/fetch。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-fetch"],
        category="网络",
        tags=["http", "api", "web"],
    ),
    MCPServer(
        name="Everything",
        description="全局文件搜索。跨目录快速检索。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
        category="系统",
        tags=["search", "filesystem", "local"],
    ),
    MCPServer(
        name="Vercel",
        description="一键部署到Vercel。管理项目、域名、环境变量。",
        command="npx",
        args=["-y", "vercel-mcp"],
        env={"VERCEL_TOKEN": ""},
        category="部署",
        tags=["deploy", "hosting", "serverless", "frontend"],
    ),
    MCPServer(
        name="Sentry",
        description="错误追踪和性能监控。查看Issue、事件、堆栈。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sentry"],
        env={"SENTRY_AUTH_TOKEN": ""},
        category="监控",
        tags=["error-tracking", "performance", "monitoring"],
    ),
    # === new servers ===
    MCPServer(
        name="Notion",
        description="连接Notion工作区，读写页面/数据库。",
        command="npx",
        args=["-y", "@notionhq/notion-mcp-server"],
        env={"NOTION_API_TOKEN": ""},
        category="知识",
        tags=["notion", "notes", "wiki", "docs", "collaboration"],
    ),
    MCPServer(
        name="Slack",
        description="Slack消息发送/频道管理。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={"SLACK_BOT_TOKEN": ""},
        category="通讯",
        tags=["slack", "messaging", "chat", "team"],
    ),
    MCPServer(
        name="Obsidian",
        description="读写Obsidian笔记库。",
        command="npx",
        args=["-y", "mcp-obsidian"],
        env={"OBSIDIAN_VAULT_PATH": ""},
        category="知识",
        tags=["obsidian", "notes", "markdown", "knowledge-base"],
    ),
    MCPServer(
        name="Linear",
        description="项目管理/Issue跟踪。",
        command="npx",
        args=["-y", "@linear/mcp"],
        env={"LINEAR_API_KEY": ""},
        category="项目管理",
        tags=["project-management", "issues", "tickets", "agile"],
    ),
    MCPServer(
        name="Supabase",
        description="数据库管理/实时订阅。",
        command="npx",
        args=["-y", "@supabase/mcp-server-supabase"],
        env={"SUPABASE_URL": "", "SUPABASE_KEY": ""},
        category="数据库",
        tags=["database", "postgresql", "realtime", "baas", "serverless"],
    ),
    MCPServer(
        name="Cloudflare",
        description="Workers/Pages/D1/R2一站式管理。",
        command="npx",
        args=["-y", "@cloudflare/mcp-server-cloudflare"],
        env={"CLOUDFLARE_API_TOKEN": ""},
        category="部署",
        tags=["cloudflare", "workers", "edge", "cdn", "serverless"],
    ),
    MCPServer(
        name="Stripe",
        description="支付集成/账单管理。",
        command="npx",
        args=["-y", "@stripe/mcp"],
        env={"STRIPE_SECRET_KEY": ""},
        category="支付",
        tags=["payment", "billing", "stripe", "fintech"],
    ),
    MCPServer(
        name="Resend",
        description="邮件发送/模板管理。",
        command="npx",
        args=["-y", "resend-mcp"],
        env={"RESEND_API_KEY": ""},
        category="通讯",
        tags=["email", "smtp", "templates", "transactional"],
    ),
    MCPServer(
        name="Raycast",
        description="Raycast扩展/快捷操作。",
        command="npx",
        args=["-y", "@raycast/mcp"],
        category="系统",
        tags=["raycast", "productivity", "shortcuts", "macos"],
    ),
    MCPServer(
        name="YouTube",
        description="视频搜索/字幕获取。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-youtube"],
        env={"YOUTUBE_API_KEY": ""},
        category="媒体",
        tags=["youtube", "video", "transcript", "search"],
    ),
    MCPServer(
        name="Spotify",
        description="音乐播放控制。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-spotify"],
        env={"SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": ""},
        category="媒体",
        tags=["spotify", "music", "audio", "playback"],
    ),
    MCPServer(
        name="GitLab",
        description="GitLab仓库/Issue/MR/CI。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-gitlab"],
        env={"GITLAB_PERSONAL_ACCESS_TOKEN": ""},
        category="源码管理",
        tags=["gitlab", "git", "ci", "mr", "devops"],
    ),
    MCPServer(
        name="Neon",
        description="Serverless PostgreSQL。",
        command="npx",
        args=["-y", "@neondatabase/mcp-server-neon"],
        env={"NEON_API_KEY": ""},
        category="数据库",
        tags=["database", "postgresql", "serverless", "neon"],
    ),
    MCPServer(
        name="Axiom",
        description="日志查询/分析/监控。",
        command="npx",
        args=["-y", "@axiomhq/mcp"],
        env={"AXIOM_TOKEN": ""},
        category="监控",
        tags=["logging", "observability", "analytics", "monitoring"],
    ),
]


# ----------------------------------------------------------------------
# MCP Manager
# ----------------------------------------------------------------------

class MCPManager:
    def __init__(self):
        MCP_DIR.mkdir(parents=True, exist_ok=True)
        self.servers: Dict[str, MCPServer] = {}
        self.running_processes: Dict[str, subprocess.Popen] = {}
        self._load()

    def _load(self) -> None:
        if MCP_CONFIG_FILE.exists():
            try:
                with open(MCP_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for server_data in data:
                    try:
                        server = MCPServer.from_dict(server_data)
                        self.servers[server.name] = server
                    except (KeyError, TypeError, ValueError) as e:
                        logger.warning(f"跳过损坏的 MCP 配置项: {e}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"MCP 配置文件读取失败: {e}，使用预设配置")
                self.servers = {}
            # Merge in any new preset servers not yet in saved config
            for preset in PRESET_MCP_SERVERS:
                if preset.name not in self.servers:
                    self.servers[preset.name] = preset
            self._save()
        else:
            for server in PRESET_MCP_SERVERS:
                self.servers[server.name] = server
            self._save()

    def _save(self) -> None:
        MCP_DIR.mkdir(parents=True, exist_ok=True)
        data = [s.to_dict() for s in self.servers.values()]
        with open(MCP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Basic CRUD
    # ------------------------------------------------------------------
    def list_servers(self) -> List[MCPServer]:
        return sorted(self.servers.values(), key=lambda s: (s.category, s.name))

    def get_server(self, name: str) -> Optional[MCPServer]:
        return self.servers.get(name)

    def enable(self, name: str) -> bool:
        if name in self.servers:
            self.servers[name].enabled = True
            self._save()
            return True
        return False

    def disable(self, name: str) -> bool:
        if name in self.servers:
            self.servers[name].enabled = False
            self._save()
            return True
        return False

    def add_server(
        self,
        name: str,
        description: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        category: str = "custom",
        transport: str = "stdio",
        sse_url: Optional[str] = None,
        http_url: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> MCPServer:
        server = MCPServer(
            name=name,
            description=description,
            command=command,
            args=args,
            env=env,
            category=category,
            transport=transport,
            sse_url=sse_url,
            http_url=http_url,
            tags=tags,
        )
        self.servers[name] = server
        self._save()
        return server

    def remove_server(self, name: str) -> bool:
        if name in self.servers:
            # stop process if running
            self.stop_server(name)
            del self.servers[name]
            self._save()
            return True
        return False

    def get_categories(self) -> List[str]:
        cats = set()
        for s in self.servers.values():
            cats.add(s.category)
        return sorted(cats)

    def get_by_category(self, category: str) -> List[MCPServer]:
        return [s for s in self.servers.values() if s.category == category]

    def get_enabled(self) -> List[MCPServer]:
        return [s for s in self.servers.values() if s.enabled]

    def get_stats(self) -> Dict[str, int]:
        enabled = self.get_enabled()
        return {
            "total": len(self.servers),
            "enabled": len(enabled),
            "categories": len(self.get_categories()),
        }

    # ------------------------------------------------------------------
    # Tags & grouping
    # ------------------------------------------------------------------
    def get_by_tag(self, tag: str) -> List[MCPServer]:
        """Return all servers that have the given tag (case-insensitive)."""
        tag_lower = tag.lower()
        return [s for s in self.servers.values() if tag_lower in (t.lower() for t in s.tags)]

    def get_popular_servers(self) -> List[MCPServer]:
        """Return the most commonly used / recommended MCP servers."""
        popular_names = {
            "GitHub", "Filesystem", "Playwright", "Brave Search",
            "Sequential Thinking", "Memory", "Fetch", "Context7",
            "Figma", "PostgreSQL", "Notion", "Slack", "Linear",
            "Supabase", "Cloudflare", "Stripe", "GitLab",
        }
        return [s for s in self.servers.values() if s.name in popular_names]

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------
    def start_server(self, name: str) -> Tuple[bool, str]:
        """Start an MCP server process.

        Launches the server as a subprocess using the configured command/args
        and injects any environment variables. The process is tracked in
        self.running_processes.

        Returns (success, message).
        """
        server = self.servers.get(name)
        if server is None:
            return False, f"Server '{name}' not found"

        if name in self.running_processes:
            proc = self.running_processes[name]
            if proc.poll() is None:
                return False, f"Server '{name}' is already running (pid={proc.pid})"

        try:
            cmd = [server.command] + server.args
            merged_env = os.environ.copy()
            merged_env.update(server.env)

            proc = subprocess.Popen(
                cmd,
                env=merged_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.running_processes[name] = proc
            return True, f"Server '{name}' started (pid={proc.pid})"
        except Exception as e:
            return False, f"Failed to start '{name}': {e}"

    def stop_server(self, name: str) -> Tuple[bool, str]:
        """Stop a running MCP server process.

        Sends SIGTERM (or CTRL_BREAK_EVENT on Windows) and waits for the
        process to exit gracefully, then force-kills if necessary.

        Returns (success, message).
        """
        if name not in self.running_processes:
            return False, f"Server '{name}' is not running"

        proc = self.running_processes[name]
        if proc.poll() is not None:
            del self.running_processes[name]
            return True, f"Server '{name}' was already stopped"

        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

            del self.running_processes[name]
            return True, f"Server '{name}' stopped"
        except Exception as e:
            # force cleanup
            try:
                proc.kill()
            except Exception:
                pass
            self.running_processes.pop(name, None)
            return False, f"Error stopping '{name}': {e}"

    def restart_server(self, name: str) -> Tuple[bool, str]:
        """Restart an MCP server process (stop + start)."""
        stop_ok, stop_msg = self.stop_server(name)
        time.sleep(0.5)
        start_ok, start_msg = self.start_server(name)
        if start_ok:
            return True, f"Server '{name}' restarted"
        else:
            return False, f"Restart failed for '{name}': stop={stop_msg}, start={start_msg}"

    def stop_all(self) -> List[Tuple[str, bool, str]]:
        """Stop all running MCP server processes.

        Returns a list of (name, success, message) tuples.
        """
        results = []
        for name in list(self.running_processes.keys()):
            ok, msg = self.stop_server(name)
            results.append((name, ok, msg))
        return results

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def check_all_health(self) -> Dict[str, str]:
        """Run health checks on all registered servers.

        Returns a dict mapping server name -> health status.
        """
        results = {}
        for name, server in self.servers.items():
            status = server.check_health()
            results[name] = status
        self._save()
        return results

    def get_unhealthy_servers(self) -> List[MCPServer]:
        """Return all servers with health_status == 'unhealthy'.

        Does NOT run new checks; only reports the last-known status.
        """
        return [s for s in self.servers.values() if s.health_status == "unhealthy"]

    # ------------------------------------------------------------------
    # Config generation
    # ------------------------------------------------------------------
    def generate_mcp_json(self) -> Dict[str, Any]:
        config = {"mcpServers": {}}
        for server in self.get_enabled():
            entry: Dict[str, Any] = {
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                entry["env"] = {k: v for k, v in server.env.items()}
            if server.transport != "stdio":
                entry["transport"] = server.transport
                if server.sse_url:
                    entry["sse_url"] = server.sse_url
                if server.http_url:
                    entry["http_url"] = server.http_url
            config["mcpServers"][server.name] = entry
        return config

    def export_config(self) -> str:
        config = self.generate_mcp_json()
        output = json.dumps(config, indent=2, ensure_ascii=False)
        output_path = MCP_DIR / "mcp.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        return str(output_path)

    # ------------------------------------------------------------------
    # Client-specific config export
    # ------------------------------------------------------------------
    def export_claude_desktop_config(self) -> str:
        """Export config in Claude Desktop format.

        Claude Desktop uses the standard mcpServers JSON structure.
        Saved to mcp_data/claude_desktop_config.json.
        """
        config = {"mcpServers": {}}
        for server in self.get_enabled():
            entry: Dict[str, Any] = {
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                entry["env"] = {k: v for k, v in server.env.items()}
            config["mcpServers"][server.name] = entry
        output = json.dumps(config, indent=2, ensure_ascii=False)
        output_path = MCP_DIR / "claude_desktop_config.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        return str(output_path)

    def export_cursor_config(self) -> str:
        """Export config in Cursor IDE format.

        Cursor uses a .cursor/mcp.json file with a 'mcpServers' key.
        Saved to mcp_data/cursor_mcp_config.json.
        """
        config = {"mcpServers": {}}
        for server in self.get_enabled():
            entry: Dict[str, Any] = {
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                entry["env"] = {k: v for k, v in server.env.items()}
            if server.transport != "stdio":
                entry["transport"] = server.transport
            config["mcpServers"][server.name] = entry
        output = json.dumps(config, indent=2, ensure_ascii=False)
        output_path = MCP_DIR / "cursor_mcp_config.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        return str(output_path)

    def export_windsurf_config(self) -> str:
        """Export config in Windsurf IDE format.

        Windsurf uses a .windsurf/mcp.json file with a 'mcpServers' key.
        Saved to mcp_data/windsurf_mcp_config.json.
        """
        config = {"mcpServers": {}}
        for server in self.get_enabled():
            entry: Dict[str, Any] = {
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                entry["env"] = {k: v for k, v in server.env.items()}
            if server.transport != "stdio":
                entry["transport"] = server.transport
            config["mcpServers"][server.name] = entry
        output = json.dumps(config, indent=2, ensure_ascii=False)
        output_path = MCP_DIR / "windsurf_mcp_config.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        return str(output_path)