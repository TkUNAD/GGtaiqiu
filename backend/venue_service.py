"""球房（租户）与会员权限"""
import math
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

# 距球房超过该距离（米）时小程序提示用户确认
VENUE_DISTANCE_WARN_METERS = 50


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点球面距离（米），坐标系 gcj02"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


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
        "manager_name": "",
        "username": "demo_hall",
        "password_hash": generate_password_hash("hall123"),
        "security_code_hash": generate_password_hash("hall123"),
        "member_expires_at": "2099-12-31T23:59:59",
        "contact_phone": "",
        "note": "演示球房（已开通会员）",
        "address": "",
        "latitude": None,
        "longitude": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    save("venues", [default])
    return [default]


def _venue_counts(venue_id: str) -> Tuple[int, int]:
    from admin_scope import users_linked_to_venue

    ensure_table_venue_ids()
    tables = load("tables")
    table_count = sum(1 for t in tables if t.get("venue_id", DEFAULT_VENUE_ID) == venue_id)
    member_count = len(users_linked_to_venue(venue_id))
    return table_count, member_count


def list_venues() -> List[Dict]:
    ensure_venues_file()
    result = []
    for v in load("venues"):
        row = venue_public_view(v, admin=True)
        tc, mc = _venue_counts(v["id"])
        row["table_count"] = tc
        row["member_count"] = mc
        result.append(row)
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


def verify_venue_security_code(username: str, code: str) -> bool:
    v = find_venue_by_username(username)
    if not v or not code:
        return False
    h = v.get("security_code_hash", "")
    if not h:
        return False
    return check_password_hash(h, code.strip())


def authenticate_venue(username: str, password: str) -> Optional[Dict]:
    v = find_venue_by_username(username)
    if not v:
        return None
    if v.get("account_status") == "cancelled":
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
        "manager_name": venue.get("manager_name", ""),
        "username": venue.get("username", ""),
        "member_expires_at": venue.get("member_expires_at"),
        "is_member_active": active,
        "contact_phone": venue.get("contact_phone", ""),
        "note": venue.get("note", ""),
        "permissions": perms,
        "has_custom_ladder_rules": bool(venue.get("ladder_rules")),
        "created_at": venue.get("created_at"),
        "updated_at": venue.get("updated_at"),
    }
    if admin:
        row["has_password"] = bool(venue.get("password_hash"))
        row["has_security_code"] = bool(venue.get("security_code_hash"))
        row["apply_phone"] = venue.get("apply_phone") or venue.get("contact_phone") or venue.get("username", "")
        row["initial_password_plain"] = venue.get("initial_password_plain", "")
        row["initial_security_code_plain"] = venue.get("initial_security_code_plain", "")
        row["apply_source"] = venue.get("apply_source", "")
        row["account_status"] = venue.get("account_status", "active")
        row["last_activity_at"] = venue.get("last_activity_at", "")
        row["approved_at"] = venue.get("approved_at", "")
        row["cancelled_at"] = venue.get("cancelled_at", "")
        row["cancel_reason"] = venue.get("cancel_reason", "")
    return row


def list_mobile_venues(latitude: float = None, longitude: float = None) -> List[Dict]:
    """小程序：球房列表（含与当前位置距离，米）"""
    ensure_venues_file()
    rows = []
    for v in load("venues"):
        lat_v = v.get("latitude")
        lng_v = v.get("longitude")
        dist = None
        if (
            latitude is not None
            and longitude is not None
            and lat_v is not None
            and lng_v is not None
        ):
            try:
                dist = int(
                    round(
                        haversine_meters(
                            float(latitude),
                            float(longitude),
                            float(lat_v),
                            float(lng_v),
                        )
                    )
                )
            except (TypeError, ValueError):
                dist = None
        rows.append(
            {
                "id": v["id"],
                "name": v.get("name", ""),
                "address": v.get("address", ""),
                "latitude": lat_v,
                "longitude": lng_v,
                "distance_m": dist,
                "is_member_active": is_member_active(v),
                "has_location": lat_v is not None and lng_v is not None,
            }
        )

    def _sort_key(item):
        if item["distance_m"] is None:
            return (1, item["name"])
        return (0, item["distance_m"])

    rows.sort(key=_sort_key)
    return rows


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


def _normalize_member_expires(val) -> str:
    s = (val or "").strip()
    if not s:
        return ""
    if len(s) == 10 and s[4] == "-":
        return s + "T23:59:59"
    return s


