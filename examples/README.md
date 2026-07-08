# 示例代码

这里收录了 chen-ai 的使用示例，帮助你快速上手。

## 示例列表

| 示例 | 说明 |
|------|------|
| [basic_chat.py](basic_chat.py) | 基础对话，使用 AIChat 类进行流式对话 |
| [multi_provider.py](multi_provider.py) | 多模型切换，在不同提供商之间切换 |
| [skills_demo.py](skills_demo.py) | 技能系统使用，列出技能、获取建议 |

## 运行示例

```bash
# 先安装依赖并配置环境变量
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 API Key

# 运行示例
python examples/basic_chat.py
python examples/multi_provider.py
python examples/skills_demo.py
```
