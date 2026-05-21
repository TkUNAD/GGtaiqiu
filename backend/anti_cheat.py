"""防刷与违规处理"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from config import DAILY_SCORE_ALERT, INITIAL_SCORE, MIN_MATCH_SECONDS, PERMANENT_BAN_VIOLATION_COUNT
from db import load, mutate, now_iso, new_id

SERIOUS_VIOLATION_ACTIONS = frozenset({
    "cheat_penalty",
    "cheat",
    "ban",
    "malicious_score",
    "record_cheat",
    "permanent_ban",
})


def check_ip_limit(ip: str, openid: str) -> Tuple[bool, str]:
    """同一 IP 注册数量限制已关闭（保留接口供后续如需恢复）"""
    return True, "ok"


def check_phone_unique(phone: str, exclude_user_id: str = None) -> Tuple[bool, str]:
    if not phone:
        return True, "ok"
    users = load("users")
    for u in users:
        if u.get("phone") == phone and u.get("id") != exclude_user_id:
            return False, "该手机号已绑定其他账号"
    return True, "ok"


def match_duration_valid(started_at: str, ended_at: str = None) -> bool:
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at) if ended_at else datetime.now()
    except ValueError:
        return False
    return (end - start).total_seconds() >= MIN_MATCH_SECONDS


def check_daily_score_alert(user_id: str, add_score: int) -> Optional[str]:
    logs = load("score_logs")
    today = datetime.now().strftime("%Y-%m-%d")
    total = sum(
        l["delta"]
        for l in logs
        if l.get("user_id") == user_id and l.get("created_at", "").startswith(today) and l["delta"] > 0
    )
    if total + add_score >= DAILY_SCORE_ALERT:
        return f"用户单日积分增长预警: +{total + add_score}"
    return None


def is_serious_violation(record: Dict) -> bool:
    action = record.get("action", "")
    reason = record.get("reason", "") or ""
    if action in SERIOUS_VIOLATION_ACTIONS:
        return True
    keywords = ("作弊", "恶意", "刷分", "虚假")
    return any(k in reason for k in keywords)


def count_serious_violations(user_id: str) -> int:
    return sum(
        1 for v in load("violations") if v.get("user_id") == user_id and is_serious_violation(v)
    )


def apply_permanent_ban(user_id: str, reason: str) -> None:
    def _fn(users):
        u = next((x for x in users if x["id"] == user_id), None)
        if not u:
            return users
        u["status"] = "banned"
        u["ban_permanent"] = True
        u["banned_at"] = now_iso()
        u["ban_reason"] = reason
        u["updated_at"] = now_iso()
        return users

    mutate("users", _fn)


def add_violation(user_id: str, reason: str, action: str = "warn", public: bool = False):
    def _fn(violations):
        violations.append({
            "id": new_id("V"),
            "user_id": user_id,
            "reason": reason,
            "action": action,
            "public": public,
            "created_at": now_iso(),
        })
        return violations

    mutate("violations", _fn)
    if public:
        def _settings(s):
            pub = s.setdefault("public_violations", [])
            users = load("users")
            u = next((x for x in users if x["id"] == user_id), None)
            pub.insert(0, {
                "user_id": user_id,
                "nickname": u.get("nickname", "球友") if u else "未知",
                "reason": reason,
                "action": action,
                "at": now_iso(),
            })
            s["public_violations"] = pub[:20]
            return s

        mutate("settings", _settings)


def add_violation_and_check_permanent(
    user_id: str,
    reason: str,
    action: str = "record_cheat",
    public: bool = True,
) -> Dict:
    """记录严重违规，累计达阈值自动永久封禁"""
    add_violation(user_id, reason, action, public)
    total = count_serious_violations(user_id)
    auto_banned = False
    if total >= PERMANENT_BAN_VIOLATION_COUNT:
        ban_reason = f"累计{total}次恶意刷分/作弊，永久禁止使用本系统"
        apply_permanent_ban(user_id, ban_reason)
        auto_banned = True
    return {"serious_count": total, "auto_permanent_ban": auto_banned}


def publish_cheat_announcement(nickname: str, message: str, scroll_times: int = 3):
    """作弊公示：写入大屏滚动队列"""
    times = max(1, int(scroll_times or 3))

    def _settings(s):
        ann = s.setdefault("cheat_announcements", [])
        ann.insert(0, {
            "nickname": nickname,
            "message": message,
            "scroll_times": times,
            "at": now_iso(),
        })
        s["cheat_announcements"] = ann[:30]
        return s

    mutate("settings", _settings)


def punish_user(user_id: str, action: str, reason: str, public: bool = True):
    users_before = load("users")
    u_before = next((x for x in users_before if x["id"] == user_id), None)
    old_score = u_before.get("score", INITIAL_SCORE) if u_before else INITIAL_SCORE

    if action == "record_cheat":
        result = add_violation_and_check_permanent(user_id, reason, "record_cheat", public)
        if result.get("auto_permanent_ban") and u_before:
            publish_cheat_announcement(
                u_before.get("nickname", "球友"),
                reason,
                3,
            )
        return

    if action == "permanent_ban":
        apply_permanent_ban(user_id, reason or "管理员永久封禁")
        add_violation(user_id, reason or "永久封禁", "permanent_ban", public)
        return

    def _fn(users):
        u = next((x for x in users if x["id"] == user_id), None)
        if not u:
            return users
        if action == "reset_score":
            u["score"] = INITIAL_SCORE
            u["wins"] = 0
            u["losses"] = 0
        elif action == "ban":
            u["status"] = "banned"
            u["ban_permanent"] = True
            u["banned_at"] = now_iso()
            u["ban_reason"] = reason
        elif action == "unban":
            u["status"] = "active"
            u.pop("ban_permanent", None)
            u.pop("banned_at", None)
            u.pop("ban_reason", None)
        u["updated_at"] = now_iso()
        return users

    mutate("users", _fn)
    if action == "reset_score" and u_before:
        from services import log_score

        log_score(user_id, INITIAL_SCORE - old_score, reason, None)
    add_violation(user_id, reason, action, public)


def check_user_allowed(user: Dict) -> Tuple[bool, str]:
    if user.get("status") == "banned":
        if user.get("ban_permanent"):
            return False, "账号已被永久封禁，无法使用本系统"
        return False, "账号已被封禁"
    return True, "ok"
