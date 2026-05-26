"""短信验证码（开发环境返回验证码；生产需对接短信网关）"""
import random
import re
import time
from typing import Dict, Optional

import config

_phone_codes: Dict[str, Dict] = {}

PHONE_RE = re.compile(r"^1\d{10}$")


def normalize_phone(phone: str) -> str:
    return re.sub(r"\s+", "", (phone or "").strip())


def validate_phone(phone: str) -> str:
    p = normalize_phone(phone)
    if not PHONE_RE.match(p):
        raise ValueError("请输入正确的11位手机号")
    return p


def _purge():
    now = time.time()
    expired = [k for k, v in _phone_codes.items() if v.get("expires_at", 0) <= now]
    for k in expired:
        _phone_codes.pop(k, None)


def send_code(phone: str, purpose: str, length: int = 4) -> Dict:
    """
    purpose: venue_apply(3位) | venue_reset(4位)（管理后台登录不使用短信验证码）
    """
    _purge()
    p = validate_phone(phone)
    key = f"{purpose}:{p}"
    last = _phone_codes.get(key)
    if last and time.time() - last.get("sent_at", 0) < 60:
        raise ValueError("发送过于频繁，请60秒后再试")
    code = "".join(str(random.randint(0, 9)) for _ in range(length))
    _phone_codes[key] = {
        "code": code,
        "purpose": purpose,
        "expires_at": time.time() + 600,
        "sent_at": time.time(),
    }
    out = {"phone": p, "expires_in": 600}
    if config.DEV_MODE:
        out["dev_code"] = code
    return out


def verify_code(phone: str, purpose: str, code: str, consume: bool = True) -> bool:
    _purge()
    p = validate_phone(phone)
    key = f"{purpose}:{p}"
    rec = _phone_codes.get(key)
    if not rec or rec.get("expires_at", 0) <= time.time():
        return False
    ok = (code or "").strip() == rec.get("code", "")
    if ok and consume:
        _phone_codes.pop(key, None)
    return ok
