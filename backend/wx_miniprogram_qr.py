"""微信小程序码（getwxacodeunlimit），扫码可直接打开指定页面"""
import json
import time
from io import BytesIO
from typing import Dict, Optional, Tuple

import requests

import config

_token_cache: Dict = {"token": "", "expires_at": 0}

# 微信 scene 最长 32 字符
MAX_SCENE_LEN = 32


def normalize_scene(scene: str) -> str:
    s = (scene or "").strip()
    if len(s) > MAX_SCENE_LEN:
        raise ValueError(
            f"scene 超过微信 {MAX_SCENE_LEN} 字符限制（当前 {len(s)}），"
            "请缩短令牌或重新生成二维码"
        )
    return s


def get_wx_access_token() -> str:
    if not config.WECHAT_APPID or not config.WECHAT_SECRET:
        raise ValueError("未配置微信小程序 AppID/Secret，无法生成小程序码")
    now = time.time()
    if _token_cache.get("token") and _token_cache.get("expires_at", 0) > now + 60:
        return _token_cache["token"]
    url = "https://api.weixin.qq.com/cgi-bin/token"
    r = requests.get(
        url,
        params={
            "grant_type": "client_credential",
            "appid": config.WECHAT_APPID,
            "secret": config.WECHAT_SECRET,
        },
        timeout=15,
    )
    data = r.json()
    if not data.get("access_token"):
        raise ValueError(data.get("errmsg") or "获取微信 access_token 失败")
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 7200))
    return _token_cache["token"]


def create_wxacode_png(page: str, scene: str, width: int = 430) -> bytes:
    """
    生成小程序码 PNG 二进制。
    page: 如 pages/super-setup/super-setup（不要前导 /）
    scene: 最长 32 字符，会传给页面 onLoad(options.scene)
    """
    scene = normalize_scene(scene)
    if not page:
        raise ValueError("缺少小程序页面路径")
    token = get_wx_access_token()
    api = f"https://api.weixin.qq.com/wxa/getwxacodeunlimit?access_token={token}"
    env_version = "develop" if config.DEV_MODE else "release"
    body = {
        "page": page,
        "scene": scene,
        "width": width,
        "check_path": False,
        "env_version": env_version,
    }
    r = requests.post(api, json=body, timeout=30)
    ctype = r.headers.get("Content-Type", "")
    if "json" in ctype or r.content[:1] == b"{":
        try:
            err = r.json()
        except Exception:
            err = {"errmsg": r.text[:200]}
        raise ValueError(err.get("errmsg") or f"生成小程序码失败({err.get('errcode')})")
    return r.content


def create_wxacode_fallback_plain(scene: str) -> bytes:
    """无微信 Secret 时退回普通二维码（仅含说明，需小程序内扫码）"""
    import qrcode

    hint = (
        "请用微信扫此码后点击右上角在小程序中打开；"
        "或打开小程序-管理后台登录-扫一扫。"
        f" Scene:{scene}"
    )
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(hint[:120])
    qr.make(fit=True)
    img = qr.make_image(fill_color="#4C1D95", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_miniprogram_qr(
    page: str,
    scene: str,
) -> Tuple[bytes, bool]:
    """
    返回 (png_bytes, is_wxacode)。
    is_wxacode=False 表示仅为普通二维码，不能从微信扫一扫直达小程序。
    """
    try:
        return create_wxacode_png(page, scene), True
    except ValueError:
        raise
    except Exception as e:
        if config.DEV_MODE and not config.WECHAT_SECRET:
            return create_wxacode_fallback_plain(scene), False
        raise ValueError(str(e)) from e
