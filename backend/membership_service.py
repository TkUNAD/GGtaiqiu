"""俱乐部会员套餐、续费订单与有效期延长"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from db import find_by_id, load, mutate, new_id, now_iso
from venue_service import DEFAULT_VENUE_ID, get_venue, is_member_active, update_venue

MEMBERSHIP_PLANS: List[Dict[str, Any]] = [
    {"id": "m1", "months": 1, "price_yuan": 28, "label": "1个月", "desc": "有效期1个月"},
    {"id": "m3", "months": 3, "price_yuan": 68, "label": "3个月", "desc": "有效期3个月"},
    {"id": "m6", "months": 6, "price_yuan": 108, "label": "6个月", "desc": "有效期6个月"},
    {"id": "m12", "months": 12, "price_yuan": 188, "label": "12个月", "desc": "有效期12个月"},
]

PLAN_BY_ID = {p["id"]: p for p in MEMBERSHIP_PLANS}


def list_membership_plans() -> List[Dict]:
    return [
        {
            "id": p["id"],
            "months": p["months"],
            "price_yuan": p["price_yuan"],
            "price_fen": int(p["price_yuan"] * 100),
            "label": p["label"],
            "desc": p["desc"],
        }
        for p in MEMBERSHIP_PLANS
    ]


def get_plan(plan_id: str) -> Optional[Dict]:
    return PLAN_BY_ID.get((plan_id or "").strip())


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except ValueError:
        return None


def extend_venue_membership(venue_id: str, months: int) -> Dict:
    """在现有到期日或当前时间基础上延长会员"""
    months = int(months)
    if months <= 0:
        raise ValueError("续费月数无效")
    venue = get_venue(venue_id)
    if not venue:
        raise ValueError("俱乐部不存在")
    now = datetime.now()
    base = _parse_dt(venue.get("member_expires_at") or "")
    if not base or base < now:
        base = now
    new_exp = base + timedelta(days=months * 30)
    new_exp_str = new_exp.replace(hour=23, minute=59, second=59).isoformat(timespec="seconds")
    updated = update_venue(venue_id, {"member_expires_at": new_exp_str})
    return {
        "venue_id": venue_id,
        "member_expires_at": updated.get("member_expires_at"),
        "is_member_active": is_member_active(updated),
    }


def venue_membership_summary(venue_id: str) -> Dict:
    venue = get_venue(venue_id or DEFAULT_VENUE_ID)
    if not venue:
        return {
            "venue_id": venue_id,
            "venue_name": "",
            "is_member_active": False,
            "member_expires_at": None,
            "member_expires_date": "",
            "plans": list_membership_plans(),
        }
    exp = venue.get("member_expires_at") or ""
    return {
        "venue_id": venue["id"],
        "venue_name": venue.get("name", ""),
        "is_member_active": is_member_active(venue),
        "member_expires_at": exp,
        "member_expires_date": exp[:10] if exp else "",
        "plans": list_membership_plans(),
    }


def create_membership_order(
    venue_id: str,
    plan_id: str,
    pay_channel: str,
    *,
    created_by: str = "",
    openid: str = "",
) -> Dict:
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError("无效的续费套餐")
    venue = get_venue(venue_id)
    if not venue:
        raise ValueError("俱乐部不存在")
    channel = (pay_channel or "").strip().lower()
    if channel not in ("wechat_jsapi", "wechat_native", "alipay_page"):
        raise ValueError("不支持的支付方式")
    if channel == "wechat_jsapi" and not (openid or "").strip():
        raise ValueError("微信内支付需要用户 openid")

    order = {
        "id": new_id("MO"),
        "venue_id": venue_id,
        "venue_name": venue.get("name", ""),
        "plan_id": plan["id"],
        "months": plan["months"],
        "amount_fen": int(plan["price_yuan"] * 100),
        "amount_yuan": plan["price_yuan"],
        "pay_channel": channel,
        "status": "pending",
        "created_at": now_iso(),
        "paid_at": None,
        "trade_no": "",
        "created_by": created_by or "",
        "openid": (openid or "").strip(),
        "nonce": secrets.token_hex(8),
    }

    def _add(orders):
        if not isinstance(orders, list):
            orders = []
        orders.append(order)
        return orders

    mutate("membership_orders", _add)
    return dict(order)


def get_membership_order(order_id: str) -> Optional[Dict]:
    return find_by_id(load("membership_orders"), order_id)


def complete_membership_order(order_id: str, trade_no: str = "") -> Dict:
    holder: Dict[str, Any] = {}

    def _pay(orders):
        o = find_by_id(orders, order_id)
        if not o:
            raise ValueError("订单不存在")
        if o.get("status") == "paid":
            holder["order"] = o
            return orders
        if o.get("status") != "pending":
            raise ValueError("订单状态不可支付")
        o["status"] = "paid"
        o["paid_at"] = now_iso()
        o["trade_no"] = trade_no or o.get("trade_no") or ""
        holder["order"] = o
        return orders

    mutate("membership_orders", _pay)
    order = holder.get("order")
    if not order:
        raise ValueError("订单处理失败")
    ext = extend_venue_membership(order["venue_id"], order.get("months", 0))
    return {"order": order, "membership": ext}


def assert_venue_allows_exchange(venue_id: Optional[str] = None) -> None:
    """玩家积分兑换：俱乐部会员须有效"""
    vid = (venue_id or DEFAULT_VENUE_ID).strip()
    venue = get_venue(vid)
    if not venue:
        raise ValueError("俱乐部不存在")
    if not is_member_active(venue):
        raise ValueError("俱乐部会员已过期，积分兑换已暂停，请联系球房续费")
