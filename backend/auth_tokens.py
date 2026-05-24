"""JWT 访问令牌 + 可撤销刷新令牌"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import jwt

import config
from db import find_by_id, mutate, now_iso


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
    """用 refresh token 换取新 access + 新 refresh（在 mutate 内原子轮换）"""
    if not refresh_raw:
        return None, "缺少 refresh_token"
    h = _hash_refresh(refresh_raw)
    holder: Dict = {}
    err_holder: Dict = {}

    def _rotate(users):
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
            err_holder["err"] = "刷新令牌无效"
            return users
        rt = list(user.get("refresh_tokens") or [])
        if matched_idx < 0 or matched_idx >= len(rt):
            err_holder["err"] = "刷新令牌无效"
            return users
        entry = rt[matched_idx]
        if entry.get("used_at"):
            err_holder["err"] = "刷新令牌已使用，请重新登录"
            return users
        try:
            exp = datetime.fromisoformat(entry.get("expires_at", "").replace("Z", ""))
        except ValueError:
            err_holder["err"] = "刷新令牌已过期"
            return users
        if exp < datetime.now():
            err_holder["err"] = "刷新令牌已过期"
            return users

        u = find_by_id(users, user["id"])
        if not u:
            err_holder["err"] = "用户不存在"
            return users

        rt = list(u.get("refresh_tokens") or [])
        idx = next(
            (i for i, t in enumerate(rt) if t.get("token_hash") == h),
            -1,
        )
        if idx < 0:
            err_holder["err"] = "刷新令牌无效"
            return users
        rt.pop(idx)

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
        new_refresh_raw = secrets.token_urlsafe(32)
        new_hash = _hash_refresh(new_refresh_raw)
        refresh_exp = (
            datetime.now() + timedelta(seconds=config.JWT_REFRESH_EXPIRE_SECONDS)
        ).isoformat()
        rt = [t for t in rt if t.get("expires_at", "") > now_iso()][-20:]
        rt.append({
            "token_hash": new_hash,
            "expires_at": refresh_exp,
            "created_at": now_iso(),
        })
        u["refresh_tokens"] = rt
        u["updated_at"] = now_iso()
        holder["bundle"] = {
            "access_token": access_token,
            "refresh_token": new_refresh_raw,
            "expires_in": config.JWT_ACCESS_EXPIRE_SECONDS,
            "token_type": "Bearer",
        }
        return users

    mutate("users", _rotate)
    if err_holder.get("err"):
        return None, err_holder["err"]
    return holder.get("bundle"), None
