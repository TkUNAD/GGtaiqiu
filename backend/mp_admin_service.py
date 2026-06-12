"""小程序管理端：球房管理员绑定、扫码登录、人员管理"""
import secrets
import time
from typing import Dict, List, Optional

import config
from db import find_by_id, load, mutate, new_id, now_iso
from admin_scope import assert_user_in_venue, users_linked_to_venue
from venue_service import (
    authenticate_venue,
    get_venue,
    is_member_active,
    super_permissions,
    venue_permissions,
)

MAX_VENUE_SUB_ADMINS = 3
QR_EXPIRE_SECONDS = 300

_qr_tokens: Dict[str, Dict] = {}


def _purge_expired_qr():
    now = time.time()
    expired = [k for k, v in _qr_tokens.items() if v.get("expires_at", 0) <= now]
    for k in expired:
        _qr_tokens.pop(k, None)


def create_qr_token(
    qr_type: str,
    venue_id: Optional[str] = None,
    role: str = "admin",
    created_by: str = "",
) -> Dict:
    _purge_expired_qr()
    # 微信 scene 最长 32：adm_(4) + token，token_urlsafe(18) -> 24，合计 28
    token = secrets.token_urlsafe(18)
    _qr_tokens[token] = {
        "type": qr_type,
        "venue_id": venue_id,
        "role": role,
        "expires_at": time.time() + QR_EXPIRE_SECONDS,
        "created_by": created_by,
    }
    return {
        "token": token,
        "expires_in": QR_EXPIRE_SECONDS,
        "scene": f"adm_{token}",
    }


def consume_qr_token(token: str) -> Optional[Dict]:
    _purge_expired_qr()
    rec = _qr_tokens.pop(token, None)
    if not rec or rec.get("expires_at", 0) <= time.time():
        return None
    return rec


def list_venue_admins(venue_id: str) -> List[Dict]:
    rows = []
    for a in load("venue_admins"):
        if a.get("venue_id") != venue_id or not a.get("id"):
            continue
        rows.append(public_admin_view(a))
    users = load("users")
    for s in rows:
        u = find_by_id(users, s.get("user_id", ""))
        if u and not s.get("nickname"):
            s["nickname"] = u.get("nickname", "")
    return rows


def get_admin_by_id(admin_id: str) -> Optional[Dict]:
    return find_by_id(load("venue_admins"), admin_id)


def list_admins_by_openid(openid: str) -> List[Dict]:
    """同一微信可绑定总后台 + 俱乐部（各一条记录）"""
    if not openid:
        return []
    rows = [a for a in load("venue_admins") if a.get("openid") == openid and a.get("id")]
    order = {"super": 0, "owner": 1, "admin": 2}
    rows.sort(key=lambda a: (order.get(a.get("role"), 9), a.get("venue_id") or ""))
    return rows


def sync_venue_admin_bindings_for_user(user: Dict) -> int:
    """
    登录/查入口时同步 venue_admins 与当前微信用户：
    - user_id 一致 → 更新 openid（AppID 变更）
    - openid 一致 → 更新 user_id（历史脏数据）
    - 绑定记录 user_id 已失效且昵称一致 → 整记录迁移到当前用户（AppID 变更且新建了用户）
    返回更新的记录数。
    """
    uid = ((user or {}).get("id") or "").strip()
    openid = ((user or {}).get("openid") or "").strip()
    nick = ((user or {}).get("nickname") or "").strip()
    phone = ((user or {}).get("phone") or "").strip()
    if not uid or not openid:
        return 0

    users = load("users")
    changed = 0

    def _sync(admins):
        nonlocal changed
        for a in admins:
            aid_oid = (a.get("openid") or "").strip()
            aid_uid = (a.get("user_id") or "").strip()
            if aid_oid == openid and aid_uid != uid:
                a["user_id"] = uid
                changed += 1
                continue
            if aid_uid == uid and aid_oid != openid:
                a["openid"] = openid
                changed += 1
                continue
            if aid_oid == openid or aid_uid == uid:
                continue
            if not aid_uid:
                continue
            old_user = find_by_id(users, aid_uid)
            if old_user and (old_user.get("openid") or "").strip() not in ("", openid):
                continue
            admin_nick = (a.get("nickname") or "").strip()
            if nick and admin_nick and admin_nick == nick:
                a["openid"] = openid
                a["user_id"] = uid
                changed += 1
                continue
            if phone and old_user and (old_user.get("phone") or "").strip() == phone:
                a["openid"] = openid
                a["user_id"] = uid
                changed += 1
        return admins

    mutate("venue_admins", _sync)
    return changed


