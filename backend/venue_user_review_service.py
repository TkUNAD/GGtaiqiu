"""俱乐部维度：选手审核白名单（炸清/接清/零封自动通过）"""
from typing import Dict, Optional

from db import find_by_id, load, mutate

FLAG_BONUS = "auto_review_bonus"
FLAG_SHUTOUT = "auto_review_shutout"


def _flags_key(venue_id: str) -> str:
    return str(venue_id or "").strip()


def get_user_review_flags(user_id: str, venue_id: str) -> Dict[str, bool]:
    if not user_id or not venue_id:
        return {FLAG_BONUS: False, FLAG_SHUTOUT: False}
    u = find_by_id(load("users"), user_id)
    if not u:
        return {FLAG_BONUS: False, FLAG_SHUTOUT: False}
    row = (u.get("venue_review_flags") or {}).get(_flags_key(venue_id)) or {}
    return {
        FLAG_BONUS: bool(row.get(FLAG_BONUS)),
        FLAG_SHUTOUT: bool(row.get(FLAG_SHUTOUT)),
    }


def set_user_review_flags(
    user_id: str,
    venue_id: str,
    *,
    auto_review_bonus: Optional[bool] = None,
    auto_review_shutout: Optional[bool] = None,
) -> Dict[str, bool]:
    if not user_id or not venue_id:
        raise ValueError("缺少玩家或球房")
    key = _flags_key(venue_id)

    def _fn(users):
        u = find_by_id(users, user_id)
        if not u:
            raise ValueError("玩家不存在")
        flags = u.setdefault("venue_review_flags", {})
        cur = dict(flags.get(key) or {})
        if auto_review_bonus is not None:
            cur[FLAG_BONUS] = bool(auto_review_bonus)
        if auto_review_shutout is not None:
            cur[FLAG_SHUTOUT] = bool(auto_review_shutout)
        flags[key] = cur
        return users

    mutate("users", _fn)
    return get_user_review_flags(user_id, venue_id)


def player_auto_approve_bonus(user_id: str, venue_id: str) -> bool:
    return get_user_review_flags(user_id, venue_id).get(FLAG_BONUS, False)


def player_auto_approve_shutout(user_id: str, venue_id: str) -> bool:
    return get_user_review_flags(user_id, venue_id).get(FLAG_SHUTOUT, False)


def match_venue_id_from_match(m: Dict) -> Optional[str]:
    from admin_scope import match_venue_id

    return match_venue_id(m.get("id")) if m.get("id") else None


def is_shutout_match(m: Dict) -> bool:
    """对手局分为 0 结束"""
    w = m.get("winner_id")
    if not w:
        return False
    s1, s2 = int(m.get("score1") or 0), int(m.get("score2") or 0)
    if w == m.get("player1_id"):
        return s2 == 0 and s1 > 0
    if w == m.get("player2_id"):
        return s1 == 0 and s2 > 0
    return False


def shutout_winner_should_auto(m: Dict, venue_id: Optional[str] = None) -> bool:
    if not is_shutout_match(m):
        return False
    vid = venue_id or match_venue_id_from_match(m)
    w = m.get("winner_id")
    if not vid or not w:
        return False
    return player_auto_approve_shutout(w, vid)
