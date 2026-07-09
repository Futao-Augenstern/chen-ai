import hashlib
import json
import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from context_manager import count_tokens

logger = logging.getLogger(__name__)

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
        self.cache_file = CACHE_DIR / "prefix_cache.json"
        self.cache = LRUCache(max_size=500)
        self.stats = {"hits": 0, "misses": 0, "total_tokens": 0, "cached_tokens": 0}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    for k, v in json.load(f).items():
                        self.cache.put(k, v)
            except Exception as e:
                logger.error(f"加载缓存失败 {self.cache_file}: {e}，使用空缓存")

    def _save(self) -> None:
        if not self._dirty:
            return
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(dict(self.cache._data), f, ensure_ascii=False, indent=2)
            self._dirty = False
        except Exception as e:
            logger.error(f"保存缓存失败 {self.cache_file}: {e}")

    def flush(self) -> None:
        self._dirty = True
        self._save()

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:24]

    def _prefix(self, messages: List[Dict[str, str]]) -> str:
        parts = []
        for msg in messages:
            if msg["role"] == "system":
                parts.append(msg["content"])
            elif msg["role"] == "user" and len(parts) <= 5:
                parts.append(msg["content"][:200])
        return "|||".join(parts)

    def get(self, messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        try:
            key = self._hash(self._prefix(messages))
            cached = self.cache.get(key)
            if cached:
                self.stats["hits"] += 1
                self.stats["cached_tokens"] += count_tokens(self._prefix(messages))
                return cached
            self.stats["misses"] += 1
            return None
        except Exception as e:
            logger.error(f"获取缓存失败: {e}")
            return None

    def set(self, messages: List[Dict[str, str]], result: Any) -> None:
        try:
            prefix = self._prefix(messages)
            key = self._hash(prefix)
            self.cache.put(key, {"result": result, "time": datetime.now().isoformat(), "prefix_hash": key})
            self.stats["total_tokens"] += count_tokens(prefix)
            self._dirty = True
        except Exception as e:
            logger.error(f"写入缓存失败: {e}")

    def hit_rate(self) -> float:
        total = self.stats["hits"] + self.stats["misses"]
        return self.stats["hits"] / total if total else 0.0

    def get_stats(self) -> Dict[str, Any]:
        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "hit_rate": f"{self.hit_rate():.1%}",
            "total_tokens": self.stats["total_tokens"],
            "cached_tokens": self.stats["cached_tokens"],
            "entries": len(self.cache),
        }


class CacheFirstLoop:
    def __init__(self):
        self.cache = PromptCache()

    def check_cache(self, messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        return self.cache.get(messages)

    def update_cache(self, messages: List[Dict[str, str]], result: Any) -> None:
        self.cache.set(messages, result)

    def get_cache_stats(self) -> Dict[str, Any]:
        return self.cache.get_stats()

    def flush_cache(self) -> None:
        self.cache.flush()


class CostTracker:
    PRICING = {
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
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_hit_tokens = 0
        self.total_cost = 0.0
        self.request_count = 0
        self._saved_cost = 0.0
        self._load()  # 从磁盘恢复历史数据

    def _load(self) -> None:
        try:
            stats_file = CACHE_DIR / "cost_stats.json"
            if stats_file.exists():
                with open(stats_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.total_input_tokens = data.get("total_input_tokens", 0)
                    self.total_output_tokens = data.get("total_output_tokens", 0)
                    self.total_cache_hit_tokens = data.get("total_cache_hit_tokens", 0)
                    self.total_cost = data.get("total_cost", 0.0)
                    self.request_count = data.get("request_count", 0)
                    self._saved_cost = data.get("_saved_cost", 0.0)
        except Exception as e:
            logger.error(f"加载成本统计失败: {e}，使用默认值")

    def _save(self) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            stats_file = CACHE_DIR / "cost_stats.json"
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump({
                    "total_input_tokens": self.total_input_tokens,
                    "total_output_tokens": self.total_output_tokens,
                    "total_cache_hit_tokens": self.total_cache_hit_tokens,
                    "total_cost": self.total_cost,
                    "request_count": self.request_count,
                    "_saved_cost": self._saved_cost,
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存成本统计失败: {e}")

    def _price(self, model: str) -> Dict[str, float]:
        for key, price in self.PRICING.items():
            if key in model:
                return price
        return self.PRICING["default"]

    def record_request(self, model: str, input_text: str, output_text: str,
                       cache_hit_tokens: int = 0) -> None:
        p = self._price(model)
        in_tok = count_tokens(input_text)
        out_tok = count_tokens(output_text)

        cost = (in_tok / 1e6) * p["input"] + (out_tok / 1e6) * p["output"] \
               + (cache_hit_tokens / 1e6) * p["cache_hit"]

        if cache_hit_tokens > 0:
            self._saved_cost += (in_tok / 1e6) * p["input"]

        self.total_input_tokens += in_tok
        self.total_output_tokens += out_tok
        self.total_cache_hit_tokens += cache_hit_tokens
        self.total_cost += cost
        self.request_count += 1

    def get_stats(self) -> Dict[str, Any]:
        avg = f"${self.total_cost / self.request_count:.6f}" if self.request_count else "$0"
        return {
            "requests": self.request_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cache_hit_tokens": self.total_cache_hit_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost": f"${self.total_cost:.4f}",
            "saved_cost": f"${self._saved_cost:.4f}",
            "avg_cost_per_request": avg,
        }

    def reset(self) -> None:
        self.__init__()