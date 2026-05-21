"""JWT 访问令牌 + 可撤销刷新令牌"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import jwt

import config
from db import find_by_id, load, mutate, now_iso


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_tokens(user: Dict) -> Dict:
    """签发 access JWT 与 refresh token，refresh 哈希存入用户记录"""
    now = datetime.utcnow()
    access_exp = now + timedelta(seconds=config.JWT_ACCESS_EXPIRE_SECONDS)
    payload = {
        "sub": user["id"],
        "typ": "access",
        "iat": now,
        "exp": access_exp,
    }
    access_token = jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")
    if isinstance(access_token, bytes):
        access_token = access_token.decode("utf-8")

    refresh_raw = secrets.token_urlsafe(32)
    refresh_hash = _hash_refresh(refresh_raw)
    refresh_exp = (datetime.now() + timedelta(seconds=config.JWT_REFRESH_EXPIRE_SECONDS)).isoformat()
    entry = {
        "token_hash": refresh_hash,
        "expires_at": refresh_exp,
        "created_at": now_iso(),
    }

    def _fn(users):
        u = find_by_id(users, user["id"])
        if not u:
            return users
        tokens = u.get("refresh_tokens") or []
        tokens = [t for t in tokens if t.get("expires_at", "") > now_iso()][-20:]
        tokens.append(entry)
        u["refresh_tokens"] = tokens
        u["updated_at"] = now_iso()
        return users

    mutate("users", _fn)
    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "expires_in": config.JWT_ACCESS_EXPIRE_SECONDS,
        "token_type": "Bearer",
    }


def verify_access_token(token: str) -> Optional[str]:
    """校验 access JWT，返回 user_id"""
    if not token:
        return None
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "typ"]},
        )
        if payload.get("typ") != "access":
            return None
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def refresh_access_token(refresh_raw: str) -> Tuple[Optional[Dict], Optional[str]]:
    """用 refresh token 换取新 access + 新 refresh。返回 (token_bundle, error_msg)"""
    if not refresh_raw:
        return None, "缺少 refresh_token"
    h = _hash_refresh(refresh_raw)
    users = load("users")
    user = None
    matched_idx = -1
    for u in users:
        for i, t in enumerate(u.get("refresh_tokens") or []):
            if t.get("token_hash") == h:
                user = u
                matched_idx = i
                break
        if user:
            break
    if not user:
        return None, "刷新令牌无效"
    tokens = user.get("refresh_tokens") or []
    if matched_idx < 0 or matched_idx >= len(tokens):
        return None, "刷新令牌无效"
    entry = tokens[matched_idx]
    try:
        exp = datetime.fromisoformat(entry.get("expires_at", "").replace("Z", ""))
    except ValueError:
        return None, "刷新令牌已过期"
    if exp < datetime.now():
        return None, "刷新令牌已过期"

    def _revoke_old(us):
        u = find_by_id(us, user["id"])
        if not u:
            return us
        rt = list(u.get("refresh_tokens") or [])
        if 0 <= matched_idx < len(rt):
            rt.pop(matched_idx)
        u["refresh_tokens"] = rt
        return us

    mutate("users", _revoke_old)
    bundle = issue_tokens(user)
    return bundle, None


def revoke_all_refresh_tokens(user_id: str) -> None:
    def _fn(users):
        u = find_by_id(users, user_id)
        if u:
            u["refresh_tokens"] = []
            u["updated_at"] = now_iso()
        return users

    mutate("users", _fn)
