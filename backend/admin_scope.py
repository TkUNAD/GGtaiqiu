"""球房后台数据范围：按桌台/对局/等候区关联用户"""
from typing import Dict, List, Optional, Set

from db import find_by_id, load
from venue_service import DEFAULT_VENUE_ID


def venue_table_ids(venue_id: str) -> Set[str]:
    return {
        t["id"]
        for t in load("tables")
        if t.get("venue_id", DEFAULT_VENUE_ID) == venue_id
    }


def users_linked_to_venue(venue_id: str) -> Set[str]:
    """与该球房桌台有过对局或正在等候的用户"""
    tids = venue_table_ids(venue_id)
    user_ids: Set[str] = set()
    for m in load("matches"):
        if m.get("table_id") in tids:
            if m.get("player1_id"):
                user_ids.add(m["player1_id"])
            if m.get("player2_id"):
                user_ids.add(m["player2_id"])
    for t in load("tables"):
        if t.get("id") in tids:
            for w in t.get("waiting_players") or []:
                uid = w.get("user_id")
                if uid:
                    user_ids.add(uid)
    return user_ids


def match_venue_id(match_id: str) -> Optional[str]:
    m = find_by_id(load("matches"), match_id)
    if not m or not m.get("table_id"):
        return None
    t = find_by_id(load("tables"), m["table_id"])
    if not t:
        return None
    return t.get("venue_id", DEFAULT_VENUE_ID)


def assert_user_in_venue(user_id: str, venue_id: Optional[str], is_super: bool) -> None:
    if is_super or not venue_id:
        return
    if user_id not in users_linked_to_venue(venue_id):
        raise ValueError("无权操作其他球房的玩家")


def assert_match_in_venue(match_id: str, venue_id: Optional[str], is_super: bool) -> None:
    if is_super or not venue_id:
        return
    vid = match_venue_id(match_id)
    if vid != venue_id:
        raise ValueError("无权操作其他球房的对局")


def assert_exchange_in_venue(ex_id: str, venue_id: Optional[str], is_super: bool) -> None:
    if is_super or not venue_id:
        return
    ex = find_by_id(load("exchanges"), ex_id)
    if not ex:
        raise ValueError("兑换记录不存在")
    if ex.get("user_id") not in users_linked_to_venue(venue_id):
        raise ValueError("无权操作其他球房的兑换记录")


def filter_users_for_venue(users, venue_id: Optional[str], is_super: bool):
    if is_super or not venue_id:
        return users
    allowed = users_linked_to_venue(venue_id)
    return [u for u in users if u.get("id") in allowed]


def filter_matches_for_venue(matches, venue_id: Optional[str], is_super: bool):
    if is_super or not venue_id:
        return matches
    tids = venue_table_ids(venue_id)
    return [m for m in matches if m.get("table_id") in tids]


def filter_exchanges_for_venue(exchanges, venue_id: Optional[str], is_super: bool):
    if is_super or not venue_id:
        return exchanges
    allowed = users_linked_to_venue(venue_id)
    return [e for e in exchanges if e.get("user_id") in allowed]


def filter_score_logs_for_venue(logs, venue_id: Optional[str], is_super: bool):
    if is_super or not venue_id:
        return logs
    allowed = users_linked_to_venue(venue_id)
    return [l for l in logs if l.get("user_id") in allowed]


def scoped_dashboard_stats(venue_id: Optional[str], is_super: bool) -> Dict:
    users = load("users")
    matches = load("matches")
    exchanges = load("exchanges")
    if not is_super and venue_id:
        users = filter_users_for_venue(users, venue_id, is_super)
        matches = filter_matches_for_venue(matches, venue_id, is_super)
        exchanges = filter_exchanges_for_venue(exchanges, venue_id, is_super)
    pending = [m for m in matches if m.get("status") == "pending_review"]
    bonus_review = [m for m in matches if m.get("needs_bonus_review")]
    ex_pending = [e for e in exchanges if e.get("status") == "pending"]
    return {
        "users_count": len(users),
        "matches_count": len(matches),
        "pending_matches": len(pending),
        "pending_bonus_reviews": len(bonus_review),
        "pending_exchanges": len(ex_pending),
    }
