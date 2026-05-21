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
    if is_super:
        return super_dashboard_stats()
    users = load("users")
    matches = load("matches")
    exchanges = load("exchanges")
    if venue_id:
        users = filter_users_for_venue(users, venue_id, is_super)
        matches = filter_matches_for_venue(matches, venue_id, is_super)
        exchanges = filter_exchanges_for_venue(exchanges, venue_id, is_super)
    pending = [m for m in matches if m.get("status") == "pending_review"]
    bonus_review = [m for m in matches if m.get("needs_bonus_review")]
    ex_pending = [e for e in exchanges if e.get("status") == "pending"]
    return {
        "scope": "venue",
        "users_count": len(users),
        "matches_count": len(matches),
        "pending_matches": len(pending),
        "pending_bonus_reviews": len(bonus_review),
        "pending_exchanges": len(ex_pending),
    }


def super_dashboard_stats() -> Dict:
    """总后台仪表盘：统计项与各球房会员数据一致并汇总"""
    from venue_service import (
        DEFAULT_VENUE_ID,
        ensure_table_venue_ids,
        ensure_venues_file,
        is_member_active,
    )

    ensure_venues_file()
    ensure_table_venue_ids()
    venues = load("venues")
    users = load("users")
    tables = load("tables")
    matches = load("matches")
    exchanges = load("exchanges")

    all_table_ids: Set[str] = set()
    all_member_ids: Set[str] = set()
    venue_rows = []
    active_venues = 0
    total_tables = 0

    for v in venues:
        vid = v["id"]
        tids = venue_table_ids(vid)
        all_table_ids |= tids
        member_ids = users_linked_to_venue(vid)
        all_member_ids |= member_ids
        tc = len([t for t in tables if t.get("venue_id", DEFAULT_VENUE_ID) == vid])
        total_tables += tc
        member_score = sum(
            int(find_by_id(users, uid).get("score", 0))
            for uid in member_ids
            if find_by_id(users, uid)
        )
        active = is_member_active(v)
        if active:
            active_venues += 1
        exp = (v.get("member_expires_at") or "")[:10] or "-"
        venue_rows.append({
            "venue_id": vid,
            "venue_name": v.get("name", ""),
            "manager_name": v.get("manager_name", ""),
            "username": v.get("username", ""),
            "table_count": tc,
            "member_count": len(member_ids),
            "member_total_score": member_score,
            "member_expires_at": exp,
            "is_member_active": active,
        })

    venue_matches = [m for m in matches if m.get("table_id") in all_table_ids]
    venue_exchanges = [
        e for e in exchanges if e.get("user_id") in all_member_ids
    ]
    total_member_score = sum(
        int(find_by_id(users, uid).get("score", 0))
        for uid in all_member_ids
        if find_by_id(users, uid)
    )

    return {
        "scope": "super",
        "venues_count": len(venues),
        "active_venues_count": active_venues,
        "expired_venues_count": len(venues) - active_venues,
        "total_tables": total_tables,
        "total_member_count": len(all_member_ids),
        "total_member_score": total_member_score,
        "total_matches": len(venue_matches),
        "pending_bonus_reviews": len(
            [m for m in venue_matches if m.get("needs_bonus_review")]
        ),
        "pending_exchanges": len(
            [e for e in venue_exchanges if e.get("status") == "pending"]
        ),
        "venues": venue_rows,
        # 兼容旧字段
        "total_score": total_member_score,
        "products_count": len(venues),
    }
