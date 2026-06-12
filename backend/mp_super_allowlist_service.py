"""总后台：授权可在小程序使用总后台权限的微信 openid"""
from typing import Dict, List, Optional

from db import find_by_id, load, now_iso, save


def _read_raw() -> Dict:
    try:
        data = load("mp_super_entry_allowlist")
        if not isinstance(data, dict):
            return {"entries": []}
        data.setdefault("entries", [])
        return data
    except Exception:
        return {"entries": []}


def _write_raw(data: Dict) -> None:
    save("mp_super_entry_allowlist", data)


def _sync_bound_super_openids() -> set:
    """已绑定总后台管理员的微信自动视为已授权"""
    return {
        a.get("openid")
        for a in load("venue_admins")
        if a.get("role") == "super" and a.get("openid")
    }


def sync_super_allowlist_for_user(user: Dict) -> None:
    """按 user_id 将总后台授权白名单的 openid 同步为当前登录用户"""
    uid = ((user or {}).get("id") or "").strip()
    openid = ((user or {}).get("openid") or "").strip()
    if uid and openid:
        _sync_allowlist_entry_openid(uid, openid)


def _sync_allowlist_entry_openid(user_id: str, openid: str) -> None:
    uid = (user_id or "").strip()
    oid = (openid or "").strip()
    if not uid or not oid:
        return
    raw = _read_raw()

    def _merge(data: Dict) -> Dict:
        for e in data.get("entries") or []:
            if (e.get("user_id") or "").strip() == uid and (e.get("openid") or "").strip() != oid:
                e["openid"] = oid
        return data

    _write_raw(_merge(raw))


def is_super_mp_allowlisted(openid: str, user_id: str = "") -> bool:
    openid = (openid or "").strip()
    user_id = (user_id or "").strip()
    if openid and openid in _sync_bound_super_openids():
        return True
    for e in _read_raw().get("entries") or []:
        e_oid = (e.get("openid") or "").strip()
        e_uid = (e.get("user_id") or "").strip()
        if openid and e_oid == openid:
            return True
        if user_id and e_uid == user_id:
            if openid and e_oid != openid:
                _sync_allowlist_entry_openid(user_id, openid)
            return True
    return False


def _lookup_user_by_openid(openid: str) -> Optional[Dict]:
    for u in load("users"):
        if u.get("openid") == openid:
            return u
    return None


def _lookup_admin_by_openid(openid: str) -> Optional[Dict]:
    for a in load("venue_admins"):
        if a.get("openid") == openid:
            return a
    return None


def _web_avatar(url: str) -> str:
    """仅返回浏览器可加载的头像 URL（微信临时路径在 Web 不可用）"""
    u = (url or "").strip()
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return ""


def _profile_for_openid(openid: str, fallback_nickname: str = "") -> Dict:
    u = _lookup_user_by_openid(openid)
    if u:
        return {
            "nickname": (u.get("nickname") or fallback_nickname or "未命名").strip(),
            "avatar": _web_avatar(u.get("avatar")),
            "user_id": u.get("id", ""),
            "phone": u.get("phone", ""),
        }
    admin = _lookup_admin_by_openid(openid)
    if admin:
        nick = (admin.get("nickname") or fallback_nickname or "总后台管理员").strip()
        uid = admin.get("user_id") or ""
        if uid:
            u2 = find_by_id(load("users"), uid)
            if u2:
                return {
                    "nickname": (u2.get("nickname") or nick).strip(),
                    "avatar": _web_avatar(u2.get("avatar")),
                    "user_id": uid,
                    "phone": u2.get("phone", ""),
                }
        return {"nickname": nick, "avatar": "", "user_id": uid, "phone": ""}
    return {
        "nickname": (fallback_nickname or "未关联用户").strip(),
        "avatar": "",
        "user_id": "",
        "phone": "",
    }


