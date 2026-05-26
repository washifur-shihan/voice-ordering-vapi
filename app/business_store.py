import json
import os
from typing import Optional, Dict, Any

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "business_configs.json")


def _ensure_store_exists():
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)


def load_all_business_configs() -> Dict[str, Any]:
    _ensure_store_exists()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_all_business_configs(configs: Dict[str, Any]) -> None:
    _ensure_store_exists()

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)


def save_business_config(business_id: str, config: Dict[str, Any]) -> None:
    configs = load_all_business_configs()
    configs[business_id] = config
    save_all_business_configs(configs)


def get_business_config(business_id: str) -> Optional[Dict[str, Any]]:
    configs = load_all_business_configs()
    return configs.get(business_id)