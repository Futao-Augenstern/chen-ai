# 更新日志

所有重要的变更都会记录在这个文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-07-08

### 新增

- 多模型支持：12 家模型提供商（OpenAI、DeepSeek、通义千问、Kimi、智谱 GLM 等）
- CLI 命令行界面，支持 20+ 条斜杠命令
- Web UI 界面（Gradio），5 个功能 Tab
- ReAct Agent 模式，支持自我反思和并行工具调用
- 三层记忆系统：工作记忆、情景记忆、语义记忆
- 40+ 预设技能，覆盖编程、设计、写作、工作等多个领域
- 7 个内置工具：搜索、代码执行、计算器、文件操作等
- MCP 服务器配置管理，支持 20+ 预设 MCP Server
- Prompt 压缩与缓存优化
- 断路器 + 指数退避重试机制
- 分布式追踪与指标收集
- 事件钩子系统
