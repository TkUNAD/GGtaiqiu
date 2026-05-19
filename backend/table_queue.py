"""桌台扫码签到：两名选手均到场后才能开赛"""
from typing import Dict, List, Optional  # noqa: F401 - Dict used in view_holder

from db import find_by_id, load, mutate, now_iso, save
from services import start_match


def _waiting_list(table: Dict) -> List[Dict]:
    return table.setdefault("waiting_players", [])


def join_table(table_id: str, user_id: str, qr_token: str = "") -> Dict:
    tables = load("tables")
    table = find_by_id(tables, table_id)
    if not table:
        raise ValueError("桌台不存在")
    expected = table.get("qr_token") or ""
    if expected and expected != (qr_token or ""):
        raise ValueError("二维码无效，请重新扫码")

    view_holder: Dict = {}

    def _join(ts):
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

        waiting = _waiting_list(t)
        ids = [w["user_id"] for w in waiting]
        if user_id not in ids:
            if len(waiting) >= 2:
                raise ValueError("本桌已有两名选手等候，请换桌或稍后再试")
            users = load("users")
            u = find_by_id(users, user_id) or {}
            waiting.append({
                "user_id": user_id,
                "nickname": u.get("nickname", "球友"),
                "joined_at": now_iso(),
            })

        if len(_waiting_list(t)) >= 2 and not t.get("opened"):
            t["opened"] = True
            t["opened_at"] = now_iso()
            t["opened_by_scan"] = True

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
        rt = w.get("race_to")
        if rt not in (5, 7):
            continue
        at = w.get("race_updated_at", "")
        if at >= latest_at:
            race = rt
            latest_at = at
    return race


def set_waiting_race(table_id: str, user_id: str, race_to: int) -> Dict:
    view_holder: Dict = {}
    race_val = 7 if int(race_to) == 7 else 5

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
    view_holder: Dict = {}

    def _peek(ts):
        table = find_by_id(ts, table_id)
        if not table:
            raise ValueError("桌台不存在")
        view_holder["table"] = table
        return ts

    mutate("tables", _peek)
    table = view_holder["table"]

    waiting = table.get("waiting_players") or []
    if len(waiting) < 2:
        raise ValueError("需两名选手均扫码到场后才能开始（当前 %d/2）" % len(waiting))

    ids = {w["user_id"] for w in waiting}
    if user_id not in ids:
        raise ValueError("请在本桌扫码签到后再开始")

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
        players.append({
            "user_id": w.get("user_id"),
            "nickname": w.get("nickname") or u.get("nickname", "球友"),
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
        "can_start": ready and not table.get("current_match_id"),
        "i_am_waiting": any(p["user_id"] == user_id for p in players) if user_id else False,
    }
