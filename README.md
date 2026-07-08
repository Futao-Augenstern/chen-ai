# chen-ai

一个功能强大的多模型 AI 智能助手，支持多种大语言模型提供商，内置记忆系统、技能系统、工具调用和 MCP 服务器。

## 功能特性

- **多模型支持** - 支持 OpenAI、DeepSeek、通义千问、Kimi、智谱 GLM、百度文心、Groq、硅基流动等 10+ 服务商
- **记忆系统** - 上下文管理 + 长期记忆，支持对话历史持久化
- **技能系统** - 可扩展的技能框架，支持自定义技能
- **工具调用** - 内置工具注册表，支持函数调用
- **MCP 服务器** - 兼容 Model Context Protocol
- **Web 界面** - 基于 Gradio 的 Web UI
- **命令行界面** - 支持交互式命令行对话
- **缓存优化** - 智能提示词压缩，减少 token 消耗
- **弹性重试** - 自动故障转移和重试机制

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

## 项目结构

```
chen-ai/
├── main.py              # 主入口（命令行界面）
├── web_ui.py            # Web 界面（Gradio）
├── ai_core.py           # AI 对话核心
├── agent_loop.py        # Agent 主循环
├── memory.py            # 记忆系统
├── skills.py            # 技能管理器
├── tools.py             # 工具注册表
├── mcp_server.py        # MCP 服务器
├── context_manager.py   # 上下文管理器
├── prompt_compressor.py # 提示词压缩
├── cache_optimizer.py   # 缓存优化
├── resilience.py        # 弹性重试
├── hooks.py             # 钩子系统
├── telemetry.py         # 遥测
├── config.py            # 配置管理
├── providers.json       # 模型提供商配置
├── requirements.txt     # Python 依赖
├── tests.py             # 测试
└── run.bat / run.ps1    # 一键运行脚本
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

## 许可证

MIT License
