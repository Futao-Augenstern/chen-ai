# chen-ai

A **secure, zero-dependency, multi-agent AI assistant** supporting 12 LLM providers.

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.1-blue.svg)]()
[![Tests](https://img.shields.io/badge/Tests-80%2F80-green.svg)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

English | [中文](README_CN.md)

---

## Why chen-ai?

| Feature | chen-ai | Fabric | Aider | Open Interpreter |
|---------|---------|--------|-------|-----------------|
| Zero-dependency core | ✅ | ❌ | ❌ | ❌ |
| Sandbox code execution | ✅ AST-level | ❌ | ❌ | ✅ subprocess |
| 12 providers | ✅ | ✅ | ✅ | ✅ |
| Plan-Execute Agent | ✅ | ❌ | ❌ | ❌ |
| Three-layer memory | ✅ | ❌ | ❌ | ❌ |
| MCP Server ecosystem | ✅ 35 presets | ❌ | ❌ | ❌ |
| CLI + Web UI | ✅ | ✅ | ✅ | ✅ |
| Pure Python | ✅ | ✅ | ✅ | ✅ |

---

## Features

- **Multi-Provider** — OpenAI, DeepSeek, Qwen, Kimi, GLM, ERNIE, Groq, SiliconFlow, and more (12 providers)
- **Memory System** — Three-layer architecture (working + episodic + semantic), vector semantic search, and RAG
- **Skill System** — 73 built-in skills, extensible framework, keyword-based smart recommendations
- **Tool Calling** — ReAct Agent + Plan-Execute Agent, 11 built-in tools, parallel execution
- **Multi-Agent** — Collaborative agent framework with task dependency topological sorting
- **Code Sandbox** — AST-level security checks, module whitelist, output truncation
- **MCP Servers** — Model Context Protocol compatible, 35 preset configurations, SSE/Streamable HTTP
- **Web UI** — Gradio-based interface with 5 functional tabs
- **CLI** — 20+ slash commands, interactive chat
- **Cache Optimization** — Prefix caching + prompt compression
- **Resilience** — Circuit breaker + exponential backoff retry
- **Telemetry** — Distributed tracing + metrics collection

---

## Quick Start

### Installation

```bash
# Minimal install (only python-dotenv required)
pip install chen-ai

# Full install
pip install chen-ai[full]
```

### Docker

```bash
docker run -p 7860:7860 \
  -e OPENAI_API_KEY=sk-your-key \
  -e PROVIDER=OpenAI \
  ghcr.io/futao-augenstern/chen-ai
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your API keys
```

### Usage

```bash
# CLI mode
chen-ai chat

# Web UI mode
chen-ai web
```

Or run source files directly:

```bash
python main.py        # CLI
python web_ui.py      # Web UI
```

See [examples/](examples/) for more.

---

## Supported Providers

| Provider | Env Variable | Status |
|----------|-------------|--------|
| OpenAI | `OPENAI_API_KEY` | ✅ |
| DeepSeek | `DEEPSEEK_API_KEY` | ✅ |
| Qwen (Tongyi) | `DASHSCOPE_API_KEY` | ✅ |
| Moonshot (Kimi) | `MOONSHOT_API_KEY` | ✅ |
| Zhipu GLM | `ZHIPUAI_API_KEY` | ✅ |
| Baidu ERNIE | `BAIDU_API_KEY` | ✅ |
| Lingyiwanwu | `LINGYIWANWU_API_KEY` | ✅ |
| Groq | `GROQ_API_KEY` | ✅ |
| Together AI | `TOGETHER_API_KEY` | ✅ |
| SiliconFlow | `SILICONFLOW_API_KEY` | ✅ |
| Ollama (local) | - | ✅ |
| Custom | `OPENAI_BASE_URL` | ✅ |

---

## Architecture

```
chen-ai/
├── main.py              # CLI entry point
├── web_ui.py            # Web UI (Gradio)
├── ai_core.py           # AI chat core
├── agent_loop.py        # Agent loop (ReAct + Plan-Execute)
├── memory.py            # Three-layer memory system
├── skills.py            # Skill manager (73 skills)
├── tools.py             # Tool registry (11 tools + sandbox)
├── mcp_server.py        # MCP server manager (35 presets)
├── context_manager.py   # Context window management
├── prompt_compressor.py # Prompt compression
├── cache_optimizer.py   # Cache optimization + cost tracking
├── resilience.py        # Circuit breaker + retry
├── hooks.py             # Hook system
├── telemetry.py         # Tracing + metrics
├── config.py            # Configuration
├── providers.json       # Provider configs
├── tests.py             # 80 test cases
├── examples/            # Usage examples
└── .github/             # GitHub config
```

---

## Development

```bash
# Run tests (80 cases)
python tests.py

# Install dev dependencies
pip install -e ".[dev]"
```

Every line of code is covered by 80 unit tests and 22 stress tests (boundary, concurrency, sandbox security, pressure, atomic writes, corruption recovery).

---

## Community

- [Issues](https://github.com/Futao-Augenstern/chen-ai/issues) — Bug reports & feature requests
- [Contributing](CONTRIBUTING.md) — How to contribute
- [Changelog](CHANGELOG.md) — Release history

---

## License

[MIT License](LICENSE)

---

## Star History

If you find this project helpful, please give it a ⭐ Star!