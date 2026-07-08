import json
from pathlib import Path
from typing import Any, Dict, List, Optional

PROVIDERS_FILE = Path(__file__).parent / "providers.json"


def load_providers() -> List[Dict[str, Any]]:
    with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("providers", [])


def get_provider_config(name: str) -> Optional[Dict[str, Any]]:
    providers = load_providers()
    for p in providers:
        if p["name"] == name:
            return p
    return None


def get_provider_names() -> List[str]:
    return [p["name"] for p in load_providers()]