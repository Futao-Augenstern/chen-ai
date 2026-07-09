"""
基础对话示例

演示如何使用 AIChat 类进行简单的对话。
运行前请确保已配置好 .env 文件中的 API Key。

用法:
    python examples/basic_chat.py
"""

import os
import sys
from dotenv import load_dotenv
from ai_core import AIChat


def main():
    # 加载环境变量
    load_dotenv()

    # 检查 API Key 是否配置
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠️  未检测到 OPENAI_API_KEY 环境变量。")
        print("   请复制 .env.example 为 .env 并填入你的 API Key。")
        sys.exit(1)

    try:
        # 初始化 AI 对话
        chat = AIChat(
            provider=os.getenv("PROVIDER", "OpenAI"),
            model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            system_prompt=os.getenv("SYSTEM_PROMT", "你是一个有帮助的助手。"),
        )
    except Exception as e:
        print(f"⚠️  初始化 AIChat 失败: {e}")
        print("   请检查 providers.json 配置和 API Key 是否正确。")
        sys.exit(1)

    print("=" * 50)
    print("  chen-ai 基础对话示例")
    print("=" * 50)
    print(f"提供商: {chat.provider_name}")
    print(f"模型: {chat.model}")
    print("输入 'quit' 或 'exit' 退出\n")

    while True:
        try:
            user_input = input("你: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "退出"):
            print("再见！")
            break

        try:
            print("AI: ", end="", flush=True)
            full_response = ""
            for chunk in chat.chat_stream(user_input):
                print(chunk, end="", flush=True)
                full_response += chunk
            print("\n")
        except Exception as e:
            print(f"\n⚠️  对话出错: {e}")


if __name__ == "__main__":
    main()