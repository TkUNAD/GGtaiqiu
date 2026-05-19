"""球房（租户）与会员权限"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from db import find_by_id, load, mutate, new_id, now_iso, save

DEFAULT_VENUE_ID = "V001"

# 未开通会员时：手机端可用，后台不可改桌台/天梯规则，不可屏蔽广告
PERM_TABLE_MANAGE = "table_manage"
PERM_LADDER_SETTINGS = "ladder_settings"
PERM_AD_BLOCK = "ad_block"

ALL_PERMISSIONS = [PERM_TABLE_MANAGE, PERM_LADDER_SETTINGS, PERM_AD_BLOCK]


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        return None


def is_member_active(venue: Dict) -> bool:
    exp = _parse_dt(venue.get("member_expires_at", ""))
    if not exp:
        return False
    return exp > datetime.now()


def venue_permissions(venue: Dict) -> Dict[str, bool]:
    active = is_member_active(venue)
    return {
        PERM_TABLE_MANAGE: active,
        PERM_LADDER_SETTINGS: active,
        PERM_AD_BLOCK: active,
    }


def super_permissions() -> Dict[str, bool]:
    return {p: True for p in ALL_PERMISSIONS}


def ensure_venues_file():
    venues = load("venues")
    if venues:
        return venues
    default = {
        "id": DEFAULT_VENUE_ID,
        "name": "默认球房",
        "username": "demo_hall",
        "password_hash": generate_password_hash("hall123"),
        "member_expires_at": "2099-12-31T23:59:59",
        "contact_phone": "",
        "note": "演示球房（已开通会员）",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    save("venues", [default])
    return [default]


def list_venues() -> List[Dict]:
    ensure_venues_file()
    result = []
    for v in load("venues"):
        result.append(venue_public_view(v, admin=True))
    return result


def find_venue_by_username(username: str) -> Optional[Dict]:
    ensure_venues_file()
    for v in load("venues"):
        if v.get("username") == username:
            return v
    return None


def get_venue(venue_id: str) -> Optional[Dict]:
    ensure_venues_file()
    return find_by_id(load("venues"), venue_id)


def authenticate_venue(username: str, password: str) -> Optional[Dict]:
    v = find_venue_by_username(username)
    if not v:
        return None
    h = v.get("password_hash", "")
    if not h:
        return None
    if check_password_hash(h, password):
        return v
    return None


def venue_public_view(venue: Dict, admin: bool = False) -> Dict:
    active = is_member_active(venue)
    perms = venue_permissions(venue)
    row = {
        "id": venue["id"],
        "name": venue.get("name", ""),
        "username": venue.get("username", ""),
        "member_expires_at": venue.get("member_expires_at"),
        "is_member_active": active,
        "contact_phone": venue.get("contact_phone", ""),
        "note": venue.get("note", ""),
        "permissions": perms,
        "created_at": venue.get("created_at"),
        "updated_at": venue.get("updated_at"),
    }
    if admin:
        row["has_password"] = bool(venue.get("password_hash"))
    return row


def mobile_venue_status(venue_id: str) -> Dict:
    v = get_venue(venue_id) or get_venue(DEFAULT_VENUE_ID)
    if not v:
        return {
            "venue_id": venue_id,
            "venue_name": "台球天梯",
            "is_member_active": False,
            "show_ads": True,
            "features": {PERM_AD_BLOCK: False},
        }
    perms = venue_permissions(v)
    return {
        "venue_id": v["id"],
        "venue_name": v.get("name", ""),
        "is_member_active": is_member_active(v),
        "member_expires_at": v.get("member_expires_at"),
        "show_ads": not perms.get(PERM_AD_BLOCK, False),
        "features": perms,
    }


def create_venue(data: Dict) -> Dict:
    name = (data.get("name") or "").strip()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not name or not username or not password:
        raise ValueError("请填写球房名称、登录账号和密码")
    if find_venue_by_username(username):
        raise ValueError("登录账号已存在")

    venue = {
        "id": new_id("V"),
        "name": name,
        "username": username,
        "password_hash": generate_password_hash(password),
        "member_expires_at": data.get("member_expires_at") or "",
        "contact_phone": data.get("contact_phone", ""),
        "note": data.get("note", ""),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    def _fn(venues):
        venues.append(venue)
        return venues

    mutate("venues", _fn)
    return venue_public_view(venue, admin=True)


def update_venue(venue_id: str, data: Dict) -> Dict:
    updated = {}

    def _fn(venues):
        v = find_by_id(venues, venue_id)
        if not v:
            raise ValueError("球房不存在")
        if data.get("name") is not None:
            v["name"] = (data.get("name") or "").strip()
        if data.get("contact_phone") is not None:
            v["contact_phone"] = data.get("contact_phone", "")
        if data.get("note") is not None:
            v["note"] = data.get("note", "")
        if data.get("member_expires_at") is not None:
            v["member_expires_at"] = data.get("member_expires_at") or ""
        if data.get("username") is not None:
            uname = (data.get("username") or "").strip()
            if not uname:
                raise ValueError("账号不能为空")
            other = find_venue_by_username(uname)
            if other and other["id"] != venue_id:
                raise ValueError("登录账号已被占用")
            v["username"] = uname
        if data.get("password"):
            v["password_hash"] = generate_password_hash(data["password"])
        v["updated_at"] = now_iso()
        updated["venue"] = v
        return venues

    mutate("venues", _fn)
    return venue_public_view(updated["venue"], admin=True)


def delete_venue(venue_id: str):
    if venue_id == DEFAULT_VENUE_ID:
        raise ValueError("默认球房不可删除")

    def _fn(venues):
        v = find_by_id(venues, venue_id)
        if not v:
            raise ValueError("球房不存在")
        tables = load("tables")
        if any(t.get("venue_id") == venue_id for t in tables):
            raise ValueError("该球房下仍有桌台，请先删除或迁移桌台")
        return [x for x in venues if x.get("id") != venue_id]

    mutate("venues", _fn)


def ensure_table_venue_ids():
    """为旧数据补全 venue_id"""
    tables = load("tables")
    changed = False
    for t in tables:
        if not t.get("venue_id"):
            t["venue_id"] = DEFAULT_VENUE_ID
            changed = True
    if changed:
        save("tables", tables)


def filter_tables_for_session(tables: List[Dict], venue_id: Optional[str], is_super: bool) -> List[Dict]:
    ensure_table_venue_ids()
    if is_super:
        return tables
    if not venue_id:
        return []
    return [t for t in tables if t.get("venue_id", DEFAULT_VENUE_ID) == venue_id]
