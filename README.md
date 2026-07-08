# chen-ai

一个功能强大的多模型 AI 智能助手，支持多种大语言模型提供商，内置记忆系统、技能系统、工具调用和 MCP 服务器。

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

## 功能特性

- **多模型支持** - 支持 OpenAI、DeepSeek、通义千问、Kimi、智谱 GLM、百度文心、Groq、硅基流动等 10+ 服务商
- **记忆系统** - 三层记忆架构（工作记忆 + 情景记忆 + 语义记忆），支持对话历史持久化
- **技能系统** - 40+ 预设技能，可扩展的技能框架，支持关键词智能推荐
- **工具调用** - ReAct Agent 模式，7 个内置工具，支持并行工具执行
- **MCP 服务器** - 兼容 Model Context Protocol，20+ 预设 MCP Server 配置
- **Web 界面** - 基于 Gradio 的 Web UI，5 个功能 Tab
- **命令行界面** - 支持交互式命令行对话，20+ 条斜杠命令
- **缓存优化** - 前缀缓存 + 提示词压缩，减少 token 消耗
- **弹性重试** - 断路器 + 指数退避重试，提高 API 调用可靠性
- **遥测系统** - 分布式追踪 + 指标收集

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境变量

复制 `.env.example` 为 `.env` 并填入你的 API 密钥：

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置你的 API 密钥和默认模型提供商。

### 运行

**命令行模式：**

```bash
python main.py
```

**Web UI 模式：**

```bash
python web_ui.py
```

更多示例请查看 [examples/](examples/) 目录。

## 项目结构

```
chen-ai/
├── main.py              # 主入口（命令行界面）
├── web_ui.py            # Web 界面（Gradio）
├── ai_core.py           # AI 对话核心
├── agent_loop.py        # Agent 主循环 (ReAct)
├── memory.py            # 三层记忆系统
├── skills.py            # 技能管理器
├── tools.py             # 工具注册表
├── mcp_server.py        # MCP 服务器管理
├── context_manager.py   # 上下文窗口管理
├── prompt_compressor.py # 提示词压缩
├── cache_optimizer.py   # 缓存优化 + 成本追踪
├── resilience.py        # 弹性重试 + 断路器
├── hooks.py             # 钩子系统
├── telemetry.py         # 遥测（追踪 + 指标）
├── config.py            # 配置管理
├── providers.json       # 模型提供商配置
├── requirements.txt     # Python 依赖
├── pyproject.toml       # 项目配置
├── tests.py             # 测试
├── examples/            # 使用示例
├── .github/             # GitHub 配置
├── README.md            # 项目说明
├── CHANGELOG.md         # 更新日志
├── CONTRIBUTING.md      # 贡献指南
└── LICENSE              # MIT 许可证
```

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

## 开发

### 运行测试

```bash
# 使用自带测试框架
python tests.py

# 使用 pytest
pip install pytest
pytest tests.py -v
```

### 贡献代码

请参考 [贡献指南](CONTRIBUTING.md)。

## 更新日志

请查看 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT License](LICENSE)
