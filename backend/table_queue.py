"""桌台扫码签到：两名选手均到场后才能开赛"""
from datetime import datetime
from typing import Dict, List, Optional  # noqa: F401 - Dict used in view_holder

from config import INITIAL_SCORE, TABLE_WAITING_PRESENCE_SEC
from db import find_by_id, load, mutate, now_iso
from rating import get_tier
from services import reconcile_table_matches, start_match, table_has_active_match

ALLOWED_RACE_TO = (5, 7, 9, 11, 13)


def normalize_race_to(race_to) -> int:
    v = int(race_to)
    return v if v in ALLOWED_RACE_TO else 5


def _waiting_list(table: Dict) -> List[Dict]:
    return table.setdefault("waiting_players", [])


def _waiting_last_seen(w: Dict) -> Optional[datetime]:
    for key in ("last_seen_at", "joined_at"):
        v = w.get(key)
        if not v:
            continue
        try:
            return datetime.fromisoformat(str(v).replace("Z", ""))
        except ValueError:
            continue
    return None


def prune_stale_waiting_players(table: Dict, now: Optional[datetime] = None) -> bool:
    """备战区无心跳超时则移出等候，空出位置。对局进行中不清理。"""
    if table.get("current_match_id"):
        return False
    waiting = table.get("waiting_players") or []
    if not waiting:
        return False
    now = now or datetime.now()
    kept = []
    for w in waiting:
        seen = _waiting_last_seen(w)
        if seen is None:
            kept.append(w)
            continue
        if (now - seen).total_seconds() <= TABLE_WAITING_PRESENCE_SEC:
            kept.append(w)
    if len(kept) == len(waiting):
        return False
    table["waiting_players"] = kept
    return True


def prune_all_stale_waiting_players() -> None:
    """任意桌台签到时顺带清理全场备战超时选手"""

    def _fn(ts):
        for t in ts:
            prune_stale_waiting_players(t)
        return ts

    mutate("tables", _fn)


def touch_waiting_presence(table: Dict, user_id: str) -> None:
    for w in _waiting_list(table):
        if w.get("user_id") == user_id:
            w["last_seen_at"] = now_iso()
            break


def join_table(table_id: str, user_id: str, qr_token: str = "") -> Dict:
    tables = load("tables")
    table = find_by_id(tables, table_id)
    if not table:
        raise ValueError("桌台不存在")
    expected = table.get("qr_token") or ""
    if expected and expected != (qr_token or ""):
        raise ValueError("二维码无效，请重新扫码")

    reconcile_table_matches(table_id)

    view_holder: Dict = {}

    def _join(ts):
        for tbl in ts:
            prune_stale_waiting_players(tbl)
        t = find_by_id(ts, table_id)
        if not t:
            raise ValueError("桌台不存在")
        exp = t.get("qr_token") or ""
        if exp and exp != (qr_token or ""):
            raise ValueError("二维码无效，请重新扫码")

        if t.get("current_match_id"):
            matches = load("matches")
            m = find_by_id(matches, t["current_match_id"])
            if m and m.get("status") == "playing":
                if user_id not in (m.get("player1_id"), m.get("player2_id")):
                    raise ValueError("本桌正在进行其他选手的对局，请换桌或稍后再试")
                view_holder["view"] = build_table_view(t, user_id)
                return ts
            t["current_match_id"] = None

        waiting = _waiting_list(t)
        ids = [w["user_id"] for w in waiting]
        if user_id not in ids:
            if len(waiting) >= 2:
                raise ValueError("本桌已有两名选手等候，请换桌或稍后再试")
            users = load("users")
            u = find_by_id(users, user_id) or {}
            ts_now = now_iso()
            waiting.append({
                "user_id": user_id,
                "nickname": u.get("nickname", "球友"),
                "joined_at": ts_now,
                "last_seen_at": ts_now,
            })
        else:
            touch_waiting_presence(t, user_id)

        view_holder["view"] = build_table_view(t, user_id)
        return ts

    mutate("tables", _join)
    return view_holder["view"]


def leave_table(table_id: str, user_id: str) -> Dict:
    view_holder: Dict = {}

    def _leave(ts):
        table = find_by_id(ts, table_id)
        if not table:
            view_holder["view"] = {}
            return ts
        if table.get("current_match_id"):
            view_holder["view"] = build_table_view(table, user_id)
            return ts
        waiting = _waiting_list(table)
        table["waiting_players"] = [w for w in waiting if w.get("user_id") != user_id]
        view_holder["view"] = build_table_view(table, user_id)
        return ts

    mutate("tables", _leave)
    return view_holder.get("view") or {}


