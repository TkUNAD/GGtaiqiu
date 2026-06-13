"""用户头像持久化（小程序临时路径 / 微信 CDN → 服务器静态文件）"""
import base64
import re
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

AVATAR_DIR = Path(__file__).resolve().parent / "static" / "uploads" / "avatars"
MAX_BYTES = 2 * 1024 * 1024


def is_ephemeral_avatar(url: str) -> bool:
    return _is_ephemeral_avatar(url)


def _is_ephemeral_avatar(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return False
    if u.startswith("wxfile://") or u.startswith("wxlocalresource://"):
        return True
    if "/tmp/" in u and (u.startswith("http://") or u.startswith("https://")):
        return True
    return False


def _public_base_url(request=None) -> str:
    try:
        import config

        base = (getattr(config, "PUBLIC_URL", "") or "").strip().rstrip("/")
    except ImportError:
        base = ""
    if base.startswith("http://"):
        base = "https://" + base[7:]
    elif base and not base.startswith("https://"):
        base = "https://" + base
    if base:
        return base
    if request:
        proto = (request.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip()
        host = request.host or ""
        if host:
            return f"{proto}://{host}".rstrip("/")
    return "https://ggtaiqiu.com"


def _public_host() -> str:
    return urlparse(_public_base_url()).netloc.lower()


def _local_avatar_rel(user_id: str) -> str:
    return f"/static/uploads/avatars/{user_id}.jpg"


def _strip_dev_origin(url: str) -> str:
    u = (url or "").strip()
    for prefix in (
        "http://127.0.0.1:5000",
        "https://127.0.0.1:5000",
        "http://localhost:5000",
        "https://localhost:5000",
    ):
        if u.startswith(prefix):
            return u[len(prefix) :]
    return u


def _normalize_stored_path(stored: str) -> str:
    u = _strip_dev_origin((stored or "").strip())
    if not u or _is_ephemeral_avatar(u):
        return ""
    if u.startswith("/static/"):
        return u
    if u.startswith("http://") or u.startswith("https://"):
        parsed = urlparse(u)
        host = (parsed.netloc or "").lower()
        pub_host = _public_host()
        if pub_host and host == pub_host and (parsed.path or "").startswith("/static/"):
            return parsed.path
        return u
    return ""


def _is_external_avatar(url: str) -> bool:
    u = _normalize_stored_path(url)
    if not u or u.startswith("/static/"):
        return False
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    host = urlparse(u).netloc.lower()
    return host != _public_host()


def _persist_user_avatar(user_id: str, rel_path: str) -> None:
    if not user_id or not rel_path:
        return
    from db import find_by_id, load, mutate

    def _fn(users):
        u = find_by_id(users, user_id)
        if u and u.get("avatar") != rel_path:
            u["avatar"] = rel_path
        return users

    mutate("users", _fn)


def mirror_remote_avatar(user_id: str, url: str) -> str:
    if not user_id or not url:
        return ""
    from http_client import get as http_get

    r = http_get(url, timeout=12)
    r.raise_for_status()
    raw = r.content
    if len(raw) < 32:
        raise ValueError("头像数据无效")
    if len(raw) > MAX_BYTES:
        raise ValueError("头像文件过大（最大 2MB）")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    path = AVATAR_DIR / f"{user_id}.jpg"
    path.write_bytes(raw)
    return _local_avatar_rel(user_id)


def save_avatar_base64(user_id: str, b64: str) -> str:
    if not user_id or not b64:
        return ""
    raw = base64.b64decode(re.sub(r"\s+", "", b64))
    if len(raw) > MAX_BYTES:
        raise ValueError("头像文件过大（最大 2MB）")
    if len(raw) < 32:
        raise ValueError("头像数据无效")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    path = AVATAR_DIR / f"{user_id}.jpg"
    path.write_bytes(raw)
    return _local_avatar_rel(user_id)


def cache_avatar_for_user(user_id: str, stored: str, persist: bool = True) -> str:
    """将外链头像缓存到本服 static，避免真机域名白名单与 http 图片限制。"""
    if not user_id:
        return _normalize_stored_path(stored)
    rel = _local_avatar_rel(user_id)
    local_file = AVATAR_DIR / f"{user_id}.jpg"
    normalized = _normalize_stored_path(stored)

    if normalized.startswith("/static/uploads/avatars/"):
        if local_file.is_file():
            return rel
        return normalized

    if local_file.is_file():
        stored_raw = (stored or "").strip()
        if persist and stored_raw != rel:
            _persist_user_avatar(user_id, rel)
        return rel

    source = normalized
    if _is_external_avatar(source) or (
        source.startswith("http://") and _public_host() in source.lower()
    ):
        try:
            mirrored = mirror_remote_avatar(user_id, source)
            if persist:
                _persist_user_avatar(user_id, mirrored)
            return mirrored
        except Exception:
            return normalized

    return normalized


def normalize_stored_avatar(user_id: str, avatar: str, avatar_base64: str = "") -> str:
    """登录时：优先保存 base64；外链头像缓存到本服。"""
    if avatar_base64:
        try:
            path = save_avatar_base64(user_id, avatar_base64)
            if path:
                return path
        except ValueError:
            pass
    cached = cache_avatar_for_user(user_id, avatar, persist=False)
    if cached.startswith("/static/"):
        return cached
    a = (avatar or "").strip()
    if not a or _is_ephemeral_avatar(a):
        return ""
    if a.startswith("/static/uploads/avatars/"):
        return a
    if a.startswith("https://") or a.startswith("http://"):
        if _is_ephemeral_avatar(a):
            return ""
        try:
            return cache_avatar_for_user(user_id, a, persist=True)
        except Exception:
            return ""
    return ""


def persist_login_profile(
    user_id: str,
    nickname: str = "",
    avatar: str = "",
    avatar_base64: str = "",
) -> None:
    """登录时把昵称与头像写入用户表，头像文件保存到 static/uploads/avatars。"""
    from db import find_by_id, mutate, now_iso

    nick = (nickname or "").strip()
    av = (avatar or "").strip()
    b64 = (avatar_base64 or "").strip()
    stored_av = normalize_stored_avatar(user_id, av, avatar_base64=b64)

    def _fn(users):
        u = find_by_id(users, user_id)
        if not u:
            raise ValueError("用户不存在")
        if nick:
            u["nickname"] = nick
        if stored_av:
            u["avatar"] = stored_av
        elif b64:
            pass
        elif _is_ephemeral_avatar(av):
            if _is_ephemeral_avatar(u.get("avatar") or ""):
                u["avatar"] = ""
        elif av:
            clean = sanitize_avatar_for_storage(av)
            if clean:
                u["avatar"] = clean
        u["updated_at"] = now_iso()
        return users

    mutate("users", _fn)


def sanitize_avatar_for_storage(url: str) -> str:
    """写入用户资料前：拒绝无法跨设备展示的临时路径"""
    u = _normalize_stored_path(url)
    if not u:
        return ""
    if u.startswith("/static/uploads/avatars/"):
        return u
    if u.startswith("https://") or u.startswith("http://"):
        return u
    return ""


def client_avatar_url(stored: str, request=None) -> str:
    u = _normalize_stored_path(stored)
    if not u or not u.startswith("/static/"):
        return ""
    base = _public_base_url(request)
    return f"{base}{u}"


def resolve_user_avatar_for_client(user: Optional[Dict], request=None) -> str:
    uid = (user or {}).get("id") or ""
    stored = (user or {}).get("avatar") or ""
    if not uid and not stored:
        return ""
    local = cache_avatar_for_user(uid, stored, persist=True) if uid else _normalize_stored_path(stored)
    rel = local or _normalize_stored_path(stored)
    if rel.startswith("/static/uploads/avatars/") and uid:
        if (AVATAR_DIR / f"{uid}.jpg").is_file():
            return client_avatar_url(rel, request)
        return ""
    if rel.startswith("/static/"):
        return client_avatar_url(rel, request)
    return ""