# 兼容旧调用名
sync_venue_admin_openid_for_user = sync_venue_admin_bindings_for_user


def list_admins_for_mp_user(
    openid: str, user_id: str = "", user: Optional[Dict] = None
) -> List[Dict]:
    """小程序「我的」页：先同步再按 openid / user_id 查绑定"""
    if user:
        sync_venue_admin_bindings_for_user(user)
        openid = (user.get("openid") or openid or "").strip()
        user_id = (user.get("id") or user_id or "").strip()
    rows = list_admins_by_openid(openid)
    if rows:
        return rows
    uid = (user_id or "").strip()
    oid = (openid or "").strip()
    if not uid or not oid:
        return []
    rows = [a for a in load("venue_admins") if a.get("user_id") == uid and a.get("id")]
    if rows:
        sync_venue_admin_bindings_for_user({"id": uid, "openid": oid})
        return list_admins_by_openid(oid)
    return []


def get_admin_by_openid(openid: str) -> Optional[Dict]:
    rows = list_admins_by_openid(openid)
    return rows[0] if rows else None


def get_admin_by_id_for_openid(openid: str, admin_id: str) -> Optional[Dict]:
    if not openid or not admin_id:
        return None
    for a in list_admins_by_openid(openid):
        if a.get("id") == admin_id:
            return a
    return None


def openid_has_venue_admin(openid: str, venue_id: Optional[str] = None) -> bool:
    for a in list_admins_by_openid(openid):
        if a.get("role") not in ("owner", "admin"):
            continue
        if venue_id is None or a.get("venue_id") == venue_id:
            return True
    return False


def openid_has_super_admin(openid: str) -> bool:
    return any(a.get("role") == "super" for a in list_admins_by_openid(openid))


def get_venue_admin_by_openid(openid: str, venue_id: str) -> Optional[Dict]:
    for a in list_admins_by_openid(openid):
        if a.get("role") == "super":
            continue
        if a.get("venue_id") == venue_id:
            return a
    return None


def public_admin_identity(rec: Dict) -> Dict:
    info = build_mp_admin_session_info(rec)
    is_super = rec.get("role") == "super"
    role = rec.get("role") or ""
    venue_name = info.get("venue_name") or ""
    if is_super:
        title, subtitle, hint = "总后台管理", "平台运营管理", "点击进入 · 免密切换"
    elif role == "owner":
        title, subtitle = "俱乐部后台", venue_name or "俱乐部管理"
        hint = f"{subtitle} · 主管理员 · 点击进入"
    else:
        title, subtitle = "俱乐部后台", venue_name or "俱乐部管理"
        hint = f"{subtitle} · 子管理员 · 点击进入"
    return {
        "admin_id": rec.get("id", ""),
        "role": role,
        "admin_role": role,
        "venue_id": rec.get("venue_id"),
        "venue_name": venue_name,
        "console_type": info.get("console_type") or ("super" if is_super else "venue"),
        "is_super": is_super,
        "title": title,
        "subtitle": subtitle,
        "hint": hint,
    }


def get_venue_owner(venue_id: str) -> Optional[Dict]:
    for a in load("venue_admins"):
        if a.get("venue_id") == venue_id and a.get("role") == "owner":
            return a
    return None


def get_venue_admin_by_user_id(venue_id: str, user_id: str) -> Optional[Dict]:
    for a in load("venue_admins"):
        if a.get("venue_id") == venue_id and a.get("user_id") == user_id:
            return a
    return None


def count_venue_sub_admins(venue_id: str) -> int:
    return sum(
        1
        for a in load("venue_admins")
        if a.get("venue_id") == venue_id and a.get("role") == "admin"
    )


