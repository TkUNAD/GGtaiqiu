"""小程序管理端 JWT（与玩家 token 分离 typ=admin_access）"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import jwt

import config
from db import find_by_id, mutate, now_iso


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_admin_tokens(admin_rec: Dict) -> Dict:
    now = datetime.utcnow()
    access_exp = now + timedelta(seconds=config.JWT_ACCESS_EXPIRE_SECONDS)
    payload = {
        "sub": admin_rec["id"],
        "typ": "admin_access",
        "role": admin_rec.get("role"),
        "venue_id": admin_rec.get("venue_id"),
        "iat": now,
        "exp": access_exp,
    }
    access_token = jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")
    if isinstance(access_token, bytes):
        access_token = access_token.decode("utf-8")

    refresh_raw = secrets.token_urlsafe(32)
    refresh_hash = _hash_refresh(refresh_raw)
    refresh_exp = (
        datetime.now() + timedelta(seconds=config.JWT_REFRESH_EXPIRE_SECONDS)
    ).isoformat()
    entry = {
        "token_hash": refresh_hash,
        "expires_at": refresh_exp,
        "created_at": now_iso(),
    }

    def _fn(records):
        a = find_by_id(records, admin_rec["id"])
        if not a:
            return records
        tokens = a.get("refresh_tokens") or []
        tokens = [t for t in tokens if t.get("expires_at", "") > now_iso()][-20:]
        tokens.append(entry)
        a["refresh_tokens"] = tokens
        return records

    mutate("venue_admins", _fn)
    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "expires_in": config.JWT_ACCESS_EXPIRE_SECONDS,
        "token_type": "Bearer",
    }


def verify_admin_access_token(token: str) -> Optional[Dict]:
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
        if payload.get("typ") != "admin_access":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def refresh_admin_access_token(refresh_raw: str) -> Tuple[Optional[Dict], Optional[str]]:
    if not refresh_raw:
        return None, "缺少 refresh_token"
    h = _hash_refresh(refresh_raw)
    holder: Dict = {}
    err_holder: Dict = {}

    def _rotate(records):
        admin = None
        matched_idx = -1
        for a in records:
            for i, t in enumerate(a.get("refresh_tokens") or []):
                if t.get("token_hash") == h:
                    admin = a
                    matched_idx = i
                    break
            if admin:
                break
        if not admin:
            err_holder["err"] = "刷新令牌无效"
            return records
        rt = list(admin.get("refresh_tokens") or [])
        if matched_idx < 0 or matched_idx >= len(rt):
            err_holder["err"] = "刷新令牌无效"
            return records
        entry = rt[matched_idx]
        try:
            exp = datetime.fromisoformat(entry.get("expires_at", "").replace("Z", ""))
        except ValueError:
            err_holder["err"] = "刷新令牌已过期"
            return records
        if exp < datetime.now():
            err_holder["err"] = "刷新令牌已过期"
            return records

        a = find_by_id(records, admin["id"])
        if not a:
            err_holder["err"] = "管理员不存在"
            return records
        rt = list(a.get("refresh_tokens") or [])
        idx = next((i for i, t in enumerate(rt) if t.get("token_hash") == h), -1)
        if idx < 0:
            err_holder["err"] = "刷新令牌无效"
            return records
        rt.pop(idx)

        now = datetime.utcnow()
        access_exp = now + timedelta(seconds=config.JWT_ACCESS_EXPIRE_SECONDS)
        payload = {
            "sub": admin["id"],
            "typ": "admin_access",
            "role": admin.get("role"),
            "venue_id": admin.get("venue_id"),
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
        a["refresh_tokens"] = rt
        holder["bundle"] = {
            "access_token": access_token,
            "refresh_token": new_refresh_raw,
            "expires_in": config.JWT_ACCESS_EXPIRE_SECONDS,
            "token_type": "Bearer",
        }
        return records

    mutate("venue_admins", _rotate)
    if err_holder.get("err"):
        return None, err_holder["err"]
    return holder.get("bundle"), None
