import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

PROVIDERS_FILE = Path(__file__).parent / "providers.json"


@lru_cache(maxsize=1)
def _load_providers_cached() -> List[Dict[str, Any]]:
    """带缓存的提供商加载，避免重复读文件"""
    with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("providers", [])


def load_providers() -> List[Dict[str, Any]]:
    """加载所有模型提供商配置"""
    return list(_load_providers_cached())


def get_provider_config(name: str) -> Optional[Dict[str, Any]]:
    """根据名称获取提供商配置"""
    providers = _load_providers_cached()
    for p in providers:
        if p["name"] == name:
            return p
    return None


def get_provider_names() -> List[str]:
    """获取所有提供商名称列表"""
    return [p["name"] for p in _load_providers_cached()]


def reload_providers() -> None:
    """重新加载提供商配置（清空缓存）"""
    _load_providers_cached.cache_clear()