def create_venue(data: Dict) -> Dict:
    name = (data.get("name") or "").strip()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    security_code = (data.get("security_code") or "").strip()
    if not name or not username or not password:
        raise ValueError("请填写球房名称、登录账号和密码")
    if not security_code:
        raise ValueError("请填写安全码（用于球房忘记密码时核实身份）")
    if find_venue_by_username(username):
        raise ValueError("登录账号已存在")

    venue = {
        "id": new_id("V"),
        "name": name,
        "manager_name": (data.get("manager_name") or "").strip(),
        "username": username,
        "password_hash": generate_password_hash(password),
        "initial_password_plain": password,
        "security_code_hash": generate_password_hash(security_code),
        "initial_security_code_plain": security_code,
        "apply_phone": (data.get("apply_phone") or data.get("contact_phone") or username).strip(),
        "member_expires_at": _normalize_member_expires(data.get("member_expires_at")),
        "contact_phone": data.get("contact_phone", ""),
        "note": data.get("note", ""),
        "apply_source": (data.get("apply_source") or "").strip(),
        "last_activity_at": data.get("last_activity_at") or now_iso(),
        "approved_at": data.get("approved_at") or "",
        "account_status": data.get("account_status") or "active",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    def _fn(venues):
        venues.append(venue)
        return venues

    mutate("venues", _fn)
    return venue_public_view(venue, admin=True)


def update_venue(venue_id: str, data: Dict) -> Dict:
    old = get_venue(venue_id)
    was_active = is_member_active(old) if old else False
    updated = {}

    def _fn(venues):
        v = find_by_id(venues, venue_id)
        if not v:
            raise ValueError("球房不存在")
        if data.get("name") is not None:
            v["name"] = (data.get("name") or "").strip()
        if data.get("manager_name") is not None:
            v["manager_name"] = (data.get("manager_name") or "").strip()
        if data.get("contact_phone") is not None:
            v["contact_phone"] = data.get("contact_phone", "")
        if data.get("note") is not None:
            v["note"] = data.get("note", "")
        if data.get("address") is not None:
            v["address"] = (data.get("address") or "").strip()
        if data.get("latitude") is not None:
            v["latitude"] = data.get("latitude")
        if data.get("longitude") is not None:
            v["longitude"] = data.get("longitude")
        if data.get("member_expires_at") is not None:
            v["member_expires_at"] = _normalize_member_expires(data.get("member_expires_at"))
        if data.get("security_code"):
            code = (data.get("security_code") or "").strip()
            if code:
                v["security_code_hash"] = generate_password_hash(code)
                v["initial_security_code_plain"] = code
        if data.get("initial_security_code_plain") is not None:
            v["initial_security_code_plain"] = data.get("initial_security_code_plain") or ""
        if data.get("username") is not None:
            uname = (data.get("username") or "").strip()
            if not uname:
                raise ValueError("账号不能为空")
            other = find_venue_by_username(uname)
            if other and other["id"] != venue_id:
                raise ValueError("登录账号已被占用")
            v["username"] = uname
        if data.get("password"):
            pwd = data["password"]
            v["password_hash"] = generate_password_hash(pwd)
            v["initial_password_plain"] = data.get("initial_password_plain") or pwd
        elif data.get("initial_password_plain") is not None:
            v["initial_password_plain"] = data.get("initial_password_plain") or ""
        if data.get("last_activity_at") is not None:
            v["last_activity_at"] = data.get("last_activity_at")
        if data.get("account_status") is not None:
            v["account_status"] = data.get("account_status")
        if data.get("apply_source") is not None:
            v["apply_source"] = data.get("apply_source")
        v["updated_at"] = now_iso()
        updated["venue"] = v
        return venues

    mutate("venues", _fn)
    new_v = updated["venue"]
    if not was_active and is_member_active(new_v):
        from ladder_settings import sync_venue_ladder_from_global

        sync_venue_ladder_from_global(venue_id)
    return venue_public_view(new_v, admin=True)


def get_venue_admin_detail(venue_id: str) -> Dict:
    """总后台：球房详情（桌台、会员、积分概况）"""
    from admin_scope import users_linked_to_venue
    from rating import build_leaderboard, get_tier

    v = get_venue(venue_id)
    if not v:
        raise ValueError("球房不存在")
    ensure_table_venue_ids()
    tables = load("tables")
    venue_tables = [
        {
            "id": t["id"],
            "name": t.get("name", ""),
            "number": t.get("number", ""),
            "opened": bool(t.get("opened")),
            "current_match_id": t.get("current_match_id"),
        }
        for t in tables
        if t.get("venue_id", DEFAULT_VENUE_ID) == venue_id
    ]
    member_ids = users_linked_to_venue(venue_id)
    users = load("users")
    members = []
    total_score = 0
    for u in users:
        if u.get("id") not in member_ids:
            continue
        sc = int(u.get("score", 0))
        total_score += sc
        tier = get_tier(sc)
        members.append({
            "id": u["id"],
            "nickname": u.get("nickname", ""),
            "phone": u.get("phone", ""),
            "score": sc,
            "tier_name": tier.get("tier_name", ""),
            "wins": u.get("wins", 0),
            "losses": u.get("losses", 0),
            "status": u.get("status", "active"),
        })
    members.sort(key=lambda x: x["score"], reverse=True)
    tc, mc = _venue_counts(venue_id)
    base = venue_public_view(v, admin=True)
    base["table_count"] = tc
    base["member_count"] = mc
    return {
        "venue": base,
        "tables": venue_tables,
        "members": members,
        "total_member_score": total_score,
    }


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


def ensure_table_qr_tokens():
    """为无 token 或弱默认 token 的桌台生成随机 qr_token"""
    import secrets

    from table_util import default_qr_link

    tables = load("tables")
    changed = False
    from table_util import qr_link_matches_token, sync_qr_link

    for t in tables:
        tok = (t.get("qr_token") or "").strip()
        weak = not tok or any(tok.startswith(p) for p in ("table_", "table_T"))
        if weak:
            t["qr_token"] = secrets.token_urlsafe(16)
            sync_qr_link(t)
            changed = True
        elif not qr_link_matches_token(t):
            sync_qr_link(t)
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
