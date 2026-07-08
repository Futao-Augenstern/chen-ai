import hashlib
import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from context_manager import count_tokens

CACHE_DIR = Path(__file__).parent / "cache_data"


class LRUCache:
    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self._data: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key: str, value: Any) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        else:
            if len(self._data) >= self.max_size:
                self._data.popitem(last=False)
        self._data[key] = value

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


class PromptCache:
    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.cache_file: Path = CACHE_DIR / "prefix_cache.json"
        self.cache: LRUCache = LRUCache(max_size=500)
        self._load_to_memory()
        self.stats: Dict[str, int] = {
            "hits": 0, "misses": 0, "total_tokens": 0, "cached_tokens": 0,
        }

    def _load_to_memory(self) -> None:
        if self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for key, value in data.items():
                    self.cache.put(key, value)

    def _save(self) -> None:
        data = {k: v for k, v in self.cache._data.items()}
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:24]

    def get_cached_prefix(
        self, messages: List[Dict[str, str]]
    ) -> Optional[Dict[str, Any]]:
        prefix = self._build_stable_prefix(messages)
        key = self._hash(prefix)
        cached = self.cache.get(key)
        if cached is not None:
            self.stats["hits"] += 1
            self.stats["cached_tokens"] += count_tokens(prefix)
            return cached
        self.stats["misses"] += 1
        return None

    def set_cached_prefix(
        self, messages: List[Dict[str, str]], result: Any
    ) -> None:
        prefix = self._build_stable_prefix(messages)
        key = self._hash(prefix)
        self.cache.put(key, {
            "result": result,
            "time": datetime.now().isoformat(),
            "prefix_hash": key,
        })
        self.stats["total_tokens"] += count_tokens(prefix)
        self._save()

    def _build_stable_prefix(
        self, messages: List[Dict[str, str]]
    ) -> str:
        stable_parts: List[str] = []
        for msg in messages:
            if msg["role"] == "system":
                stable_parts.append(msg["content"])
            elif msg["role"] == "user" and len(stable_parts) <= 5:
                stable_parts.append(msg["content"][:200])
        return "|||".join(stable_parts)

    def get_hit_rate(self) -> float:
        total = self.stats["hits"] + self.stats["misses"]
        if total == 0:
            return 0.0
        return self.stats["hits"] / total

    def get_stats(self) -> Dict[str, Any]:
        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "hit_rate": f"{self.get_hit_rate():.1%}",
            "total_tokens": self.stats["total_tokens"],
            "cached_tokens": self.stats["cached_tokens"],
            "entries": len(self.cache),
        }


class CacheFirstLoop:
    def __init__(self):
        self.cache = PromptCache()

    def build_system_prompt(
        self,
        base_prompt: str,
        memory_context: Optional[str] = None,
        active_skill: Optional[Any] = None,
    ) -> str:
        prompt_parts: List[str] = [base_prompt]
        if memory_context:
            prompt_parts.append(f"\n\n[用户记忆]\n{memory_context}")
        if active_skill:
            prompt_parts.append(f"\n\n[技能模式: {active_skill.name}]")
            prompt_parts.append(f"技能描述: {active_skill.description}")
        return "".join(prompt_parts)

    def build_xml_prompt(
        self,
        base_prompt: str,
        memory_context: Optional[str],
        user_message: str,
        active_skill: Optional[Any] = None,
    ) -> str:
        prompt = '<?xml version="1.0" encoding="UTF-8"?>\n'
        prompt += "<agent_context>\n"
        prompt += f"  <system>{base_prompt}</system>\n"
        if memory_context:
            prompt += f"  <memory>{memory_context}</memory>\n"
        if active_skill:
            prompt += (
                f"  <skill name=\"{active_skill.name}\">"
                f"{active_skill.description}</skill>\n"
            )
        prompt += "</agent_context>\n"
        prompt += f"<user_message>{user_message}</user_message>"
        return prompt

    def check_cache(
        self, messages: List[Dict[str, str]]
    ) -> Optional[Dict[str, Any]]:
        return self.cache.get_cached_prefix(messages)

    def update_cache(
        self, messages: List[Dict[str, str]], result: Any
    ) -> None:
        self.cache.set_cached_prefix(messages, result)

    def get_cache_stats(self) -> Dict[str, Any]:
        return self.cache.get_stats()


class CostTracker:
    PRICING: Dict[str, Dict[str, float]] = {
        "deepseek-chat": {"input": 0.14, "output": 0.28, "cache_hit": 0.014},
        "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_hit": 0.14},
        "gpt-4o": {"input": 2.50, "output": 10.00, "cache_hit": 1.25},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00, "cache_hit": 5.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50, "cache_hit": 0.25},
        "qwen-turbo": {"input": 0.30, "output": 0.60, "cache_hit": 0.10},
        "glm-4-flash": {"input": 0.01, "output": 0.01, "cache_hit": 0.01},
        "moonshot-v1-8k": {"input": 1.00, "output": 1.00, "cache_hit": 0.50},
        "default": {"input": 0.50, "output": 1.50, "cache_hit": 0.25},
    }

    def __init__(self):
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cache_hit_tokens: int = 0
        self.total_cost: float = 0.0
        self.request_count: int = 0
        self._saved_cost: float = 0.0

    def _get_price(self, model: str) -> Dict[str, float]:
        for key, price in self.PRICING.items():
            if key in model:
                return price
        return self.PRICING["default"]

    def record_request(
        self,
        model: str,
        input_text: str,
        output_text: str,
        cache_hit_tokens: int = 0,
    ) -> None:
        price = self._get_price(model)
        input_tokens = count_tokens(input_text)
        output_tokens = count_tokens(output_text)

        cost = (
            (input_tokens / 1_000_000) * price["input"]
            + (output_tokens / 1_000_000) * price["output"]
            + (cache_hit_tokens / 1_000_000) * price["cache_hit"]
        )

        if cache_hit_tokens > 0:
            self._saved_cost += (input_tokens / 1_000_000) * price["input"]

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cache_hit_tokens += cache_hit_tokens
        self.total_cost += cost
        self.request_count += 1

    def get_stats(self) -> Dict[str, Any]:
        return {
            "requests": self.request_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cache_hit_tokens": self.total_cache_hit_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost": f"${self.total_cost:.4f}",
            "saved_cost": f"${self._saved_cost:.4f}",
            "avg_cost_per_request": (
                f"${self.total_cost / self.request_count:.6f}"
                if self.request_count > 0
                else "$0"
            ),
        }

    def reset(self) -> None:
        self.__init__()