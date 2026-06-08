"""图形验证码（登录/申请）；云托管多实例时写入存储共享。"""
import random
import secrets
import string
import time
from io import BytesIO
from typing import Dict, Optional, Tuple

_captcha_store: Dict[str, Dict] = {}
CAPTCHA_TTL = 300
_CAPTCHA_STORE_NAME = "_captchas"


def _purge_store(store: Dict) -> Dict:
    now = time.time()
    return {
        k: v
        for k, v in store.items()
        if isinstance(v, dict) and v.get("expires_at", 0) > now
    }


def _load_store() -> Dict:
    try:
        from config import USE_MYSQL

        if USE_MYSQL:
            from db import load, save

            data = load(_CAPTCHA_STORE_NAME)
            if not isinstance(data, dict):
                data = {}
            data = _purge_store(data)
            save(_CAPTCHA_STORE_NAME, data)
            return data
    except Exception:
        pass
    global _captcha_store
    _captcha_store = _purge_store(_captcha_store)
    return _captcha_store


def _save_store(store: Dict) -> None:
    try:
        from config import USE_MYSQL

        if USE_MYSQL:
            from db import save

            save(_CAPTCHA_STORE_NAME, _purge_store(store))
            return
    except Exception:
        pass
    global _captcha_store
    _captcha_store = store


def _put_captcha(cid: str, code: str, expires_at: float) -> None:
    store = _load_store()
    store[cid] = {"code": code, "expires_at": expires_at}
    _save_store(store)


def _pop_captcha(cid: str) -> Optional[Dict]:
    store = _load_store()
    rec = store.pop(cid, None)
    _save_store(store)
    return rec


def create_captcha() -> Dict:
    chars = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    cid = secrets.token_urlsafe(12)
    _put_captcha(cid, chars.upper(), time.time() + CAPTCHA_TTL)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return {
            "captcha_id": cid,
            "captcha_code": chars if __debug__ else None,
            "image_base64": "",
            "dev_hint": chars,
        }
    w, h = 280, 96
    img = Image.new("RGB", (w, h), (20, 24, 42))
    draw = ImageDraw.Draw(img)
    for _ in range(3):
        draw.line(
            (
                random.randint(0, w),
                random.randint(0, h),
                random.randint(0, w),
                random.randint(0, h),
            ),
            fill=(180, 140, 40),
            width=1,
        )
    font = None
    for path, size in (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 54),
        ("C:/Windows/Fonts/arialbd.ttf", 56),
        ("C:/Windows/Fonts/Arial.ttf", 54),
    ):
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), chars, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (w - tw) // 2
    ty = (h - th) // 2 - 4
    try:
        draw.text(
            (tx, ty),
            chars,
            fill=(255, 252, 240),
            font=font,
            stroke_width=2,
            stroke_fill=(60, 45, 20),
        )
    except TypeError:
        draw.text((tx, ty), chars, fill=(255, 252, 240), font=font)
    buf = BytesIO()
    img.save(buf, format="PNG")
    import base64

    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    out = {
        "captcha_id": cid,
        "image_base64": f"data:image/png;base64,{b64}",
    }
    return out


def verify_captcha(captcha_id: str, code: str) -> bool:
    rec = _pop_captcha(captcha_id)
    if not rec or rec.get("expires_at", 0) <= time.time():
        return False
    return (code or "").strip().upper() == rec.get("code", "")
