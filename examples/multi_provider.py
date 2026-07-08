"""
多模型切换示例

演示如何在不同的模型提供商之间切换。
"""

import os
from dotenv import load_dotenv
from ai_core import AIChat
from config import get_provider_names


def main():
    load_dotenv()

    print("=" * 50)
    print("  多模型切换示例")
    print("=" * 50)

    # 列出所有支持的提供商
    print("\n支持的模型提供商:")
    for i, name in enumerate(get_provider_names(), 1):
        print(f"  {i}. {name}")

    # 初始化
    chat = AIChat(provider="OpenAI")

    print(f"\n当前提供商: {chat.provider_name}")
    print(f"当前模型: {chat.model}")

    # 切换到 DeepSeek（如果配置了 API Key）
    if os.getenv("DEEPSEEK_API_KEY"):
        chat.set_provider("DeepSeek")
        print(f"\n已切换到: {chat.provider_name} ({chat.model})")

    # 切换到通义千问（如果配置了）
    if os.getenv("DASHSCOPE_API_KEY"):
        chat.set_provider("通义千问")
        print(f"已切换到: {chat.provider_name} ({chat.model})")

    # 切换模型
    try:
        chat.set_model("gpt-4")
        print(f"\n模型已切换为: {chat.model}")
    except Exception as e:
        print(f"\n切换模型失败: {e}")

    print("\n提示: 在 .env 中配置不同提供商的 API Key 即可切换使用")


if __name__ == "__main__":
    main()
