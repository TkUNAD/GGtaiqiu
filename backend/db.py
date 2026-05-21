import json
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from config import DATA_DIR

_lock = threading.RLock()

FILES = {
    "users": "users.json",
    "tables": "tables.json",
    "matches": "matches.json",
    "products": "products.json",
    "exchanges": "exchanges.json",
    "score_logs": "score_logs.json",
    "violations": "violations.json",
    "season": "season.json",
    "week_rank": "week_rank.json",
    "settings": "settings.json",
    "venues": "venues.json",
}


def _path(name: str) -> str:
    return os.path.join(DATA_DIR, FILES[name])


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _default_data(name: str) -> Any:
    defaults = {
        "users": [],
        "tables": [
            {"id": "T01", "name": "1号桌", "qr_token": "table_T01", "venue_id": "V001", "opened": False, "current_match_id": None},
            {"id": "T02", "name": "2号桌", "qr_token": "table_T02", "venue_id": "V001", "opened": False, "current_match_id": None},
            {"id": "T03", "name": "3号桌", "qr_token": "table_T03", "venue_id": "V001", "opened": False, "current_match_id": None},
            {"id": "T04", "name": "4号桌", "qr_token": "table_T04", "venue_id": "V001", "opened": False, "current_match_id": None},
        ],
        "matches": [],
        "products": [
            {"id": "P001", "name": "台费1小时", "type": "台费", "points": 200, "stock": 100, "desc": "抵扣台费1小时", "enabled": True},
            {"id": "P002", "name": "可乐", "type": "饮品", "points": 80, "stock": 50, "desc": "冰镇可乐一瓶", "enabled": True},
        ],
        "exchanges": [],
        "score_logs": [],
        "violations": [],
        "season": {"current": _current_season_id(), "started_at": datetime.now().isoformat()},
        "week_rank": {"week_id": _current_week_id(), "scores": {}},
        "settings": {
            "public_violations": [],
            "ladder_rules": {
                "challenge_rank_min": 1,
                "challenge_rank_max": 5,
                "beyond_rank_daily_bonus_only": True,
                "daily_ranked_limit": 2,
                "weekly_ranked_limit": 9,
                "ranked_over_limit_to_casual": True,
                "daily_bonus_valid_match": 5,
                "daily_bonus_break_run": 20,
                "daily_bonus_clearance": 15,
                "daily_bonus_hour_open": 8,
            },
        },
        "venues": [],
    }
    return defaults.get(name, [])


def _current_season_id() -> str:
    now = datetime.now()
    return f"{now.year}{now.month:02d}"


def _current_week_id() -> str:
    now = datetime.now()
    return now.strftime("%Y-W%W")


def load(name: str) -> Any:
    _ensure_data_dir()
    path = _path(name)
    with _lock:
        if not os.path.exists(path):
            data = _default_data(name)
            save(name, data)
            return data
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def save(name: str, data: Any):
    _ensure_data_dir()
    path = _path(name)
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def mutate(name: str, fn: Callable[[Any], Any]) -> Any:
    with _lock:
        data = load(name)
        result = fn(data)
        save(name, result if result is not None else data)
        return result


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now().isoformat()


def find_by_id(items: List[Dict], item_id: str, key: str = "id") -> Optional[Dict]:
    for item in items:
        if item.get(key) == item_id:
            return item
    return None
