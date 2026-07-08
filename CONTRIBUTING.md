# 贡献指南

感谢你对 chen-ai 项目的关注！欢迎提交 Issue 和 Pull Request。

## 开发环境搭建

### 1. 克隆项目

```bash
git clone https://github.com/Futao-Augenstern/chen-ai.git
cd chen-ai
```

### 2. 创建虚拟环境

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
# 安装开发依赖
pip install pytest pytest-cov pytest-mock
```

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 5. 运行测试

```bash
python tests.py
# 或使用 pytest
pytest tests.py -v
```

## 代码规范

- **Python 版本**: 支持 Python 3.9+
- **代码风格**: 遵循 PEP 8
- **类型注解**: 公共 API 建议添加类型注解
- **文档字符串**: 公共类和方法建议添加 docstring

## 提交规范

提交信息格式：

```
<type>: <subject>

<body>
```

**type 类型**:
- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `style`: 代码格式调整（不影响功能）
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具链相关

示例：

```
feat: 添加对话导出功能

支持导出 JSON 和 Markdown 格式
- JSON 格式包含完整对话元数据
- Markdown 格式便于阅读和分享
```

## 提交流程

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的改动 (`git commit -m 'feat: 添加某些 Amazing 功能'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

## 报告 Bug

提交 Issue 时请包含：
- 操作系统和 Python 版本
- 复现步骤
- 预期行为和实际行为
- 错误日志或截图

## 功能建议

欢迎提交功能建议的 Issue，请说明：
- 功能描述
- 使用场景
- 大概的实现思路（可选）

## 项目结构

```
chen-ai/
├── main.py              # CLI 入口
├── web_ui.py            # Web UI 入口
├── ai_core.py           # AI 对话核心
├── agent_loop.py        # Agent 主循环
├── memory.py            # 记忆系统
├── skills.py            # 技能系统
├── tools.py             # 工具注册表
├── mcp_server.py        # MCP 服务器管理
├── context_manager.py   # 上下文管理
├── prompt_compressor.py # Prompt 压缩
├── cache_optimizer.py   # 缓存优化
├── resilience.py        # 弹性重试
├── hooks.py             # 钩子系统
├── telemetry.py         # 遥测系统
├── config.py            # 配置管理
├── providers.json       # 模型提供商配置
├── requirements.txt     # 依赖列表
├── tests.py             # 测试
└── README.md            # 项目说明
```

## 问答

有任何问题可以通过 Issue 提问。
