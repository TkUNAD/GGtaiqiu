import json
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from config import DATA_DIR, USE_MYSQL

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
    "venue_admins": "venue_admins.json",
    "venue_applications": "venue_applications.json",
    "review_logs": "review_logs.json",
    "super_setup": "super_setup.json",
    "mp_super_entry_allowlist": "mp_super_entry_allowlist.json",
    "mp_admin_entry_allowlist": "mp_admin_entry_allowlist.json",
}


def _path(name: str) -> str:
    return os.path.join(DATA_DIR, FILES.get(name, f"{name}.json"))


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _current_season_id() -> str:
    now = datetime.now()
    return f"{now.year}{now.month:02d}"


def _current_week_id() -> str:
    now = datetime.now()
    return now.strftime("%Y-W%W")


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
        "venue_admins": [],
        "venue_applications": [],
        "review_logs": [],
        "super_setup": {"initialized": False},
        "mp_super_entry_allowlist": {
            "comment": "总后台授权：列表内微信可在小程序「我的」看到总后台入口并用账号密码登录",
            "entries": [],
        },
        "mp_admin_entry_allowlist": {"openids": []},
    }
    return defaults.get(name, [])


def _json_load_unlocked(name: str) -> Any:
    _ensure_data_dir()
    path = _path(name)
    if not os.path.exists(path):
        data = _default_data(name)
        _json_save_unlocked(name, data)
        return data
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_save_unlocked(name: str, data: Any):
    _ensure_data_dir()
    path = _path(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _mysql_load_unlocked(conn, name: str) -> Any:
    from mysql_store import load_collection, save_collection

    data = load_collection(conn, name)
    if data is None:
        data = _default_data(name)
        save_collection(conn, name, data)
    return data


def _mysql_save_unlocked(conn, name: str, data: Any):
    from mysql_store import save_collection

    save_collection(conn, name, data)


def _read_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def import_json_files_to_mysql() -> Dict[str, int]:
    """将 backend/data 下所有 .json 导入 MySQL（已有集合跳过）。"""
    from mysql_store import connect, collection_count, import_collection, list_collections

    _ensure_data_dir()
    conn = connect()
    try:
        ensure_schema(conn)
        existing = set(list_collections(conn))
        imported = 0
        skipped = 0
        for fname in sorted(os.listdir(DATA_DIR)):
            if not fname.endswith(".json"):
                continue
            name = fname[:-5]
            if name in existing:
                skipped += 1
                continue
            path = os.path.join(DATA_DIR, fname)
            try:
                data = _read_json_file(path)
            except Exception:
                continue
            import_collection(conn, name, data)
            imported += 1
        conn.commit()
        return {"imported": imported, "skipped": skipped, "total": collection_count(conn)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(conn=None):
    from mysql_store import ensure_schema as _ensure

    _ensure(conn)


def init_storage() -> Dict[str, Any]:
    """启动时初始化存储；MySQL 自动补全缺失的 JSON 集合（已有跳过）。"""
    info = storage_info()
    if not USE_MYSQL:
        _ensure_data_dir()
        return info
    result = import_json_files_to_mysql()
    info["sync_from_json"] = result
    info["collections"] = result.get("total", 0)
    return info


def storage_info() -> Dict[str, Any]:
    info = {
        "backend": "mysql" if USE_MYSQL else "json",
        "database": None,
        "collections": None,
    }
    if USE_MYSQL:
        import config

        info["database"] = config.MYSQL_DATABASE
    return info


def ping_mysql() -> Dict[str, Any]:
    if not USE_MYSQL:
        return {"configured": False, "ok": False}
    try:
        from mysql_store import collection_count, connect, ping

        ping()
        conn = connect()
        try:
            count = collection_count(conn)
            conn.commit()
        finally:
            conn.close()
        return {"configured": True, "ok": True, "collections": count}
    except Exception as e:
        return {"configured": True, "ok": False, "error": str(e)}


def load(name: str) -> Any:
    with _lock:
        if USE_MYSQL:
            from mysql_store import connect

            conn = connect()
            try:
                data = _mysql_load_unlocked(conn, name)
                conn.commit()
                return data
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        return _json_load_unlocked(name)


def save(name: str, data: Any):
    with _lock:
        if USE_MYSQL:
            from mysql_store import connect

            conn = connect()
            try:
                _mysql_save_unlocked(conn, name, data)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        _json_save_unlocked(name, data)


def mutate(name: str, fn: Callable[[Any], Any]) -> Any:
    with _lock:
        if USE_MYSQL:
            from mysql_store import connect

            conn = connect()
            try:
                data = _mysql_load_unlocked(conn, name)
                result = fn(data)
                _mysql_save_unlocked(conn, name, result if result is not None else data)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        data = _json_load_unlocked(name)
        result = fn(data)
        _json_save_unlocked(name, result if result is not None else data)
        return result


def mutate_multi(names: List[str], fn: Callable[..., Any]) -> Any:
    with _lock:
        if USE_MYSQL:
            from mysql_store import connect

            conn = connect()
            try:
                bundles = {n: _mysql_load_unlocked(conn, n) for n in names}
                result = fn(**bundles)
                for n in names:
                    if n in bundles:
                        _mysql_save_unlocked(conn, n, bundles[n])
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        bundles = {n: _json_load_unlocked(n) for n in names}
        result = fn(**bundles)
        for n in names:
            if n in bundles:
                _json_save_unlocked(n, bundles[n])
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
