"""图形验证码（内存，用于登录/申请）"""
import random
import secrets
import string
import time
from io import BytesIO
from typing import Dict, Optional, Tuple

_captcha_store: Dict[str, Dict] = {}
CAPTCHA_TTL = 300


def _purge():
    now = time.time()
    expired = [k for k, v in _captcha_store.items() if v.get("expires_at", 0) <= now]
    for k in expired:
        _captcha_store.pop(k, None)


def create_captcha() -> Dict:
    _purge()
    chars = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    cid = secrets.token_urlsafe(12)
    _captcha_store[cid] = {
        "code": chars.upper(),
        "expires_at": time.time() + CAPTCHA_TTL,
    }
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return {
            "captcha_id": cid,
            "captcha_code": chars if __debug__ else None,
            "image_base64": "",
            "dev_hint": chars,
        }
    w, h = 220, 80
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
        ("C:/Windows/Fonts/arialbd.ttf", 44),
        ("C:/Windows/Fonts/Arial.ttf", 42),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40),
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
    draw.text(
        ((w - tw) // 2, (h - th) // 2 - 3),
        chars,
        fill=(255, 252, 240),
        font=font,
    )
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
    _purge()
    rec = _captcha_store.pop(captcha_id, None)
    if not rec or rec.get("expires_at", 0) <= time.time():
        return False
    return (code or "").strip().upper() == rec.get("code", "")
