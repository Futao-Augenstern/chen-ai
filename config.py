"""AI 服务商配置管理。

支持:
- 从 JSON 文件加载提供商配置
- 环境变量覆盖配置路径和 API Key
- 错误处理和默认配置回退
- mtime 缓存失效检测
- 类型校验
"""

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 配置文件路径，可通过环境变量覆盖
PROVIDERS_FILE = Path(
    os.getenv("PROVIDERS_CONFIG_PATH", "")
    or (Path(__file__).parent / "providers.json")
)
# 默认提供商名称，可通过环境变量覆盖
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "openai")


# 最小默认配置（文件不存在或损坏时回退）
DEFAULT_CONFIG: Dict[str, Any] = {
    "providers": [
        {
            "name": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-3.5-turbo",
        },
        {
            "name": "deepseek",
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
        },
    ]
}


def _get_api_key_from_env(config: Dict[str, Any]) -> Optional[str]:
    """从环境变量获取 API Key。

    优先级:
    1. 配置中的 api_key 字段（明文，不推荐）
    2. 配置中的 api_key_env 字段 → 从对应环境变量读取
    3. None

    Args:
        config: 提供商配置字典。

    Returns:
        找到的 API Key，否则 None。
    """
    # 明文优先
    if "api_key" in config and config["api_key"]:
        return config["api_key"]

    # 环境变量次之
    if "api_key_env" in config and config["api_key_env"]:
        return os.getenv(config["api_key_env"])

    return None


def _validate_provider_config(config: Dict[str, Any]) -> bool:
    """验证单个提供商配置是否合法。

    必须字段: name

    Args:
        config: 提供商配置字典。

    Returns:
        True 表示合法，False 表示非法。
    """
    if not isinstance(config, dict):
        logger.warning("提供商配置不是字典类型")
        return False
    if "name" not in config:
        logger.warning("提供商配置缺少 'name' 字段")
        return False
    if not config["name"] or not isinstance(config["name"], str):
        logger.warning("提供商 'name' 为空或不是字符串")
        return False

    # 检查是否能获取到 API Key（日志警告但不算非法）
    api_key = _get_api_key_from_env(config)
    if api_key is None:
        logger.debug(f"提供商 '{config['name']}' 未配置 API Key")

    return True


# 缓存使用 lru_cache + mtime 检测：文件修改后自动失效
_last_mtime: float = 0.0
_cached_providers: List[Dict[str, Any]] = []


@lru_cache(maxsize=1)
def _load_providers_cached() -> List[Dict[str, Any]]:
    """带缓存的提供商加载，避免重复读文件。

    如果文件不存在或读取失败，返回默认配置。

    Returns:
        提供商配置列表。
    """
    global _last_mtime, _cached_providers

    # 如果文件不存在，直接返回默认配置
    if not PROVIDERS_FILE.exists():
        logger.warning(
            f"配置文件 {PROVIDERS_FILE} 不存在，使用默认配置。"
            "请复制 providers.json.example 到 providers.json 并填写你的 API Key。"
        )
        return DEFAULT_CONFIG["providers"]

    # 检查文件修改时间，如果缓存未变直接返回
    try:
        current_mtime = PROVIDERS_FILE.stat().st_mtime
        if current_mtime == _last_mtime and _cached_providers:
            return _cached_providers
    except OSError as e:
        logger.warning(f"读取配置文件 stat 失败: {e}")

    # 重新读取
    try:
        with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning(f"配置文件 {PROVIDERS_FILE} 找不到，使用默认配置")
        return DEFAULT_CONFIG["providers"]
    except json.JSONDecodeError as e:
        logger.error(f"配置文件 JSON 格式错误: {e}，使用默认配置")
        return DEFAULT_CONFIG["providers"]
    except OSError as e:
        logger.error(f"读取配置文件 IO 错误: {e}，使用默认配置")
        return DEFAULT_CONFIG["providers"]

    if not isinstance(data, dict) or "providers" not in data:
        logger.error(f"配置文件缺少 'providers' 顶级字段，使用默认配置")
        return DEFAULT_CONFIG["providers"]

    providers_raw = data["providers"]
    if not isinstance(providers_raw, list):
        logger.error(f"'providers' 必须是列表，使用默认配置")
        return DEFAULT_CONFIG["providers"]

    # 过滤掉非法配置
    providers: List[Dict[str, Any]] = []
    for i, p in enumerate(providers_raw):
        if _validate_provider_config(p):
            providers.append(p)
        else:
            logger.warning(f"跳过第 {i+1} 个提供商配置（格式错误）")

    # 更新缓存
    try:
        _last_mtime = PROVIDERS_FILE.stat().st_mtime
    except OSError:
        _last_mtime = 0.0
    _cached_providers = providers

    return providers


def load_providers() -> List[Dict[str, Any]]:
    """加载所有模型提供商配置。

    Returns:
        提供商配置字典列表。每个字典包含:
        - name: 提供商名称（必填）
        - api_key / api_key_env: API Key 或环境变量名称
        - base_url: API 基础 URL
        - default_model: 默认模型名称
    """
    return list(_load_providers_cached())


def get_provider_config(name: str) -> Optional[Dict[str, Any]]:
    """根据名称获取提供商配置。

    Args:
        name: 提供商名称。

    Returns:
        找到返回配置字典，否则 None。
    """
    providers = _load_providers_cached()
    for p in providers:
        if p.get("name") == name:
            return p
    return None


def get_provider_names() -> List[str]:
    """获取所有提供商名称列表。

    Returns:
        名称字符串列表。
    """
    return [p["name"] for p in _load_providers_cached() if "name" in p]


def get_default_provider() -> str:
    """获取默认提供商名称。

    Returns:
        默认提供商名称（来自环境变量 DEFAULT_PROVIDER，默认 "openai"）。
    """
    names = get_provider_names()
    if DEFAULT_PROVIDER in names:
        return DEFAULT_PROVIDER
    if names:
        return names[0]
    return "openai"


def get_provider_api_key(config: Dict[str, Any]) -> Optional[str]:
    """从配置获取 API Key。

    Args:
        config: 提供商配置字典。

    Returns:
        API Key 字符串，如果找不到返回 None。
    """
    return _get_api_key_from_env(config)


def reload_providers() -> None:
    """重新加载提供商配置（清空缓存强制读取文件）。"""
    global _last_mtime
    _last_mtime = 0.0
    _load_providers_cached.cache_clear()
    logger.info("已清空配置缓存，下次调用将重新读取")


def get_config_path() -> Path:
    """获取当前配置文件路径。

    Returns:
        Path 对象。
    """
    return PROVIDERS_FILE


def get_provider_summary() -> Dict[str, Any]:
    """获取提供商配置摘要，用于启动时显示。

    Returns:
        包含 configured_count, total_count, configured_names 等字段的字典。
    """
    providers = _load_providers_cached()
    configured = []
    unconfigured = []
    for p in providers:
        if _get_api_key_from_env(p):
            configured.append(p["name"])
        else:
            unconfigured.append(p["name"])
    return {
        "total": len(providers),
        "configured": len(configured),
        "configured_names": configured,
        "unconfigured_names": unconfigured,
    }