def public_admin_view(rec: Dict) -> Dict:
    return {
        "id": rec.get("id", ""),
        "venue_id": rec.get("venue_id"),
        "user_id": rec.get("user_id"),
        "role": rec.get("role"),
        "nickname": rec.get("nickname", ""),
        "created_at": rec.get("created_at"),
        "last_login_at": rec.get("last_login_at"),
    }


def build_mp_admin_session_info(admin_rec: Dict) -> Dict:
    role = admin_rec.get("role", "admin")
    if role == "super":
        return {
            "role": "super",
            "username": "总后台",
            "venue_id": None,
            "venue_name": "总后台",
            "admin_id": admin_rec["id"],
            "admin_role": "super",
            "is_member_active": True,
            "member_expires_at": None,
            "permissions": super_permissions(),
            "can_manage_staff": False,
            "console_type": "super",
        }
    vid = admin_rec.get("venue_id")
    venue = get_venue(vid) if vid else None
    active = is_member_active(venue) if venue else False
    perms = venue_permissions(venue) if venue else {}
    is_owner = role == "owner"
    owner_bound = bool(get_venue_owner(vid)) if vid else False
    info = {
        "role": "venue",
        "username": admin_rec.get("nickname") or (venue.get("name", "") if venue else ""),
        "venue_id": vid,
        "venue_name": venue.get("name", "") if venue else "",
        "admin_id": admin_rec["id"],
        "admin_role": role,
        "is_member_active": active,
        "member_expires_at": venue.get("member_expires_at") if venue else None,
        "permissions": perms,
        "can_manage_staff": is_owner,
        "can_promote_players": is_owner,
        "has_venue_owner": owner_bound,
        "console_type": "venue",
    }
    if not active and venue:
        info["member_tip"] = "俱乐部会员已过期：仅可查看仪表盘、玩家、桌台"
    return info


def check_user_eligibility(openid: str) -> Dict:
    rec = get_admin_by_openid(openid)
    if not rec:
        return {"eligible": False}
    info = build_mp_admin_session_info(rec)
    return {
        "eligible": True,
        "role": rec.get("role"),
        "venue_id": rec.get("venue_id"),
        "venue_name": info.get("venue_name"),
        "admin_role": rec.get("role"),
        "is_super": rec.get("role") == "super",
    }


