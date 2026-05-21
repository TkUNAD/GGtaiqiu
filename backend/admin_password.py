"""管理后台密码修改与找回（总后台写 .env，球房写 venues.json）"""
import os
import re
from typing import Optional, Tuple

import config
from venue_service import (
    authenticate_venue,
    find_venue_by_username,
    get_venue,
    verify_venue_security_code,
)

ROOT_DIR = config.ROOT_DIR
ENV_PATH = os.path.join(ROOT_DIR, ".env")


def _validate_new_password(password: str, confirm: str) -> None:
    if not password or len(password) < 6:
        raise ValueError("新密码至少 6 位")
    if password != confirm:
        raise ValueError("两次输入的新密码不一致")


def _update_env_key(key: str, value: str) -> None:
    """更新项目根 .env 中的键值"""
    lines = []
    if os.path.isfile(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=", re.I)
    found = False
    new_lines = []
    for line in lines:
        if pattern.match(line):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    os.environ[key] = value


def apply_super_admin_password(new_password: str) -> None:
    _update_env_key("ADMIN_PASS", new_password)
    config.ADMIN_PASS = new_password


def verify_super_recovery_secret(secret: str) -> bool:
    """找回总后台密码：需输入 .env 中的 JWT_SECRET"""
    expected = (config.JWT_SECRET or "").strip()
    return bool(expected) and secret.strip() == expected


def change_password_with_old(
    username: str, old_password: str, new_password: str, confirm_password: str
) -> dict:
    _validate_new_password(new_password, confirm_password)
    username = (username or "").strip()
    if not username or not old_password:
        raise ValueError("请填写账号和当前密码")

    if username == config.ADMIN_USER:
        if old_password != config.ADMIN_PASS:
            raise ValueError("当前密码错误")
        apply_super_admin_password(new_password)
        return {"role": "super", "username": username, "message": "总后台密码已更新"}

    venue = authenticate_venue(username, old_password)
    if not venue:
        raise ValueError("账号或当前密码错误")

    from venue_service import update_venue

    update_venue(venue["id"], {"password": new_password})
    return {
        "role": "venue",
        "username": username,
        "venue_name": venue.get("name", ""),
        "message": "球房登录密码已更新",
    }


def reset_password_forgot(
    username: str,
    recovery_secret: str,
    new_password: str,
    confirm_password: str,
) -> dict:
    """忘记密码：总后台凭 JWT_SECRET 重置；球房请联系总后台"""
    _validate_new_password(new_password, confirm_password)
    username = (username or "").strip()
    if not username:
        raise ValueError("请填写账号")

    if username == config.ADMIN_USER:
        if not verify_super_recovery_secret(recovery_secret):
            raise ValueError("恢复密钥错误（请填写 .env 文件中的 JWT_SECRET）")
        apply_super_admin_password(new_password)
        return {"role": "super", "message": "总后台密码已重置，请使用新密码登录"}

    venue = find_venue_by_username(username)
    if venue:
        if not venue.get("security_code_hash"):
            raise ValueError("该球房未设置安全码，请联系总后台在「球房会员」中设置")
        if not verify_venue_security_code(username, recovery_secret):
            raise ValueError("安全码错误")
        from venue_service import update_venue

        update_venue(venue["id"], {"password": new_password})
        return {
            "role": "venue",
            "message": "球房密码已重置，请使用新密码登录",
        }

    raise ValueError("账号不存在")


def change_password_logged_in(
    role: str,
    username: str,
    venue_id: Optional[str],
    old_password: str,
    new_password: str,
    confirm_password: str,
) -> dict:
    _validate_new_password(new_password, confirm_password)
    if role == "super":
        if username != config.ADMIN_USER or old_password != config.ADMIN_PASS:
            raise ValueError("当前密码错误")
        apply_super_admin_password(new_password)
        return {"message": "总后台密码已更新，下次登录请使用新密码"}
    if role == "venue" and venue_id:
        venue = get_venue(venue_id)
        if not venue or venue.get("username") != username:
            raise ValueError("会话异常，请重新登录")
        if not authenticate_venue(username, old_password):
            raise ValueError("当前密码错误")
        from venue_service import update_venue

        update_venue(venue_id, {"password": new_password})
        return {"message": "球房登录密码已更新"}
    raise ValueError("无法修改密码")
