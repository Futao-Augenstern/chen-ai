# 更新日志

所有重要的变更都会记录在这个文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.1] - 2026-07-09

### 新增

- **Skills 系统**: 从 51 个扩展到 73 个技能，新增自动化测试、后端架构、微服务、移动端、数据工程、NLP/CV、量化交易、区块链、增长黑客、SEO、产品策略、敏捷教练、架构评审、成本优化、云原生安全等 22 个技能
- **MCP Server**: 从 21 个扩展到 35 个 Server，新增 Notion、Slack、Obsidian、Linear、Supabase、Cloudflare、Stripe、GitLab、Neon、YouTube、Spotify 等
- **MCP 传输**: 新增 SSE 和 Streamable HTTP 传输协议支持
- **MCP 导出**: 一键导出 Claude Desktop、Cursor、Windsurf 配置文件
- **Tools**: 从 7 个扩展到 11 个工具，新增 Image、Browser、Markdown、HTTP 工具
- **Memory**: 新增向量语义检索（TF-IDF）、RAG 文档检索、K-means 记忆聚类、艾宾浩斯遗忘曲线
- **Agent Loop**: 新增 PlanExecutor（Plan-Execute-Verify 模式）、MultiAgentCoordinator（多 Agent 协作）、TaskTracker（任务追踪）、自动执行模式切换
- **AgentConfig**: 配置常量类，消除 30+ 魔法数字
- **__init__.py**: 新增包初始化文件，支持 pip install 安装
- **CLI argparse**: 新增 7 个命令行参数（--provider/--model/--web/--port/--no-stream/--config/--skills/--mcp）
- **测试**: 从 41 个扩展到 80 个测试，覆盖 PlanExecutor、MultiAgentCoordinator、Skills 高级、MCP 高级、Memory 高级、Tools 高级

### 变更

- **依赖全部可选**: openai、gradio、rich、pydantic、tiktoken、numpy 全部改为可选依赖，零依赖可运行核心功能
- **config.py 重写**: 添加错误处理、默认配置回退、环境变量覆盖、mtime 缓存失效检测
- **main.py**: 修复 Status spinner 与流式响应冲突，修复 --no-stream 崩溃，修复 run.bat 路径
- **web_ui.py**: 全局状态改为 SessionState + gr.State() session 级别，新增 start_web_server 函数
- **context_manager.py**: truncate_messages() 从 O(n²) 优化为 O(n)
- **cache_optimizer.py**: CostTracker._load() 在 __init__ 中调用，恢复历史成本数据
- **prompt_compressor.py**: 添加 try/except 错误处理
- **resilience.py**: 参数改为从环境变量读取
- **examples/**: 全部添加 try/except 错误处理和 API Key 检查
- **版本号**: 统一为 1.0.1（原 v3.0/0.1.0 混乱）

### 修复

- 45 处 except Exception 全部添加日志记录
- 4 个文件清理未使用的 import（Union、Tuple）
- 示例文件 SYSTEM_PROMT 拼写错误修复
- GitHub Issue 模板内容交换修复
- providers.json 添加 api_key_env 字段
- 启动时 API Key 警告从 12 条刷屏改为 1 条摘要

## [0.1.0] - 2026-07-08

### 新增

- 多模型支持：12 家模型提供商（OpenAI、DeepSeek、通义千问、Kimi、智谱 GLM 等）
- CLI 命令行界面，支持 20+ 条斜杠命令
- Web UI 界面（Gradio），5 个功能 Tab
- ReAct Agent 模式，支持自我反思和并行工具调用
- 三层记忆系统：工作记忆、情景记忆、语义记忆
- 51 个预设技能，覆盖编程、设计、写作、工作等多个领域
- 7 个内置工具：搜索、代码执行、计算器、文件操作等
- MCP 服务器配置管理，支持 21 个预设 MCP Server
- Prompt 压缩与缓存优化
- 断路器 + 指数退避重试机制
- 分布式追踪与指标收集
- 事件钩子系统