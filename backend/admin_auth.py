"""管理后台登录态与权限"""
import secrets
import time
from functools import wraps
from typing import Callable, Optional

from flask import jsonify, request, session

from venue_service import (
    PERM_AD_BLOCK,
    PERM_LADDER_SETTINGS,
    PERM_TABLE_MANAGE,
    get_venue,
    is_member_active,
    super_permissions,
    venue_permissions,
)

# 登录失败限流：ip -> {count, lock_until}
_login_attempts = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 180  # 连续错误 5 次后暂停 3 分钟


def _err(msg, code=1, http_status=400):
    return jsonify({"code": code, "msg": msg, "data": None}), http_status


def issue_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return token


def verify_csrf() -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    expected = session.get("csrf_token", "")
    if not expected:
        return False
    got = request.headers.get("X-CSRF-Token", "")
    return got == expected


def _login_rec(ip: str) -> dict:
    return _login_attempts.get(ip, {"count": 0, "lock_until": 0})


def _format_lock_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 60:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds} 秒"


def check_login_rate_limit(ip: str) -> Optional[str]:
    """已锁定时返回提示文案"""
    now = time.time()
    rec = _login_rec(ip)
    lock_until = rec.get("lock_until", 0)
    if lock_until > now:
        remain = int(lock_until - now)
        return (
            f"已连续错误 {MAX_LOGIN_ATTEMPTS} 次，登录已暂停 3 分钟，"
            f"请 {_format_lock_remaining(remain)} 后再试"
        )
    if lock_until and lock_until <= now:
        rec["lock_until"] = 0
        _login_attempts[ip] = rec
    return None


def record_login_failure(ip: str, base_msg: str = "账号或密码错误") -> str:
    """记录一次失败，返回含错误次数与剩余次数的提示"""
    now = time.time()
    rec = _login_rec(ip)
    if rec.get("lock_until", 0) > now:
        return check_login_rate_limit(ip) or base_msg

    failed = rec.get("count", 0) + 1
    rec["count"] = failed

    if failed >= MAX_LOGIN_ATTEMPTS:
        rec["lock_until"] = now + LOGIN_LOCK_SECONDS
        rec["count"] = 0
        _login_attempts[ip] = rec
        return (
            f"{base_msg}。已连续错误 {MAX_LOGIN_ATTEMPTS} 次，"
            f"登录已暂停 3 分钟，请稍后再试"
        )

    remaining = MAX_LOGIN_ATTEMPTS - failed
    _login_attempts[ip] = rec
    return f"{base_msg}。已连续错误 {failed} 次，还可尝试 {remaining} 次"


def clear_login_attempts(ip: str) -> None:
    _login_attempts.pop(ip, None)


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
    csrf = issue_csrf_token()
    if role == "super":
        return {
            "role": "super",
            "username": session.get("admin_username", "admin"),
            "venue_id": None,
            "venue_name": "总后台",
            "is_member_active": True,
            "member_expires_at": None,
            "permissions": super_permissions(),
            "csrf_token": csrf,
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
        "csrf_token": csrf,
    }


def admin_required(f: Callable):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return _err("未登录管理后台", 401, 401)
        if not verify_csrf():
            return _err("CSRF 校验失败，请刷新页面", 403, 403)
        return f(*args, **kwargs)

    return decorated


def super_admin_required(f: Callable):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return _err("未登录管理后台", 401, 401)
        if not verify_csrf():
            return _err("CSRF 校验失败，请刷新页面", 403, 403)
        if not is_super_admin():
            return _err("仅总后台可操作", 403, 403)
        return f(*args, **kwargs)

    return decorated


def member_permission_required(perm: str):
    def decorator(f: Callable):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("admin_logged_in"):
                return _err("未登录管理后台", 401, 401)
            if not verify_csrf():
                return _err("CSRF 校验失败，请刷新页面", 403, 403)
            if is_super_admin():
                return f(*args, **kwargs)
            if not has_permission(perm):
                labels = {
                    PERM_TABLE_MANAGE: "桌台管理",
                    PERM_LADDER_SETTINGS: "天梯规则设置",
                    PERM_AD_BLOCK: "手机端广告屏蔽",
                }
                return _err(f"球房未开通会员，无法使用「{labels.get(perm, perm)}」功能", 403, 403)
            return f(*args, **kwargs)

        return decorated

    return decorator


def require_active_venue_member(f: Callable):
    """球房过期会员禁止敏感写操作（总后台不受限）"""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return _err("未登录管理后台", 401, 401)
        if not verify_csrf():
            return _err("CSRF 校验失败，请刷新页面", 403, 403)
        if is_super_admin():
            return f(*args, **kwargs)
        vid = session.get("venue_id")
        venue = get_venue(vid) if vid else None
        if not venue or not is_member_active(venue):
            return _err("球房会员已过期，无法进行此操作", 403, 403)
        return f(*args, **kwargs)

    return decorated
