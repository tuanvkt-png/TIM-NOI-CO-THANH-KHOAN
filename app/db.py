import json
import os

SETTINGS_FILE = "settings.json"

DEFAULT = {
    "favorite_symbols": ["BTC-USD"],
    "interval": "1h",
    "scan_cycle": "manual",
    "auto_scan": False,
}


def init_db():
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT)


def get_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        merged = {**DEFAULT, **data}
        return merged
    except Exception:
        return dict(DEFAULT)


def save_settings(payload: dict):
    data = {**DEFAULT, **(payload or {})}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)