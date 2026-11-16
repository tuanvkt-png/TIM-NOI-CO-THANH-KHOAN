import json
import os

SETTINGS_FILE = "settings.json"

DEFAULT = {
    "favorite_symbols": ["GC=F", "BTC-USD", "EURUSD=X", "CL=F"],
    "interval": "1h",
    "scan_cycle": "manual",
    "auto_scan": False,
    "watchlist": ["GC=F", "BTC-USD", "ETH-USD", "EURUSD=X", "GBPUSD=X",
                  "USDJPY=X", "CL=F", "^DJI", "^GSPC"],
}


def init_db():
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT)


def get_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULT, **data}
    except Exception:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT.items()}


def save_settings(payload: dict):
    current = get_settings()
    data = {**current, **(payload or {})}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