def _load_entry_allowlist() -> set:
    """允许在「未绑定前」看到管理入口的微信 openid（首次绑定用）"""
    import os

    from db import DATA_DIR

    openids = set()
    path = os.path.join(DATA_DIR, "mp_admin_entry_allowlist.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                import json

                data = json.load(f)
            for oid in data.get("openids") or []:
                if oid and str(oid).strip():
                    openids.add(str(oid).strip())
        except Exception:
            pass
    env_raw = (os.environ.get("MP_ADMIN_ENTRY_OPENIDS") or "").strip()
    if env_raw:
        for oid in env_raw.split(","):
            oid = oid.strip()
            if oid:
                openids.add(oid)
    return openids


def _sync_allowlist_from_admins() -> None:
    """已绑定管理员的 openid 自动视为可见（无需手写白名单）"""
    return {a.get("openid") for a in load("venue_admins") if a.get("openid")}


def build_profile_console_entries(
    openid: str,
    venue_id: Optional[str] = None,
    user_id: str = "",
    user: Optional[Dict] = None,
) -> List[Dict]:
    """「我的」页管理入口：已绑定免密进入 + 未绑定时的验证入口"""
    from mp_super_allowlist_service import is_super_mp_allowlisted, sync_super_allowlist_for_user

    if user:
        sync_super_allowlist_for_user(user)
    entries: List[Dict] = []
    bound_admins = list_admins_for_mp_user(openid, user_id, user)
    for a in bound_admins:
        item = public_admin_identity(a)
        item["entry_type"] = "bound"
        item["entry_key"] = f"bound_{a.get('id')}"
        entries.append(item)

    has_super = any(a.get("role") == "super" for a in bound_admins)
    has_venue = any(a.get("role") in ("owner", "admin") for a in bound_admins)
    on_super_allow = is_super_mp_allowlisted(openid, user_id)
    allow = _load_entry_allowlist() | _sync_allowlist_from_admins()
    on_venue_allow = (openid in allow) or bool(user_id and bound_admins)
    need_owner = bool(venue_id) and not get_venue_owner(venue_id)

    if on_super_allow and not has_super:
        entries.append(
            {
                "entry_type": "super_auth",
                "entry_key": "super_auth",
                "title": "总后台管理",
                "subtitle": "平台运营管理",
                "hint": "首次需验证总后台账号密码，验证后免密进入",
                "admin_id": "",
                "is_super": True,
            }
        )

    if not has_venue and (on_venue_allow or has_super):
        if need_owner:
            hint = "绑定本俱乐部主管理员（网页生成码或账号密码），绑定后免密进入"
        else:
            hint = "使用俱乐部账号密码绑定微信，绑定后免密进入"
        entries.append(
            {
                "entry_type": "venue_auth",
                "entry_key": "venue_auth",
                "title": "俱乐部后台",
                "subtitle": "俱乐部管理",
                "hint": hint,
                "need_owner_bind": need_owner,
                "admin_id": "",
                "is_super": False,
            }
        )

    return entries


def check_mp_admin_visibility(
    openid: str,
    venue_id: Optional[str] = None,
    user_id: str = "",
    user: Optional[Dict] = None,
) -> Dict:
    """
    控制小程序「我的」页是否展示管理入口。
    - 已绑定：免密进入（console_entries entry_type=bound）
    - 未绑定总后台/俱乐部：展示对应验证入口（super_auth / venue_auth）
    """
    if user:
        sync_venue_admin_bindings_for_user(user)
        openid = (user.get("openid") or openid or "").strip()
        user_id = (user.get("id") or user_id or "").strip()
    openid = (openid or "").strip()
    if not openid:
        return {
            "eligible": False,
            "console_entries": [],
            "admin_identities": [],
            "has_multiple_consoles": False,
            "show_admin_entry": False,
            "show_login_entry": False,
            "show_super_login_entry": False,
            "show_owner_bind_entry": False,
        }

    console_entries = build_profile_console_entries(
        openid, venue_id, user_id, user=user
    )
    bound = [e for e in console_entries if e.get("entry_type") == "bound"]
    identities = [e for e in bound]
    is_super = any(i.get("is_super") for i in identities)
    has_super_auth = any(e.get("entry_type") == "super_auth" for e in console_entries)
    venue_auth = [e for e in console_entries if e.get("entry_type") == "venue_auth"]
    has_venue_auth = bool(venue_auth)
    need_owner = bool(venue_auth and venue_auth[0].get("need_owner_bind"))

    first = identities[0] if identities else {}
    return {
        "eligible": len(bound) > 0,
        "console_entries": console_entries,
        "admin_identities": identities,
        "has_multiple_consoles": len(bound) > 1,
        "has_dual_console": len(bound) >= 2,
        "role": first.get("role"),
        "venue_id": first.get("venue_id"),
        "venue_name": first.get("venue_name"),
        "admin_role": first.get("admin_role"),
        "is_super": is_super,
        "show_admin_entry": len(bound) == 1,
        "show_login_entry": has_venue_auth and not need_owner,
        "show_super_login_entry": has_super_auth,
        "show_owner_bind_entry": has_venue_auth and need_owner,
        "need_owner_bind": need_owner,
    }


def _is_super_session_info(session_info: Dict) -> bool:
    return (
        session_info.get("role") == "super"
        or session_info.get("console_type") == "super"
        or session_info.get("admin_role") == "super"
    )


def build_admin_menu(session_info: Dict) -> List[Dict]:
    """与 Web 侧栏一致：总后台与俱乐部后台菜单分离"""
    is_super = _is_super_session_info(session_info)
    active = session_info.get("is_member_active", False)
    perms = session_info.get("permissions") or {}
    can_staff = session_info.get("can_manage_staff", False)
    expired = not is_super and not active

    def item(mid: str, title: str, desc: str = "", badge_key: str = ""):
        return {
            "id": mid,
            "title": title,
            "desc": desc,
            "badge_key": badge_key,
        }

    # 总后台（与 Web 对齐：仪表盘、天梯、球房会员、授权、设置）
    if is_super:
        return [
            item("dashboard", "仪表盘", "全平台与各球房概况"),
            item("ladder", "天梯规则", "全平台默认规则"),
            item("venues", "球房会员", "申请审核·开通续费"),
            item("mp_wechat", "授权微信", "小程序总后台入口"),
            item("settings", "系统设置", "密码·数据重置"),
        ]

    # 俱乐部后台：到期后仍展示全部入口，禁用项标 disabled 供前端置灰
    def venue_item(mid: str, title: str, desc: str = "", badge_key: str = "", *, locked: bool = False):
        row = item(mid, title, desc, badge_key)
        row["disabled"] = bool(locked)
        if locked:
            row["desc"] = (desc or "") + (" · " if desc else "") + "会员已到期"
        return row

    table_desc = "开台与二维码" if perms.get("table_manage") else "仅查看"
    user_desc = "调分·设子管理员" if not expired else "仅查看"
    return [
        venue_item("dashboard", "仪表盘", "本俱乐部数据概览"),
        venue_item("matches", "对局管理", "历史对局", locked=expired),
        venue_item("users", "玩家管理", user_desc),
        venue_item("tables", "桌台管理", table_desc),
        venue_item("review", "对局审核", "待审·审核记录·兑换", "pending_all", locked=expired),
        venue_item("ladder", "天梯规则", "总后台规则说明"),
        venue_item("products", "兑换商品", "商品列表", locked=expired),
        venue_item("exchanges", "兑换记录", "全部记录", locked=expired),
        venue_item("logs", "积分明细", "变动记录", locked=expired),
        venue_item("staff", "管理员设置", "子管理员列表(≤3)", locked=expired),
    ]


def bind_venue_owner(
    venue_id: str,
    openid: str,
    user_id: str,
    nickname: str,
) -> Dict:
    if get_venue_owner(venue_id):
        raise ValueError("该球房已有主管理员，请使用扫码登录")
    venue = get_venue(venue_id)
    if not venue:
        raise ValueError("球房不存在")
    if openid_has_venue_admin(openid):
        raise ValueError("您的微信已绑定俱乐部管理账号")

    admin = {
        "id": new_id("VA"),
        "venue_id": venue_id,
        "openid": openid,
        "user_id": user_id,
        "role": "owner",
        "nickname": nickname or "",
        "refresh_tokens": [],
        "created_at": now_iso(),
        "created_by": "bind_owner",
    }

    def _fn(records):
        records.append(admin)
        return records

    mutate("venue_admins", _fn)
    return admin


def bind_from_qr(
    qr_rec: Dict,
    openid: str,
    user_id: str,
    nickname: str,
) -> Dict:
    qr_type = qr_rec.get("type")
    venue_id = qr_rec.get("venue_id")

    if qr_type == "super_login":
        return _login_super_by_qr(openid, user_id, nickname)

    if qr_type == "owner_bind":
        if openid_has_venue_admin(openid):
            raise ValueError("您的微信已绑定俱乐部管理账号")
        return bind_venue_owner(venue_id, openid, user_id, nickname)

    if qr_type == "login":
        admin = get_venue_admin_by_openid(openid, venue_id)
        if not admin:
            raise ValueError("您尚未获得管理权限，请联系俱乐部主管理员")
        return admin

    if qr_type == "invite":
        if openid_has_venue_admin(openid, venue_id):
            raise ValueError("您的微信已是本俱乐部管理员")
        if not get_venue_owner(venue_id):
            raise ValueError("球房尚未设置主管理员")
        if count_venue_sub_admins(venue_id) >= MAX_VENUE_SUB_ADMINS:
            raise ValueError(f"子管理员已达上限（{MAX_VENUE_SUB_ADMINS}人）")
        owner = get_venue_owner(venue_id)
        admin = {
            "id": new_id("VA"),
            "venue_id": venue_id,
            "openid": openid,
            "user_id": user_id,
            "role": "admin",
            "nickname": nickname or "",
            "refresh_tokens": [],
            "created_at": now_iso(),
            "created_by": owner["id"] if owner else "",
        }

        def _fn(records):
            records.append(admin)
            return records

        mutate("venue_admins", _fn)
        return admin

    raise ValueError("无效的扫码类型")


def _login_super_by_qr(openid: str, user_id: str, nickname: str) -> Dict:
    from mp_super_allowlist_service import assert_super_mp_allowed

    for a in list_admins_by_openid(openid):
        if a.get("role") == "super":
            return a
    assert_super_mp_allowed(openid)
    super_count = sum(1 for a in load("venue_admins") if a.get("role") == "super")
    if super_count >= 3:
        raise ValueError("总后台小程序管理员已达上限")
    admin = {
        "id": new_id("VA"),
        "venue_id": None,
        "openid": openid,
        "user_id": user_id,
        "role": "super",
        "nickname": nickname or "总后台",
        "refresh_tokens": [],
        "created_at": now_iso(),
        "created_by": "super_qr",
    }

    def _fn(records):
        records.append(admin)
        return records

    mutate("venue_admins", _fn)
    return admin


def bind_owner_with_password(
    username: str,
    password: str,
    openid: str,
    user_id: str,
    nickname: str,
) -> Dict:
    venue = authenticate_venue(username, password)
    if not venue:
        raise ValueError("球房账号或密码错误")
    return bind_venue_owner(venue["id"], openid, user_id, nickname)


def bind_super_with_password(
    username: str,
    password: str,
    openid: str,
    user_id: str,
    nickname: str,
) -> Dict:
    from mp_super_allowlist_service import assert_super_mp_allowed
    from super_setup_service import authenticate_super

    if not openid_has_super_admin(openid):
        assert_super_mp_allowed(openid)
    if not authenticate_super(username, password):
        raise ValueError("总后台账号或密码错误")
    return _login_super_by_qr(openid, user_id, nickname)


def list_venue_players(venue_id: str) -> List[Dict]:
    """本俱乐部玩家列表（含是否已是子管理员）"""
    from db import find_by_id as _fid

    allowed = users_linked_to_venue(venue_id)
    admin_user_ids = {
        a.get("user_id")
        for a in load("venue_admins")
        if a.get("venue_id") == venue_id and a.get("user_id")
    }
    admin_openids = {
        a.get("openid")
        for a in load("venue_admins")
        if a.get("venue_id") == venue_id and a.get("openid")
    }
    out = []
    for u in load("users"):
        if u.get("id") not in allowed:
            continue
        adm = None
        for a in load("venue_admins"):
            if a.get("venue_id") == venue_id and a.get("user_id") == u.get("id"):
                adm = a
                break
        is_admin = adm is not None
        out.append({
            "id": u.get("id"),
            "nickname": u.get("nickname", ""),
            "phone": u.get("phone", ""),
            "score": u.get("score", 0),
            "openid": u.get("openid", ""),
            "has_openid": bool(u.get("openid")),
            "is_venue_admin": is_admin,
            "venue_admin_role": adm.get("role") if adm else None,
            "venue_admin_id": adm.get("id") if adm else None,
            "can_promote": bool(u.get("openid")) and not is_admin,
            "can_demote_admin": is_admin and adm.get("role") == "admin",
        })
    out.sort(key=lambda x: (-int(x.get("is_venue_admin", False)), x.get("nickname", "")))
    return out


def promote_player_to_sub_admin(
    venue_id: str,
    target_user_id: str,
    operator_admin_id: str = "",
    *,
    via_venue_account: bool = False,
) -> Dict:
    """将本俱乐部玩家设为子管理员（网页俱乐部账号或小程序主管理员）"""
    if not via_venue_account:
        owner = get_venue_owner(venue_id)
        if not owner or owner.get("id") != operator_admin_id:
            raise ValueError("仅俱乐部主管理员可设置子管理员")
    op_id = operator_admin_id or "venue_web"
    assert_user_in_venue(target_user_id, venue_id, False)
    target = find_by_id(load("users"), target_user_id)
    if not target:
        raise ValueError("玩家不存在")
    openid = (target.get("openid") or "").strip()
    if not openid:
        raise ValueError("该玩家尚未完成微信授权，无法设为管理员")
    if openid_has_venue_admin(openid, venue_id):
        raise ValueError("该玩家已是本俱乐部管理员")
    if count_venue_sub_admins(venue_id) >= MAX_VENUE_SUB_ADMINS:
        raise ValueError(f"子管理员已达上限（{MAX_VENUE_SUB_ADMINS}人）")
    admin = {
        "id": new_id("VA"),
        "venue_id": venue_id,
        "openid": openid,
        "user_id": target_user_id,
        "role": "admin",
        "nickname": target.get("nickname", ""),
        "refresh_tokens": [],
        "created_at": now_iso(),
        "created_by": op_id,
    }

    def _fn(records):
        records.append(admin)
        return records

    mutate("venue_admins", _fn)
    from venue_activity_service import touch_venue_activity

    touch_venue_activity(venue_id)
    return public_admin_view(admin)


def remove_sub_admin(
    owner_admin_id: str,
    target_admin_id: str,
    *,
    via_venue_account: bool = False,
) -> None:
    target = get_admin_by_id(target_admin_id)
    if not target:
        raise ValueError("管理员不存在")
    if target.get("role") != "admin":
        raise ValueError("只能移除子管理员")
    if not via_venue_account:
        owner = get_admin_by_id(owner_admin_id)
        if not owner or owner.get("role") != "owner":
            raise ValueError("仅主管理员可移除子管理员")
        if target.get("venue_id") != owner.get("venue_id"):
            raise ValueError("无权操作")

    def _fn(records):
        return [r for r in records if r.get("id") != target_admin_id]

    mutate("venue_admins", _fn)


def resolve_admin_for_relogin(openid: str, admin_id: Optional[str] = None) -> Dict:
    """恢复管理登录：指定 admin_id，或仅一条绑定记录时自动选用"""
    rows = list_admins_by_openid(openid)
    if not rows:
        raise ValueError("您尚未绑定管理权限")
    if admin_id:
        rec = get_admin_by_id_for_openid(openid, admin_id)
        if not rec:
            raise ValueError("无效的管理身份")
        return rec
    if len(rows) == 1:
        return rows[0]
    raise ValueError("您绑定了多个管理后台，请在「我的」选择要进入的入口")


def create_owner_bind_qr(venue_id: str, created_by: str = "") -> Dict:
    """生成主管理员绑定码：微信扫码后成为该俱乐部唯一主管理员"""
    if not venue_id:
        raise ValueError("缺少俱乐部信息")
    if get_venue_owner(venue_id):
        raise ValueError("该俱乐部已有主管理员，每个俱乐部仅可绑定一名")
    if not get_venue(venue_id):
        raise ValueError("俱乐部不存在")
    qr = create_qr_token(
        "owner_bind",
        venue_id=venue_id,
        role="owner",
        created_by=created_by or "web",
    )
    scene = qr["scene"]
    scan_guide = (
        "1. 被绑定人先打开本小程序，在「我的」完成微信授权登录；\n"
        "2. 进入「我的」→ 点「俱乐部后台」或底部「管理后台登录」；\n"
        "3. 在页面内点「扫一扫」（不要用微信首页的扫一扫）；\n"
        "4. 对准本二维码扫描，提示成功即可；之后在「我的」可免密进入俱乐部后台。\n"
        "注意：每个俱乐部仅 1 名主管理员；码约 5 分钟有效，过期请在网页重新生成。"
    )
    return {
        **qr,
        "qr_base64": qr_png_base64(scene, "pages/admin-scan/admin-scan"),
        "scene": scene,
        "hint": scan_guide,
        "scan_guide": scan_guide,
    }


def qr_png_base64(text: str, page: str = "") -> str:
    """生成二维码 PNG 的 data URL；若配置微信 Secret 且提供 page 则生成小程序码"""
    import base64
    from io import BytesIO

    if page:
        try:
            from wx_miniprogram_qr import build_miniprogram_qr, normalize_scene

            png, _ = build_miniprogram_qr(page, normalize_scene(text))
            return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        except Exception:
            pass

    try:
        import qrcode
    except ImportError:
        return ""
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#4C1D95", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def admin_record_from_jwt_claims(claims: Dict) -> Optional[Dict]:
    admin_id = claims.get("admin_id") or claims.get("sub")
    if not admin_id:
        return None
    rec = get_admin_by_id(admin_id)
    if not rec:
        return None
    uid = rec.get("user_id") or ""
    if uid:
        user = find_by_id(load("users"), uid)
        if user and rec.get("openid") and user.get("openid") != rec.get("openid"):
            return None
    return rec
