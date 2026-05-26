"""球房账号活跃追踪：小程序申请开通的俱乐部 30 天无操作自动注销"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from db import find_by_id, load, mutate, now_iso
from venue_service import get_venue, update_venue

INACTIVE_CANCEL_DAYS = 30
APPLY_SOURCE_MP = "mp_apply"


def touch_venue_activity(venue_id: str) -> None:
    """记录球房最近一次操作时间（登录、审核、对局等）"""
    if not venue_id:
        return
    v = get_venue(venue_id)
    if not v or v.get("account_status") == "cancelled":
        return
    update_venue(venue_id, {"last_activity_at": now_iso()})


def cancel_venue_account(venue_id: str, reason: str = "") -> None:
    """注销俱乐部管理账号（保留数据记录，禁止再登录）"""
    v = get_venue(venue_id)
    if not v:
        return

    def _vn(venues):
        x = find_by_id(venues, venue_id)
        if not x:
            return venues
        x["account_status"] = "cancelled"
        x["cancelled_at"] = now_iso()
        x["cancel_reason"] = (reason or "").strip() or "长期无操作自动注销"
        x["member_expires_at"] = datetime.now().isoformat(timespec="seconds")
        return venues

    mutate("venues", _vn)

    def _rm_admins(rows):
        return [r for r in rows if r.get("venue_id") != venue_id]

    mutate("venue_admins", _rm_admins)


def purge_inactive_mp_applied_venues() -> List[str]:
    """
    小程序申请开通的球房：超过 INACTIVE_CANCEL_DAYS 无操作则注销。
    返回本次注销的 venue_id 列表。
    """
    cutoff = datetime.now() - timedelta(days=INACTIVE_CANCEL_DAYS)
    cancelled: List[str] = []
    for v in load("venues"):
        if v.get("apply_source") != APPLY_SOURCE_MP:
            continue
        if v.get("account_status") == "cancelled":
            continue
        last = _parse_dt(v.get("last_activity_at") or v.get("approved_at") or v.get("created_at"))
        if not last or last >= cutoff:
            continue
        cancel_venue_account(
            v["id"],
            f"申请开通后{INACTIVE_CANCEL_DAYS}天内无操作，账号已自动注销",
        )
        cancelled.append(v["id"])
    return cancelled


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except ValueError:
        return None
