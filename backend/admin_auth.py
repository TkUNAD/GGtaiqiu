"""管理后台登录态与权限"""
from functools import wraps
from typing import Callable, Optional

from flask import jsonify, session

from venue_service import (
    PERM_AD_BLOCK,
    PERM_LADDER_SETTINGS,
    PERM_TABLE_MANAGE,
    get_venue,
    is_member_active,
    super_permissions,
    venue_permissions,
)


def _err(msg, code=1):
    return jsonify({"code": code, "msg": msg, "data": None}), 400


def is_super_admin() -> bool:
    return session.get("admin_logged_in") and session.get("admin_role") == "super"


def current_venue_id() -> Optional[str]:
    if is_super_admin():
        return session.get("venue_id")
    return session.get("venue_id")


def get_session_permissions() -> dict:
    if is_super_admin():
        return super_permissions()
    vid = session.get("venue_id")
    if not vid:
        return {}
    venue = get_venue(vid)
    if not venue:
        return {}
    return venue_permissions(venue)


def has_permission(perm: str) -> bool:
    if is_super_admin():
        return True
    return bool(get_session_permissions().get(perm))


def build_admin_session_info() -> dict:
    role = session.get("admin_role", "super")
    if role == "super":
        return {
            "role": "super",
            "username": session.get("admin_username", "admin"),
            "venue_id": None,
            "venue_name": "总后台",
            "is_member_active": True,
            "member_expires_at": None,
            "permissions": super_permissions(),
        }
    vid = session.get("venue_id")
    venue = get_venue(vid) if vid else None
    active = is_member_active(venue) if venue else False
    perms = venue_permissions(venue) if venue else {}
    return {
        "role": "venue",
        "username": session.get("admin_username", ""),
        "venue_id": vid,
        "venue_name": venue.get("name", "") if venue else "",
        "is_member_active": active,
        "member_expires_at": venue.get("member_expires_at") if venue else None,
        "permissions": perms,
    }


def admin_required(f: Callable):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return _err("未登录管理后台", 401), 401
        return f(*args, **kwargs)

    return decorated


def super_admin_required(f: Callable):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return _err("未登录管理后台", 401), 401
        if not is_super_admin():
            return _err("仅总后台可操作", 403), 403
        return f(*args, **kwargs)

    return decorated


def member_permission_required(perm: str):
    def decorator(f: Callable):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("admin_logged_in"):
                return _err("未登录管理后台", 401), 401
            if is_super_admin():
                return f(*args, **kwargs)
            if not has_permission(perm):
                labels = {
                    PERM_TABLE_MANAGE: "桌台管理",
                    PERM_LADDER_SETTINGS: "天梯规则设置",
                    PERM_AD_BLOCK: "手机端广告屏蔽",
                }
                return _err(f"球房未开通会员，无法使用「{labels.get(perm, perm)}」功能", 403), 403
            return f(*args, **kwargs)

        return decorated

    return decorator
