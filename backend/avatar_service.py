"""用户头像持久化（小程序临时路径 → 服务器静态文件）"""
import base64
import re
from pathlib import Path
from typing import Optional

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
    return f"/static/uploads/avatars/{user_id}.jpg"


def normalize_stored_avatar(user_id: str, avatar: str, avatar_base64: str = "") -> str:
    """登录时：优先保存 base64；否则保留可公网访问的 URL"""
    if avatar_base64:
        try:
            return save_avatar_base64(user_id, avatar_base64)
        except ValueError:
            pass
    a = (avatar or "").strip()
    if not a or _is_ephemeral_avatar(a):
        return ""
    if a.startswith("/static/uploads/avatars/"):
        return a
    if a.startswith("https://") or a.startswith("http://"):
        if _is_ephemeral_avatar(a):
            return ""
        return a
    return ""


def sanitize_avatar_for_storage(url: str) -> str:
    """写入用户资料前：拒绝无法跨设备展示的临时路径"""
    u = (url or "").strip()
    if not u or _is_ephemeral_avatar(u):
        return ""
    if u.startswith("/static/uploads/avatars/"):
        return u
    if u.startswith("https://") or u.startswith("http://"):
        return u
    return ""


def client_avatar_url(stored: str, request=None) -> str:
    u = (stored or "").strip()
    if not u or _is_ephemeral_avatar(u):
        return ""
    if u.startswith("/static/"):
        root = ""
        if request:
            root = (request.url_root or "").rstrip("/")
        if not root:
            try:
                import config
                root = getattr(config, "PUBLIC_URL", "") or ""
            except ImportError:
                root = ""
        return f"{root}{u}" if root else u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return ""
