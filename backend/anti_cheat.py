"""防刷与违规处理"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from config import DEV_MODE, DAILY_SCORE_ALERT, INITIAL_SCORE, MIN_MATCH_SECONDS, SAME_IP_MAX_ACCOUNTS

# 开发/测试环境放宽，便于模拟多账号
DEV_SAME_IP_MAX_ACCOUNTS = 50
from db import load, mutate, now_iso, new_id


def check_ip_limit(ip: str, openid: str) -> Tuple[bool, str]:
    if not ip:
        return True, "ok"
    # 开发模式：放宽 IP 限制，方便测试选手 A/B 及多账号
    if DEV_MODE:
        limit = DEV_SAME_IP_MAX_ACCOUNTS
    else:
        limit = SAME_IP_MAX_ACCOUNTS
    # 固定测试账号始终允许
    if openid in ("dev_test_player_a", "dev_test_player_b"):
        return True, "ok"
    users = load("users")
    same_ip = [u for u in users if u.get("last_ip") == ip and u.get("openid") != openid]
    if len(same_ip) >= limit:
        return False, f"同一IP最多注册{limit}个账号"
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
        elif action == "unban":
            u["status"] = "active"
        u["updated_at"] = now_iso()
        return users

    mutate("users", _fn)
    if action == "reset_score" and u_before:
        from services import log_score

        log_score(user_id, INITIAL_SCORE - old_score, reason, None)
    add_violation(user_id, reason, action, public)