def list_allowlist_entries() -> List[Dict]:
    bound = _sync_bound_super_openids()
    rows = []
    seen = set()
    for e in _read_raw().get("entries") or []:
        oid = (e.get("openid") or "").strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        prof = _profile_for_openid(oid, e.get("nickname") or "")
        rows.append({
            "openid": oid,
            "nickname": prof["nickname"],
            "avatar": prof["avatar"],
            "user_id": e.get("user_id") or prof["user_id"] or "",
            "phone": prof["phone"],
            "added_at": e.get("added_at", ""),
            "note": e.get("note", ""),
            "is_bound_super": oid in bound,
            "source": e.get("source", "manual"),
        })
    for oid in bound:
        if oid in seen:
            continue
        prof = _profile_for_openid(oid, "已绑定总后台")
        rows.append({
            "openid": oid,
            "nickname": prof["nickname"],
            "avatar": prof["avatar"],
            "user_id": prof["user_id"],
            "phone": prof["phone"],
            "added_at": "",
            "note": "已绑定总后台管理员",
            "is_bound_super": True,
            "source": "bound",
        })
    rows.sort(key=lambda x: (not x.get("is_bound_super"), x.get("added_at", "")), reverse=True)
    return rows


def add_allowlist_entry(
    openid: str,
    *,
    nickname: str = "",
    user_id: str = "",
    note: str = "",
    source: str = "manual",
) -> Dict:
    openid = (openid or "").strip()
    if not openid:
        raise ValueError("openid 不能为空")
    raw = _read_raw()
    for e in raw.get("entries") or []:
        if (e.get("openid") or "").strip() == openid:
            raise ValueError("该微信已在授权列表中")

    entry = {
        "openid": openid,
        "nickname": (nickname or "").strip(),
        "user_id": (user_id or "").strip(),
        "added_at": now_iso(),
        "note": (note or "").strip(),
        "source": source,
    }

    def _merge(data: Dict) -> Dict:
        entries = list(data.get("entries") or [])
        entries = [e for e in entries if (e.get("openid") or "").strip() != openid]
        entries.append(entry)
        data["entries"] = entries
        return data

    _write_raw(_merge(raw))
    prof = _profile_for_openid(openid, entry.get("nickname") or "")
    return {
        **entry,
        "nickname": prof["nickname"],
        "avatar": prof["avatar"],
        "phone": prof["phone"],
        "is_bound_super": openid in _sync_bound_super_openids(),
    }


def add_allowlist_by_user_id(user_id: str, note: str = "") -> Dict:
    user = find_by_id(load("users"), user_id)
    if not user:
        raise ValueError("用户不存在")
    openid = (user.get("openid") or "").strip()
    if not openid:
        raise ValueError("该用户尚未微信授权登录，无法添加")
    return add_allowlist_entry(
        openid,
        nickname=user.get("nickname", ""),
        user_id=user_id,
        note=note,
        source="admin_pick",
    )


def remove_allowlist_entry(openid: str) -> None:
    openid = (openid or "").strip()
    if not openid:
        raise ValueError("openid 不能为空")
    if openid in _sync_bound_super_openids():
        raise ValueError("该微信已绑定总后台管理员，请先在小程序退出管理后台后再移除授权")

    raw = _read_raw()
    entries = [
        e for e in (raw.get("entries") or [])
        if (e.get("openid") or "").strip() != openid
    ]
    if len(entries) == len(raw.get("entries") or []):
        raise ValueError("授权记录不存在")
    raw["entries"] = entries
    _write_raw(raw)


def register_self_from_scan(openid: str, user_id: str, nickname: str) -> Dict:
    """用户扫「授权登记码」后写入白名单"""
    if is_super_mp_allowlisted(openid):
        u = _lookup_user_by_openid(openid)
        return {
            "openid": openid,
            "nickname": nickname or (u.get("nickname") if u else ""),
            "already": True,
        }
    return add_allowlist_entry(
        openid,
        nickname=nickname,
        user_id=user_id,
        note="扫码登记",
        source="register_qr",
    )


def assert_super_mp_allowed(openid: str) -> None:
    if not is_super_mp_allowlisted(openid):
        raise ValueError("您的微信未获总后台授权，请联系总管理员在 Web 后台添加")
