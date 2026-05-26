"""总后台首次扫码设置密码（一次性二维码）"""
import json
import os
import re
import secrets
import time
from typing import Dict, Optional

from werkzeug.security import check_password_hash, generate_password_hash

import config
from db import DATA_DIR

SETUP_PATH = os.path.join(DATA_DIR, "super_setup.json")
# 微信 getwxacodeunlimit 的 scene 最长 32 字符，使用 16 位十六进制短码
SCENE_HEX_LEN = 8  # token_hex(8) -> 16 chars
_LEGACY_PREFIX = "sas_"


def _load() -> Dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.isfile(SETUP_PATH):
        return {"initialized": False}
    with open(SETUP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: Dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETUP_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalize_incoming(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith(_LEGACY_PREFIX):
        s = s[len(_LEGACY_PREFIX) :]
    return s


def _pending_scene(data: Dict) -> str:
    return (data.get("pending_scene") or data.get("pending_token") or "").strip()


def _is_short_scene(scene: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{16}", (scene or "").strip(), re.I))


def _scene_valid(scene: str) -> bool:
    if not scene:
        return False
    return _is_short_scene(scene)


def is_super_initialized() -> bool:
    return bool(_load().get("initialized"))


def verify_super_password(password: str) -> bool:
    data = _load()
    if data.get("initialized") and data.get("password_hash"):
        return check_password_hash(data["password_hash"], password)
    return password == config.ADMIN_PASS


def authenticate_super(username: str, password: str) -> bool:
    if (username or "").strip() != config.ADMIN_USER:
        return False
    return verify_super_password(password)


def create_one_time_setup_token() -> Dict:
    data = _load()
    if data.get("initialized"):
        raise ValueError("总后台已完成首次设置，无法再次生成初始化二维码")
    pending = _pending_scene(data)
    if pending and not data.get("token_used"):
        exp = data.get("token_expires_at", 0)
        if exp > time.time() and _scene_valid(pending):
            return {
                "token": pending,
                "scene": pending,
                "expires_in": int(exp - time.time()),
            }
    short = secrets.token_hex(SCENE_HEX_LEN)
    data["pending_scene"] = short
    data["pending_token"] = short
    data["token_used"] = False
    data["token_expires_at"] = time.time() + 86400 * 7
    _save(data)
    return {
        "token": short,
        "scene": short,
        "expires_in": 86400 * 7,
    }


def consume_setup_token(token: str) -> bool:
    data = _load()
    if data.get("initialized"):
        return False
    if data.get("token_used"):
        return False
    key = _normalize_incoming(token)
    if not key:
        return False
    if data.get("token_expires_at", 0) <= time.time():
        return False
    expected = _pending_scene(data)
    return key == expected


def complete_setup(token: str, password: str, confirm: str) -> Dict:
    if not consume_setup_token(token):
        raise ValueError("初始化链接无效或已使用")
    pwd = (password or "").strip()
    if len(pwd) < 6:
        raise ValueError("密码至少6位")
    if pwd != (confirm or "").strip():
        raise ValueError("两次密码不一致")
    data = _load()
    data["initialized"] = True
    data["password_hash"] = generate_password_hash(pwd)
    data["token_used"] = True
    data["pending_token"] = None
    data["pending_scene"] = None
    from admin_password import apply_super_admin_password

    apply_super_admin_password(pwd)
    _save(data)
    return {"message": "总后台密码已设置，请使用新密码登录"}


def get_setup_status() -> Dict:
    data = _load()
    return {
        "initialized": bool(data.get("initialized")),
        "has_pending_qr": bool(
            _pending_scene(data) and not data.get("token_used")
        ),
        "login_username": config.ADMIN_USER,
    }


def provision_super_account(username: str, password: str) -> Dict:
    """
    直接配置总后台账号密码（无需扫码初始化）。
    同步 .env、super_setup.json 密码哈希，并清除待使用的初始化二维码。
    """
    from admin_password import apply_super_admin_account

    username = (username or "").strip()
    pwd = password or ""
    if len(pwd) < 6:
        raise ValueError("密码至少6位")
    apply_super_admin_account(username, pwd)
    data = _load()
    data["initialized"] = True
    data["password_hash"] = generate_password_hash(pwd)
    data["token_used"] = True
    data["pending_token"] = None
    data["pending_scene"] = None
    data["provisioned_at"] = time.time()
    _save(data)
    return {
        "message": "总后台账号已配置",
        "username": username,
        "initialized": True,
    }