def _synced_race_to(waiting: List[Dict]) -> int:
    """取等候区最近更新的局数（双方同步显示）"""
    race = 5
    latest_at = ""
    for w in waiting:
        rt = normalize_race_to(w.get("race_to", 5))
        at = w.get("race_updated_at", "")
        if at >= latest_at:
            race = rt
            latest_at = at
    return race


def set_waiting_race(table_id: str, user_id: str, race_to: int) -> Dict:
    view_holder: Dict = {}
    race_val = normalize_race_to(race_to)

    def _set(ts):
        table = find_by_id(ts, table_id)
        if not table:
            raise ValueError("桌台不存在")
        if table.get("current_match_id"):
            view_holder["view"] = build_table_view(table, user_id)
            return ts
        waiting = _waiting_list(table)
        found = False
        for w in waiting:
            if w.get("user_id") == user_id:
                w["race_to"] = race_val
                w["race_updated_at"] = now_iso()
                found = True
                break
        if not found:
            raise ValueError("请先在本桌扫码签到")
        touch_waiting_presence(table, user_id)
        view_holder["view"] = build_table_view(table, user_id)
        return ts

    mutate("tables", _set)
    return view_holder["view"]


def clear_waiting(table_id: str):
    def _clear(ts):
        table = find_by_id(ts, table_id)
        if table:
            table["waiting_players"] = []
        return ts

    mutate("tables", _clear)


def start_from_table(
    table_id: str,
    user_id: str,
    race_to: int,
    match_type: str = "auto",
    challenger_id: str = None,
    target_id: str = None,
) -> Dict:
    reconcile_table_matches(table_id)

    view_holder: Dict = {}

    def _prepare(ts):
        table = find_by_id(ts, table_id)
        if not table:
            raise ValueError("桌台不存在")
        waiting = table.get("waiting_players") or []
        if len(waiting) < 2:
            raise ValueError("需两名选手均扫码到场后才能开始（当前 %d/2）" % len(waiting))
        ids = {w["user_id"] for w in waiting}
        if user_id not in ids:
            raise ValueError("请在本桌扫码签到后再开始")
        if not table.get("opened"):
            table["opened"] = True
            table["opened_at"] = now_iso()
            table["opened_by_scan"] = True
        view_holder["table"] = table
        return ts

    mutate("tables", _prepare)
    table = view_holder["table"]

    waiting = table.get("waiting_players") or []
    player1_id = waiting[0]["user_id"]
    player2_id = waiting[1]["user_id"]
    synced_race = _synced_race_to(waiting)

    from services import resolve_match_type

    resolved_type, ranked_reason = resolve_match_type(
        table, player1_id, player2_id, challenger_id, target_id
    )

    return start_match(
        table_id,
        player1_id,
        player2_id,
        synced_race,
        resolved_type,
        challenger_id=challenger_id,
        target_id=target_id,
        ranked_reason_hint=ranked_reason,
    )


def build_table_view(table: Dict, user_id: str = None) -> Dict:
    waiting = table.get("waiting_players") or []
    users = load("users")
    players = []
    for w in waiting:
        u = find_by_id(users, w.get("user_id")) or {}
        tier = get_tier(u.get("score", INITIAL_SCORE))
        players.append({
            "user_id": w.get("user_id"),
            "nickname": w.get("nickname") or u.get("nickname", "球友"),
            "avatar": u.get("avatar") or "",
            "tier_index": tier.get("tier_index", 1),
            "tier_name": tier.get("tier_name", ""),
            "star": tier.get("star", 1),
            "joined_at": w.get("joined_at"),
            "is_me": w.get("user_id") == user_id,
        })

    ready = len(players) >= 2
    opened = bool(table.get("opened"))
    synced_race = _synced_race_to(waiting)
    race_picker = None
    for w in waiting:
        if w.get("race_updated_at"):
            u = find_by_id(users, w.get("user_id")) or {}
            if w.get("race_updated_at", "") >= (race_picker or {}).get("at", ""):
                race_picker = {
                    "nickname": w.get("nickname") or u.get("nickname", "球友"),
                    "race_to": w.get("race_to", synced_race),
                    "at": w.get("race_updated_at", ""),
                }
    return {
        "id": table.get("id"),
        "name": table.get("name"),
        "opened": opened,
        "players_ready": ready,
        "race_to": synced_race,
        "race_picker": race_picker,
        "current_match_id": table.get("current_match_id"),
        "waiting_players": players,
        "waiting_count": len(players),
        "can_start": ready and not table_has_active_match(table),
        "i_am_waiting": any(p["user_id"] == user_id for p in players) if user_id else False,
    }
