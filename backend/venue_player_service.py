"""俱乐部玩家关联：扫码加入、桌台签到"""
from typing import Dict, List, Optional, Set

from db import find_by_id, load, mutate, new_id, now_iso
from venue_service import DEFAULT_VENUE_ID, get_venue, is_venue_deleted


def venue_player_user_ids(venue_id: str) -> Set[str]:
    vid = (venue_id or DEFAULT_VENUE_ID).strip()
    return {
        r.get("user_id")
        for r in load("venue_players")
        if r.get("venue_id") == vid and r.get("user_id")
    }


def link_user_to_venue(user_id: str, venue_id: str, source: str = "qr") -> Dict:
    uid = (user_id or "").strip()
    vid = (venue_id or "").strip()
    if not uid or not vid:
        raise ValueError("缺少用户或俱乐部")
    venue = get_venue(vid)
    if not venue:
        raise ValueError("俱乐部不存在")
    if is_venue_deleted(venue):
        raise ValueError("俱乐部已停用")
    holder: Dict = {}

    def _fn(rows):
        for r in rows:
            if r.get("user_id") == uid and r.get("venue_id") == vid:
                r["last_seen_at"] = now_iso()
                if source:
                    r["source"] = source
                holder["rec"] = r
                return rows
        rec = {
            "id": new_id("VP"),
            "user_id": uid,
            "venue_id": vid,
            "source": (source or "qr").strip() or "qr",
            "joined_at": now_iso(),
            "last_seen_at": now_iso(),
        }
        rows.append(rec)
        holder["rec"] = rec
        return rows

    mutate("venue_players", _fn)
    return holder["rec"]


def clear_venue_players(venue_id: str) -> int:
    vid = (venue_id or "").strip()
    if not vid:
        return 0
    before = len(load("venue_players"))

    def _fn(rows):
        return [r for r in rows if r.get("venue_id") != vid]

    mutate("venue_players", _fn)
    return before - len(load("venue_players"))


def join_preview_by_token(token: str) -> Dict:
    from venue_service import parse_join_token, venue_id_by_join_token

    raw = parse_join_token(token)
    if not raw:
        raise ValueError("加入码无效")
    vid = venue_id_by_join_token(raw)
    if not vid:
        raise ValueError("加入码无效或俱乐部不存在")
    venue = get_venue(vid) or {}
    return {
        "venue_id": vid,
        "venue_name": venue.get("name", ""),
        "token": raw,
    }


def join_venue_by_token(user_id: str, token: str) -> Dict:
    info = join_preview_by_token(token)
    rec = link_user_to_venue(user_id, info["venue_id"], source="join_qr")
    u = find_by_id(load("users"), user_id) or {}
    return {
        "venue_id": info["venue_id"],
        "venue_name": info["venue_name"],
        "user_id": user_id,
        "nickname": u.get("nickname", ""),
        "joined_at": rec.get("joined_at"),
        "already_member": False,
    }
