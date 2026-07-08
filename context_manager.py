import re
from typing import Any, Dict, List, Optional, Tuple


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Simple token estimation using character counting (works without dependencies)"""
    return _estimate_tokens(text)


def _estimate_tokens(text: str) -> int:
    """
    Token estimation:
    - Chinese: ~1.5 tokens per character
    - English words: ~0.3 tokens per word
    - Other: ~0.25 tokens per character
    """
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    others = len(text) - chinese_chars - len(re.findall(r'[a-zA-Z]', text))
    return int(chinese_chars * 1.5 + english_words * 0.3 + others * 0.25)


def count_messages_tokens(messages: List[Dict[str, str]], model: str = "gpt-4") -> int:
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", ""), model)
        total += 4
    total += 2
    return total


class ContextWindowManager:
    MAX_TOKENS_MAP: Dict[str, int] = {
        "gpt-4": 8192,
        "gpt-4-turbo": 128000,
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-3.5-turbo": 16384,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "deepseek-chat": 65536,
        "deepseek-reasoner": 65536,
        "qwen-turbo": 131072,
        "qwen-plus": 131072,
        "qwen-max": 32768,
    }

    def __init__(
        self,
        model: str = "gpt-4",
        max_input_tokens: int = 0,
        reserve_output_tokens: int = 2048,
    ):
        self.model = model
        self.max_total = max_input_tokens or self.MAX_TOKENS_MAP.get(model, 8192)
        self.reserve_output = reserve_output_tokens
        self.max_input = self.max_total - self.reserve_output

    def get_max_input_tokens(self) -> int:
        return self.max_input

    def is_overflow(self, messages: List[Dict[str, str]]) -> bool:
        return count_messages_tokens(messages, self.model) > self.max_input

    def truncate_messages(
        self,
        messages: List[Dict[str, str]],
        preserve_system: bool = True,
    ) -> List[Dict[str, str]]:
        if not self.is_overflow(messages):
            return messages

        system_msgs: List[Dict[str, str]] = []
        other_msgs: List[Dict[str, str]] = []

        for msg in messages:
            if preserve_system and msg.get("role") == "system":
                system_msgs.append(msg)
            else:
                other_msgs.append(msg)

        system_tokens = count_messages_tokens(system_msgs, self.model)
        available = self.max_input - system_tokens

        truncated: List[Dict[str, str]] = []
        current_tokens = 0

        for msg in reversed(other_msgs):
            msg_tokens = count_tokens(msg.get("content", ""), self.model) + 4
            if current_tokens + msg_tokens > available:
                break
            truncated.insert(0, msg)
            current_tokens += msg_tokens

        return system_msgs + truncated


class ConversationSummarizer:
    def __init__(self, ai_client: Any):
        self.ai = ai_client
        self.summary_cache: Dict[str, str] = {}

    def summarize(
        self,
        messages: List[Dict[str, str]],
        max_summary_tokens: int = 500,
    ) -> str:
        cache_key = str(hash(tuple(
            (m.get("role", ""), m.get("content", "")[:100]) for m in messages
        )))
        if cache_key in self.summary_cache:
            return self.summary_cache[cache_key]

        if len(messages) <= 2:
            return messages[-1].get("content", "")[:max_summary_tokens * 4] if messages else ""

        conversation_text = "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in messages
        )

        if count_tokens(conversation_text) < 500:
            summary = conversation_text
        else:
            try:
                response = self.ai.client.chat.completions.create(
                    model=self.ai.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"请用不超过{max_summary_tokens}个token简要总结以下对话。"
                                "保留关键信息：用户意图、AI回答要点、重要决策。"
                            ),
                        },
                        {"role": "user", "content": conversation_text},
                    ],
                    temperature=0.3,
                    max_tokens=max_summary_tokens,
                )
                summary = response.choices[0].message.content or ""
            except Exception:
                summary = conversation_text[:max_summary_tokens * 4]

        self.summary_cache[cache_key] = summary
        if len(self.summary_cache) > 50:
            first_key = next(iter(self.summary_cache))
            del self.summary_cache[first_key]

        return summary

    def rolling_summary(
        self,
        history: List[Dict[str, str]],
        current_message: str,
        max_context_tokens: int = 4000,
    ) -> str:
        if count_messages_tokens(history, self.ai.model) <= max_context_tokens:
            return current_message

        summary = self.summarize(history, max_summary_tokens=1000)
        return (
            f"[对话历史摘要]\n{summary}\n\n"
            f"[当前消息]\n{current_message}"
        )