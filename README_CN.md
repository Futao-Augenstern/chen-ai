# chen-ai

一个**安全、零依赖、支持 12 家国产大模型的多智能体 AI 助手**。

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.1-blue.svg)]()
[![Tests](https://img.shields.io/badge/Tests-80%2F80-green.svg)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[English](README.md) | 中文

---

## 为什么选择 chen-ai？

| 特性 | chen-ai | Open Interpreter | LangChain | AutoGPT | CrewAI |
|------|---------|-----------------|-----------|---------|--------|
| 零依赖核心 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 沙箱安全代码执行 | ✅ AST 级别 | ✅ subprocess | ❌ | ❌ | ❌ |
| 12 家模型提供商 | ✅ | ✅ | ✅ | ✅ | ✅ |
| Plan-Execute Agent | ✅ | ❌ | ❌ | ❌ | ❌ |
| 三层记忆系统 | ✅ | ❌ | ✅ 基础 | ✅ 基础 | ❌ |
| MCP Server 生态 | ✅ 35 个预设 | ❌ | ❌ | ❌ | ❌ |
| 命令行 + Web UI | ✅ | ✅ | ✅ | ✅ | ✅ |
| 纯 Python 实现 | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 功能特性

- **多模型支持** — OpenAI、DeepSeek、通义千问、Kimi、智谱 GLM、百度文心、Groq、硅基流动等 12 家服务商
- **记忆系统** — 三层记忆架构（工作记忆 + 情景记忆 + 语义记忆），支持向量语义检索和 RAG 文档检索
- **技能系统** — 73 个预设技能，可扩展的技能框架，支持关键词智能推荐
- **工具调用** — ReAct Agent 模式 + Plan-Execute Agent 模式，11 个内置工具，支持并行工具执行
- **多 Agent 协作** — 多 Agent 协作框架，任务依赖拓扑排序
- **代码沙箱** — AST 级别的代码安全检查，白名单模块导入，输出截断
- **MCP 服务器** — 兼容 Model Context Protocol，35 个预设配置，支持 SSE/Streamable HTTP
- **Web 界面** — 基于 Gradio 的 Web UI，5 个功能 Tab
- **命令行界面** — 20+ 条斜杠命令，交互式对话
- **缓存优化** — 前缀缓存 + 提示词压缩，减少 token 消耗
- **弹性重试** — 断路器 + 指数退避，提高 API 调用可靠性
- **遥测系统** — 分布式追踪 + 指标收集

---

## 快速开始

### 安装

核心功能零依赖，仅需 `python-dotenv`：

```bash
# 基础安装
pip install chen-ai

# 完整安装（包含所有可选依赖）
pip install chen-ai[full]
```

### Docker 一键部署

```bash
docker run -p 7860:7860 \
  -e OPENAI_API_KEY=sk-your-key \
  -e PROVIDER=OpenAI \
  ghcr.io/futao-augenstern/chen-ai
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 填入你的 API 密钥
```

### 运行

```bash
# 命令行模式
chen-ai chat

# Web UI 模式
chen-ai web
```

或者直接运行源文件：

```bash
python main.py        # 命令行
python web_ui.py      # Web 界面
```

更多示例请查看 [examples/](examples/) 目录。

---

## 支持的模型提供商

| 提供商 | 环境变量 | 状态 |
|--------|----------|------|
| OpenAI | `OPENAI_API_KEY` | ✅ |
| DeepSeek | `DEEPSEEK_API_KEY` | ✅ |
| 通义千问 | `DASHSCOPE_API_KEY` | ✅ |
| Moonshot (Kimi) | `MOONSHOT_API_KEY` | ✅ |
| 智谱 GLM | `ZHIPUAI_API_KEY` | ✅ |
| 百度文心 | `BAIDU_API_KEY` | ✅ |
| 零一万物 | `LINGYIWANWU_API_KEY` | ✅ |
| Groq | `GROQ_API_KEY` | ✅ |
| Together AI | `TOGETHER_API_KEY` | ✅ |
| 硅基流动 | `SILICONFLOW_API_KEY` | ✅ |
| Ollama (本地) | - | ✅ |
| 自定义 | `OPENAI_BASE_URL` | ✅ |

---

## 项目结构

```
chen-ai/
├── main.py              # 主入口（命令行界面）
├── web_ui.py            # Web 界面（Gradio）
├── ai_core.py           # AI 对话核心
├── agent_loop.py        # Agent 主循环 (ReAct + Plan-Execute)
├── memory.py            # 三层记忆系统
├── skills.py            # 技能管理器（73 个技能）
├── tools.py             # 工具注册表（11 个工具 + 沙箱）
├── mcp_server.py        # MCP 服务器管理（35 个预设）
├── context_manager.py   # 上下文窗口管理
├── prompt_compressor.py # 提示词压缩
├── cache_optimizer.py   # 缓存优化 + 成本追踪
├── resilience.py        # 弹性重试 + 断路器
├── hooks.py             # 钩子系统
├── telemetry.py         # 遥测（追踪 + 指标）
├── config.py            # 配置管理
├── providers.json       # 模型提供商配置
├── tests.py             # 80 个测试用例
├── examples/            # 使用示例
└── .github/             # GitHub 配置
```

---

## 开发

```bash
# 运行测试（80 个用例）
python tests.py

# 安装开发依赖
pip install -e ".[dev]"
```

每行代码都经过 80 个单元测试和 22 个压力测试（边界、并发、沙箱安全、压力、原子写入、损坏恢复）。

---

## 社区

- [提交 Issue](https://github.com/Futao-Augenstern/chen-ai/issues) — 报告 Bug 或建议新功能
- [贡献指南](CONTRIBUTING.md) — 参与贡献
- [更新日志](CHANGELOG.md) — 版本历史

---

## 许可证

[MIT License](LICENSE)

---

## 星标历史

如果这个项目对你有帮助，请给一个 ⭐ Star 支持一下！