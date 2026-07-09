import logging
import re
from typing import Any, Dict, List, Optional, Set

from context_manager import count_tokens

logger = logging.getLogger(__name__)


class PromptCompressor:
    def __init__(self):
        self.stats = {"original_tokens": 0, "compressed_tokens": 0, "savings": 0}

    def compress(self, text: str, level: str = "medium") -> str:
        original = text
        try:
            orig = count_tokens(text)
            if level == "light":
                text = self._light(text)
            elif level == "aggressive":
                text = self._aggressive(text)
            else:
                text = self._medium(text)

            comp = count_tokens(text)
            self.stats["original_tokens"] += orig
            self.stats["compressed_tokens"] += comp
            self.stats["savings"] = self.stats["original_tokens"] - self.stats["compressed_tokens"]
            return text
        except Exception as e:
            logger.error(f"压缩失败: {e}，返回原始文本")
            return original

    def _light(self, text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _medium(self, text: str) -> str:
        text = self._light(text)
        patterns = [
            (r"可以(.*?)吗", r"可以\1?"),
            (r"请(你|您)(帮助|帮忙|帮我)(.*?)(一下)?", r"请\3"),
            (r"能不能(.*?)(一下)?", r"能否\1"),
            (r"我想(要|知道|了解)(.*?)", r"\2"),
            (r"请问(.*?)", r"\1?"),
            (r"麻烦(.*?)(一下)?", r"\1"),
            (r"帮我(.*?)", r"\1"),
        ]
        for pat, rep in patterns:
            text = re.sub(pat, rep, text)
        return re.sub(r"[ \t]+", " ", text).strip()

    def _aggressive(self, text: str) -> str:
        text = self._medium(text)
        text = re.sub(r"[，。！？；：、""''《》（）【】]", "", text)
        for w in "的了是在":
            text = text.replace(w, "")
        return re.sub(r"[ \t]+", " ", text).strip()

    def deduplicate(self, text: str) -> str:
        seen: Set[str] = set()
        result: List[str] = []
        for line in text.split("\n"):
            norm = line.strip().lower()
            if norm and norm not in seen:
                seen.add(norm)
                result.append(line)
            elif not norm:
                result.append(line)
        return "\n".join(result)

    def savings_rate(self) -> float:
        if self.stats["original_tokens"] == 0:
            return 0.0
        return self.stats["savings"] / self.stats["original_tokens"]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "original_tokens": self.stats["original_tokens"],
            "compressed_tokens": self.stats["compressed_tokens"],
            "savings": self.stats["savings"],
            "savings_rate": f"{self.savings_rate():.1%}",
        }


class PromptOptimizer:
    def __init__(self):
        self.compressor = PromptCompressor()
        self._seen: Set[str] = set()

    def optimize(self, text: str, context: Optional[str] = None) -> str:
        original = text
        try:
            optimized = self.compressor.deduplicate(text)
            if count_tokens(text) > 500:
                optimized = self.compressor.compress(optimized, "medium")
            if context:
                relevant = self._relevant_context(text, context)
                if relevant:
                    optimized = f"{relevant}\n\n{optimized}"
            if optimized not in self._seen:
                self._seen.add(optimized)
                if len(self._seen) > 1000:
                    self._seen.clear()
            return optimized
        except Exception as e:
            logger.error(f"优化失败: {e}，返回原始消息")
            return original

    def _relevant_context(self, text: str, context: str, max_len: int = 300) -> Optional[str]:
        keywords = set(text.lower().split())
        keywords.discard("")
        if not keywords:
            return None

        scored = []
        for line in context.split("\n"):
            score = sum(1 for kw in keywords if kw in line.lower())
            if score > 0:
                scored.append((score, line))
        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        result = "\n".join(line for _, line in scored[:5])
        return result[:max_len] + "..." if len(result) > max_len else result

    def get_stats(self) -> Dict[str, Any]:
        return self.compressor.get_stats()
