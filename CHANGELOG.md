# 更新日志

所有重要的变更都会记录在这个文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.2] - 2026-07-09

### 修复

- **Span 泄漏**: `run_stream` 异常路径中未调用 `_finalize()` 导致遥测 Span 永不关闭
- **并行工具顺序**: `_execute_tools_parallel` 使用 `as_completed` 导致结果顺序与输入不一致，改用 `future→index` 映射
- **断路器失效**: `ResilientAPIClient.call()` 对 `CircuitBreakerOpenError` 进行重试，完全破坏断路保护。修复为直接向上传播
- **CostTracker 重置**: `reset()` 调用 `__init__()` 导致从磁盘重新加载历史数据，重置无效
- **Web UI 导出**: `export_chat` 消息计数模式与 `export_history` 格式不匹配，10000 条截断逻辑永不触发
- **Web UI 下载**: `gr.File` 组件期望文件路径，`export_chat` 却返回字符串，导致下载失败
- **AI 环境变量解析**: `AIChat.__init__` 中 `float(os.getenv(...))` 无类型校验，非法值导致崩溃
- **AI 消息内容**: `message.content` 可能为 `None`（推理模型），未做空值检查
- **AI 重试机制**: `_retry_request` 的 `except Exception` 捕获了 `KeyboardInterrupt`，Ctrl+C 无法中断
- **原始消息保存**: `_prepare_message` 在压缩后返回修改后的 `user_message`，导致记忆系统接收压缩文本
- **遥测装饰器**: `timed` 装饰器未使用 `functools.wraps`，丢失函数元数据
- **死代码清理**: 移除未使用的 `_think_llm` 方法
- **错误分类**: 从 network 分支移除重复的 timeout 关键词，`_handle_execution_error` 集成到 `run()` 中
- **工具时区**: 从硬编码 UTC+8 改为 `datetime.now().astimezone()` 获取系统本地时区
- **文件读取 TOCTOU**: 文件大小检查改为读取后检查，防止条件竞争
- **内存增长**: 为 `MemorySystem` 添加 `max_interactions` 上限和 `_prune_interactions()` 淘汰机制
- **冗余导入**: 删除 `CodeExecutionTool.execute()` 内部的重复 `import io, sys`
- **提示词压缩统计**: `savings` 从覆盖改为累加，避免统计失真
- **非原子写入**: `MCPManager._save()`、`PromptCache._save()`、`CostTracker._save()`、`SkillManager._save()`、`Tracer.export()` 共 5 处使用 `open(w)` 直接写入，存在崩溃时数据损坏风险。修复为通过 `utils.atomic_write_json()` 原子写入
- **Web UI 版本号**: 两处硬编码 `v1.0.1` 未随版本升级更新
- **`__init__.py` 版本注释**: 文档字符串中版本号仍为 `1.0.1`
- **错误恢复策略**: `run()` 中 `_handle_execution_error` 分类了错误但从未执行恢复策略（重试/降级）。修复为在 `strategy=retry` 时自动重试简化 prompt

### 新增

- `--version` / `-V` 命令行参数
- `MultiAgentCoordinator.set_roles()` / `restore_roles()` 公开 API
- `utils.py` 共享工具模块，提供 `atomic_write_json()` 原子写入
- 版本号统一升级至 1.0.2
- 测试从 86 扩展到 95 个，覆盖断路器重试、成本重置、提示词压缩统计、环境变量解析、遥测装饰器、内存淘汰、文件读取安全等路径
- 测试进一步扩展到 97 个，新增原子写入、错误恢复覆盖

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