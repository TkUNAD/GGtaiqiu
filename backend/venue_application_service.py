"""俱乐部管理账号申请、审核与密码重置（管理后台登录仅用账号+密码+图形验证码）"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from werkzeug.security import generate_password_hash

from captcha_service import verify_captcha
from db import find_by_id, load, mutate, new_id, now_iso
from sms_code_service import send_code, validate_phone, verify_code
from venue_activity_service import APPLY_SOURCE_MP, INACTIVE_CANCEL_DAYS, purge_inactive_mp_applied_venues
from venue_service import create_venue, find_venue_by_username, get_venue, update_venue


def _apps() -> List[Dict]:
    return load("venue_applications")


def list_applications(status: Optional[str] = None) -> List[Dict]:
    purge_inactive_mp_applied_venues()
    rows = _apps()
    if status:
        rows = [a for a in rows if a.get("status") == status]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return [public_application_view(a) for a in rows]


def public_application_view(rec: Dict) -> Dict:
    return {
        "id": rec["id"],
        "phone": rec.get("phone", ""),
        "club_name": rec.get("club_name", ""),
        "password_plain": rec.get("password_plain", ""),
        "status": rec.get("status", "pending"),
        "venue_id": rec.get("venue_id"),
        "reject_reason": rec.get("reject_reason", ""),
        "created_at": rec.get("created_at"),
        "reviewed_at": rec.get("reviewed_at"),
        "source": rec.get("source", "mp_apply"),
    }


def submit_application(
    phone: str,
    club_name: str,
    password: str,
    confirm_password: str,
    captcha_id: str,
    captcha_code: str,
) -> Dict:
    p = validate_phone(phone)
    if not verify_captcha(captcha_id, captcha_code):
        raise ValueError("图形验证码错误或已过期")
    name = (club_name or "").strip()
    if not name or len(name) < 2:
        raise ValueError("请填写俱乐部名称")
    pwd = (password or "").strip()
    if len(pwd) < 6:
        raise ValueError("密码至少6位")
    if pwd != (confirm_password or "").strip():
        raise ValueError("两次密码不一致")
    if find_venue_by_username(p):
        v = find_venue_by_username(p)
        if v and v.get("account_status") == "cancelled":
            raise ValueError("该手机号对应账号已注销，请联系总后台")
        raise ValueError("该手机号已注册俱乐部账号")
    for a in _apps():
        if a.get("phone") == p and a.get("status") == "pending":
            raise ValueError("该手机号已有待审核申请")

    rec = {
        "id": new_id("APP"),
        "phone": p,
        "club_name": name,
        "password_plain": pwd,
        "password_hash": generate_password_hash(pwd),
        "status": "pending",
        "venue_id": None,
        "reject_reason": "",
        "source": "mp_apply",
        "created_at": now_iso(),
        "reviewed_at": None,
    }

    def _fn(rows):
        rows.append(rec)
        return rows

    mutate("venue_applications", _fn)
    return public_application_view(rec)


def approve_application(app_id: str) -> Dict:
    app_rec = find_by_id(_apps(), app_id)
    if not app_rec:
        raise ValueError("申请不存在")
    if app_rec.get("status") != "pending":
        raise ValueError("申请已处理")
    phone = app_rec["phone"]
    if find_venue_by_username(phone):
        raise ValueError("该手机号已存在俱乐部账号")

    trial_exp = (datetime.now() + timedelta(days=INACTIVE_CANCEL_DAYS)).isoformat(timespec="seconds")
    venue = create_venue({
        "name": app_rec["club_name"],
        "username": phone,
        "password": app_rec["password_plain"],
        "security_code": app_rec["password_plain"][-6:] if len(app_rec["password_plain"]) >= 6 else app_rec["password_plain"],
        "contact_phone": phone,
        "member_expires_at": trial_exp,
        "note": "小程序申请开通",
        "apply_source": APPLY_SOURCE_MP,
        "last_activity_at": now_iso(),
        "approved_at": now_iso(),
        "account_status": "active",
    })

    def _fn(rows):
        a = find_by_id(rows, app_id)
        if not a:
            return rows
        a["status"] = "approved"
        a["venue_id"] = venue["id"]
        a["reviewed_at"] = now_iso()
        return rows

    mutate("venue_applications", _fn)
    v = get_venue(venue["id"])
    if v:
        def _vn(venues):
            x = find_by_id(venues, venue["id"])
            if x:
                sec = app_rec["password_plain"][-6:] if len(app_rec["password_plain"]) >= 6 else app_rec["password_plain"]
                x["initial_password_plain"] = app_rec["password_plain"]
                x["initial_security_code_plain"] = sec
                x["apply_phone"] = phone
            return venues

        mutate("venues", _vn)
    return public_application_view(find_by_id(_apps(), app_id))


def reject_application(app_id: str, reason: str = "") -> Dict:
    def _fn(rows):
        a = find_by_id(rows, app_id)
        if not a:
            raise ValueError("申请不存在")
        if a.get("status") != "pending":
            raise ValueError("申请已处理")
        a["status"] = "rejected"
        a["reject_reason"] = (reason or "").strip()
        a["reviewed_at"] = now_iso()
        return rows

    mutate("venue_applications", _fn)
    return public_application_view(find_by_id(_apps(), app_id))


def reset_venue_password(phone: str, sms_code: str, new_password: str, confirm: str) -> Dict:
    p = validate_phone(phone)
    if not verify_code(p, "venue_reset", sms_code, consume=True):
        raise ValueError("验证码错误")
    venue = find_venue_by_username(p)
    if not venue:
        raise ValueError("该手机号未注册俱乐部")
    if venue.get("account_status") == "cancelled":
        raise ValueError("账号已注销，请联系总后台")
    pwd = (new_password or "").strip()
    if len(pwd) < 6:
        raise ValueError("新密码至少6位")
    if pwd != (confirm or "").strip():
        raise ValueError("两次密码不一致")
    update_venue(venue["id"], {"password": pwd, "initial_password_plain": pwd})
    return {"message": "密码已重置"}


def send_reset_code(phone: str) -> Dict:
    return send_code(validate_phone(phone), "venue_reset", length=4)
