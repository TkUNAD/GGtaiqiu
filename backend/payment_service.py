"""微信支付 / 支付宝支付（会员续费）"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import string
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional
from urllib.parse import quote_plus, urlencode

import requests

import config
from membership_service import complete_membership_order, get_membership_order

WECHAT_UNIFIED_URL = "https://api.mch.weixin.qq.com/pay/unifiedorder"
ALIPAY_GATEWAY = "https://openapi.alipay.com/gateway.do"


def _rand_str(n: int = 32) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def _xml_dict(xml_text: str) -> Dict[str, str]:
    root = ET.fromstring(xml_text)
    return {child.tag: child.text or "" for child in root}


def _dict_xml(data: Dict[str, Any]) -> str:
    parts = ["<xml>"]
    for k, v in sorted(data.items()):
        if v is None:
            continue
        parts.append(f"<{k}><![CDATA[{v}]]></{k}>")
    parts.append("</xml>")
    return "".join(parts)


def _wechat_sign(data: Dict[str, Any], api_key: str) -> str:
    items = []
    for k in sorted(data.keys()):
        if k == "sign" or data[k] is None or data[k] == "":
            continue
        items.append(f"{k}={data[k]}")
    items.append(f"key={api_key}")
    return hashlib.md5("&".join(items).encode("utf-8")).hexdigest().upper()


def payment_configured(channel: str) -> bool:
    if getattr(config, "PAYMENT_DEV_MODE", False):
        return True
    ch = (channel or "").lower()
    if ch in ("wechat_jsapi", "wechat_native"):
        return bool(config.WECHAT_PAY_MCH_ID and config.WECHAT_PAY_API_KEY)
    if ch == "alipay_page":
        return bool(config.ALIPAY_APP_ID and config.ALIPAY_PRIVATE_KEY)
    return False


def _wechat_unifiedorder(order: Dict, trade_type: str, openid: str = "") -> Dict[str, str]:
    mch_id = config.WECHAT_PAY_MCH_ID
    api_key = config.WECHAT_PAY_API_KEY
    appid = config.WECHAT_APPID
    if not mch_id or not api_key:
        raise ValueError("未配置微信支付商户号或 API 密钥")

    body = {
        "appid": appid,
        "mch_id": mch_id,
        "nonce_str": _rand_str(),
        "body": f"GG台球-{order.get('venue_name', '俱乐部')}会员续费",
        "out_trade_no": order["id"],
        "total_fee": str(int(order.get("amount_fen", 0))),
        "spbill_create_ip": "127.0.0.1",
        "notify_url": config.WECHAT_PAY_NOTIFY_URL,
        "trade_type": trade_type,
    }
    if trade_type == "JSAPI":
        body["openid"] = openid
    body["sign"] = _wechat_sign(body, api_key)
    resp = requests.post(
        WECHAT_UNIFIED_URL,
        data=_dict_xml(body).encode("utf-8"),
        timeout=15,
        headers={"Content-Type": "application/xml"},
    )
    result = _xml_dict(resp.text)
    if result.get("return_code") != "SUCCESS":
        raise ValueError(result.get("return_msg") or "微信下单失败")
    if result.get("result_code") != "SUCCESS":
        raise ValueError(result.get("err_code_des") or result.get("err_code") or "微信下单失败")
    return result


def create_wechat_jsapi_payment(order: Dict, openid: str) -> Dict[str, str]:
    wx = _wechat_unifiedorder(order, "JSAPI", openid=openid)
    prepay_id = wx.get("prepay_id", "")
    pkg = f"prepay_id={prepay_id}"
    ts = str(int(time.time()))
    nonce = _rand_str(16)
    sign_data = {
        "appId": config.WECHAT_APPID,
        "timeStamp": ts,
        "nonceStr": nonce,
        "package": pkg,
        "signType": "MD5",
    }
    pay_sign = _wechat_sign(sign_data, config.WECHAT_PAY_API_KEY)
    return {
        "timeStamp": ts,
        "nonceStr": nonce,
        "package": pkg,
        "signType": "MD5",
        "paySign": pay_sign,
    }


def create_wechat_native_payment(order: Dict) -> Dict[str, str]:
    wx = _wechat_unifiedorder(order, "NATIVE")
    return {"code_url": wx.get("code_url", ""), "order_id": order["id"]}


def _alipay_sign(content: str, private_key_pem: str) -> str:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as e:
        raise ValueError("服务器未安装 cryptography，无法使用支付宝支付") from e

    key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem,
        password=None,
    )
    signature = key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("utf-8")


def create_alipay_page_payment(order: Dict) -> Dict[str, str]:
    app_id = config.ALIPAY_APP_ID
    private_key = config.ALIPAY_PRIVATE_KEY
    if not app_id or not private_key:
        raise ValueError("未配置支付宝 AppID 或应用私钥")

    biz = {
        "out_trade_no": order["id"],
        "total_amount": f"{float(order.get('amount_yuan', 0)):.2f}",
        "subject": f"GG台球俱乐部会员续费-{order.get('venue_name', '')}",
        "product_code": "FAST_INSTANT_TRADE_PAY",
    }
    params = {
        "app_id": app_id,
        "method": "alipay.trade.page.pay",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": config.ALIPAY_NOTIFY_URL,
        "return_url": config.ALIPAY_RETURN_URL,
        "biz_content": json.dumps(biz, ensure_ascii=False),
    }
    unsigned = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    params["sign"] = _alipay_sign(unsigned, private_key)
    pay_url = f"{ALIPAY_GATEWAY}?{urlencode(params, quote_via=quote_plus)}"
    return {"pay_url": pay_url, "order_id": order["id"]}


def init_order_payment(order: Dict, openid: str = "") -> Dict[str, Any]:
    if getattr(config, "PAYMENT_DEV_MODE", False):
        return {"dev_mode": True, "order_id": order["id"]}

    channel = order.get("pay_channel", "")
    if channel == "wechat_jsapi":
        return {
            "channel": channel,
            "wechat": create_wechat_jsapi_payment(order, openid),
            "order_id": order["id"],
        }
    if channel == "wechat_native":
        return {
            "channel": channel,
            **create_wechat_native_payment(order),
        }
    if channel == "alipay_page":
        return {
            "channel": channel,
            **create_alipay_page_payment(order),
        }
    raise ValueError("未知支付渠道")


def handle_wechat_pay_notify(xml_body: str) -> str:
    data = _xml_dict(xml_body)
    sign = data.pop("sign", "")
    if _wechat_sign(data, config.WECHAT_PAY_API_KEY) != sign:
        return _dict_xml({"return_code": "FAIL", "return_msg": "签名错误"})
    if data.get("return_code") != "SUCCESS" or data.get("result_code") != "SUCCESS":
        return _dict_xml({"return_code": "FAIL", "return_msg": "支付失败"})
    order_id = data.get("out_trade_no", "")
    trade_no = data.get("transaction_id", "")
    try:
        complete_membership_order(order_id, trade_no)
    except ValueError:
        return _dict_xml({"return_code": "FAIL", "return_msg": "订单处理失败"})
    return _dict_xml({"return_code": "SUCCESS", "return_msg": "OK"})


def handle_alipay_notify(form_data: Dict[str, str]) -> str:
    sign = form_data.get("sign", "")
    unsigned_items = []
    for k in sorted(form_data.keys()):
        if k in ("sign", "sign_type") or form_data[k] is None:
            continue
        unsigned_items.append(f"{k}={form_data[k]}")
    content = "&".join(unsigned_items)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        return "failure"

    pub = config.ALIPAY_PUBLIC_KEY
    if not pub:
        return "failure"
    key = serialization.load_pem_public_key(pub.encode("utf-8"))
    try:
        key.verify(
            base64.b64decode(sign),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception:
        return "failure"

    if form_data.get("trade_status") not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return "success"
    order_id = form_data.get("out_trade_no", "")
    trade_no = form_data.get("trade_no", "")
    try:
        complete_membership_order(order_id, trade_no)
    except ValueError:
        return "failure"
    return "success"
