import re
from typing import Any, Dict, List, Optional, Set

from context_manager import count_tokens


class PromptCompressor:
    def __init__(self):
        self.compression_stats: Dict[str, int] = {
            "original_tokens": 0,
            "compressed_tokens": 0,
            "savings": 0,
        }

    def compress(self, text: str, level: str = "medium") -> str:
        original_tokens = count_tokens(text)

        if level == "light":
            compressed = self._light_compress(text)
        elif level == "aggressive":
            compressed = self._aggressive_compress(text)
        else:
            compressed = self._medium_compress(text)

        compressed_tokens = count_tokens(compressed)

        self.compression_stats["original_tokens"] += original_tokens
        self.compression_stats["compressed_tokens"] += compressed_tokens
        self.compression_stats["savings"] = (
            self.compression_stats["original_tokens"]
            - self.compression_stats["compressed_tokens"]
        )

        return compressed

    def _light_compress(self, text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        return text

    def _medium_compress(self, text: str) -> str:
        text = self._light_compress(text)
        patterns: List[tuple] = [
            (r"可以(.*?)吗", r"可以\1?"),
            (r"请(你|您)(帮助|帮忙|帮我)(.*?)(一下)?", r"请\3"),
            (r"能不能(.*?)(一下)?", r"能否\1"),
            (r"我想(要|知道|了解)(.*?)", r"\2"),
            (r"请问(.*?)", r"\1?"),
            (r"麻烦(.*?)(一下)?", r"\1"),
            (r"帮我(.*?)", r"\1"),
        ]
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text)
        text = re.sub(r"[ \t]+", " ", text).strip()
        return text

    def _aggressive_compress(self, text: str) -> str:
        text = self._medium_compress(text)
        text = re.sub(r"[，。！？；：、""''《》（）【】]", "", text)
        text = re.sub(r"的", "", text)
        text = re.sub(r"了", "", text)
        text = re.sub(r"是", "", text)
        text = re.sub(r"在", "", text)
        text = re.sub(r"[ \t]+", " ", text).strip()
        return text

    def deduplicate(self, text: str) -> str:
        lines = text.split("\n")
        seen: Set[str] = set()
        result: List[str] = []
        for line in lines:
            normalized = line.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(line)
            elif not normalized:
                result.append(line)
        return "\n".join(result)

    def get_savings_rate(self) -> float:
        if self.compression_stats["original_tokens"] == 0:
            return 0.0
        return (
            self.compression_stats["savings"]
            / self.compression_stats["original_tokens"]
        )

    def get_stats(self) -> Dict[str, Any]:
        return {
            "original_tokens": self.compression_stats["original_tokens"],
            "compressed_tokens": self.compression_stats["compressed_tokens"],
            "savings": self.compression_stats["savings"],
            "savings_rate": f"{self.get_savings_rate():.1%}",
        }


class PromptOptimizer:
    def __init__(self):
        self.compressor = PromptCompressor()
        self.optimizations: List[Dict[str, int]] = []
        self._seen_messages: Set[str] = set()

    def optimize(self, text: str, context: Optional[str] = None) -> str:
        optimized = self.compressor.deduplicate(text)

        if count_tokens(text) > 500:
            optimized = self.compressor.compress(optimized, "medium")

        if context:
            relevant = self._extract_relevant_context(text, context)
            if relevant:
                optimized = f"{relevant}\n\n{optimized}"

        if optimized in self._seen_messages:
            pass
        else:
            self._seen_messages.add(optimized)
            if len(self._seen_messages) > 1000:
                self._seen_messages.clear()

        self.optimizations.append(
            {
                "original_length": len(text),
                "optimized_length": len(optimized),
                "saved": len(text) - len(optimized),
            }
        )

        return optimized

    def _extract_relevant_context(
        self, text: str, context: str, max_length: int = 300
    ) -> Optional[str]:
        keywords = set(text.lower().split())
        keywords.discard("")
        if not keywords:
            return None

        lines = context.split("\n")
        scored: List[tuple] = []
        for line in lines:
            score = sum(1 for kw in keywords if kw in line.lower())
            if score > 0:
                scored.append((score, line))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        result = "\n".join(line for _, line in scored[:5])
        if len(result) > max_length:
            result = result[:max_length] + "..."
        return result

    def get_stats(self) -> Dict[str, Any]:
        return self.compressor.get_stats()