"""用户对外展示字段（API 脱敏）"""
from typing import Dict, List, Optional


def mask_phone(phone: str) -> str:
    p = (phone or "").strip()
    if len(p) >= 11:
        return p[:3] + "****" + p[-4:]
    if len(p) >= 7:
        return p[:2] + "****" + p[-2:]
    return p or ""


def sanitize_user_public(user: Dict, include_phone: bool = True) -> Dict:
    if not user:
        return {}
    out = {
        "id": user.get("id"),
        "nickname": user.get("nickname", "球友"),
        "avatar": user.get("avatar", ""),
        "score": user.get("score", 1000),
        "wins": user.get("wins", 0),
        "losses": user.get("losses", 0),
        "status": user.get("status", "active"),
    }
    if include_phone:
        ph = user.get("phone") or ""
        out["phone"] = mask_phone(ph) if ph else ""
        out["phone_bound"] = bool(ph)
    return out


def sanitize_user_list(users: List[Dict], limit: int = 50) -> List[Dict]:
    return [sanitize_user_public(u, include_phone=False) for u in users[:limit]]
