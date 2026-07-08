import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
        )
        server.enabled = data.get("enabled", False)
        server.installed = data.get("installed", False)
        server.created_at = data.get("created_at", datetime.now().isoformat())
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


PRESET_MCP_SERVERS: List[MCPServer] = [
    MCPServer(
        name="GitHub",
        description="自然语言操作GitHub仓库/Issue/PR/CI。生态最广泛使用的Server。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        category="源码管理",
    ),
    MCPServer(
        name="Context7",
        description="实时查询最新版本文档，消除AI幻觉。支持1000+库的实时文档。",
        command="npx",
        args=["-y", "@upstash/context7-mcp"],
        env={"CONTEXT7_API_KEY": ""},
        category="开发工具",
    ),
    MCPServer(
        name="Sequential Thinking",
        description="逐步推理引擎，复杂问题拆解。支持思维链、分支、修正。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sequential-thinking"],
        category="推理",
    ),
    MCPServer(
        name="Filesystem",
        description="安全读写文件系统，支持指定工作目录范围。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
        category="系统",
    ),
    MCPServer(
        name="Playwright",
        description="微软出品浏览器自动化(20k⭐)。AI像人类一样操作浏览器。",
        command="npx",
        args=["-y", "@playwright/mcp"],
        category="前端",
    ),
    MCPServer(
        name="Puppeteer",
        description="无头Chrome控制。网页截图、PDF生成、自动化测试。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-puppeteer"],
        category="前端",
    ),
    MCPServer(
        name="Figma",
        description="设计稿对接。读取Figma文件、组件、样式。",
        command="npx",
        args=["-y", "figma-developer-mcp"],
        env={"FIGMA_ACCESS_TOKEN": ""},
        category="设计",
    ),
    MCPServer(
        name="PostgreSQL",
        description="PostgreSQL数据库查询/管理。支持SQL查询、表结构探索。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        env={"DATABASE_URL": ""},
        category="数据库",
    ),
    MCPServer(
        name="SQLite",
        description="本地轻量数据库。适合原型开发和数据分析。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sqlite"],
        env={"SQLITE_PATH": ""},
        category="数据库",
    ),
    MCPServer(
        name="Docker",
        description="容器管理。镜像/容器/网络操作。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-docker"],
        category="DevOps",
    ),
    MCPServer(
        name="Brave Search",
        description="独立索引搜索引擎。支持网页搜索和本地搜索。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-brave-search"],
        env={"BRAVE_API_KEY": ""},
        category="搜索",
    ),
    MCPServer(
        name="Tavily",
        description="AI原生搜索引擎，专门为LLM优化。支持深度搜索。",
        command="npx",
        args=["-y", "tavily-mcp"],
        env={"TAVILY_API_KEY": ""},
        category="搜索",
    ),
    MCPServer(
        name="Firecrawl",
        description="精准网页抓取。支持JS渲染、Markdown转换。",
        command="npx",
        args=["-y", "firecrawl-mcp"],
        env={"FIRECRAWL_API_KEY": ""},
        category="搜索",
    ),
    MCPServer(
        name="Exa",
        description="AI语义搜索+内容提取。原生日期筛选。",
        command="npx",
        args=["-y", "exa-mcp-server"],
        env={"EXA_API_KEY": ""},
        category="搜索",
    ),
    MCPServer(
        name="Arxiv",
        description="学术论文搜索。支持论文检索、摘要获取。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-arxiv"],
        category="学术",
    ),
    MCPServer(
        name="Memory",
        description="知识图谱持久记忆。跨会话记忆、实体关系管理。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        category="知识",
    ),
    MCPServer(
        name="Fetch",
        description="HTTP请求。支持GET/POST/JSON/fetch。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-fetch"],
        category="网络",
    ),
    MCPServer(
        name="Everything",
        description="全局文件搜索。跨目录快速检索。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
        category="系统",
    ),
    MCPServer(
        name="Vercel",
        description="一键部署到Vercel。管理项目、域名、环境变量。",
        command="npx",
        args=["-y", "vercel-mcp"],
        env={"VERCEL_TOKEN": ""},
        category="部署",
    ),
    MCPServer(
        name="Sentry",
        description="错误追踪和性能监控。查看Issue、事件、堆栈。",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sentry"],
        env={"SENTRY_AUTH_TOKEN": ""},
        category="监控",
    ),
]


class MCPManager:
    def __init__(self):
        MCP_DIR.mkdir(parents=True, exist_ok=True)
        self.servers: Dict[str, MCPServer] = {}
        self._load()

    def _load(self) -> None:
        if MCP_CONFIG_FILE.exists():
            with open(MCP_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for server_data in data:
                    server = MCPServer.from_dict(server_data)
                    self.servers[server.name] = server
        else:
            for server in PRESET_MCP_SERVERS:
                self.servers[server.name] = server
            self._save()

    def _save(self) -> None:
        data = [s.to_dict() for s in self.servers.values()]
        with open(MCP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

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
    ) -> MCPServer:
        server = MCPServer(name, description, command, args, env, category)
        self.servers[name] = server
        self._save()
        return server

    def remove_server(self, name: str) -> bool:
        if name in self.servers:
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

    def generate_mcp_json(self) -> Dict[str, Any]:
        config = {"mcpServers": {}}
        for server in self.get_enabled():
            entry: Dict[str, Any] = {
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                entry["env"] = {k: v for k, v in server.env.items()}
            config["mcpServers"][server.name] = entry
        return config

    def export_config(self) -> str:
        config = self.generate_mcp_json()
        output = json.dumps(config, indent=2, ensure_ascii=False)
        output_path = MCP_DIR / "mcp.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        return str(output_path)