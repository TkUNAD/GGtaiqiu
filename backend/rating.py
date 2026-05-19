"""段位、积分、赛季规则（排位规则从 ladder_settings 读取）"""
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from config import HIDE_RANK_DAYS, INACTIVE_DAYS_START, INACTIVE_PENALTY_PER_DAY, INITIAL_SCORE, RANK_TIERS
from ladder_settings import get_daily_bonus_map, get_ladder_rules


def get_tier(score: int) -> Dict:
    for tier in RANK_TIERS:
        if tier["min"] <= score <= tier["max"]:
            span = tier["max"] - tier["min"] + 1
            if tier["max"] >= 99999:
                star = 5
            else:
                pos = score - tier["min"]
                star = min(5, max(1, int(pos / (span / 5)) + 1))
            return {
                "tier_name": tier["name"],
                "tier_index": RANK_TIERS.index(tier) + 1,
                "star": star,
                "min": tier["min"],
                "max": tier["max"],
            }
    return {"tier_name": "新锐学徒", "tier_index": 1, "star": 1, "min": 1000, "max": 1199}


def ranked_point_delta(winner_score: int, loser_score: int, is_winner: bool) -> int:
    diff = winner_score - loser_score
    if is_winner:
        if diff >= 100:
            return random.randint(35, 50)
        if abs(diff) < 50:
            return random.randint(25, 30)
        return random.randint(10, 15)
    else:
        if diff >= 100:
            return 0
        if abs(diff) < 50:
            return -random.randint(15, 20)
        return -random.randint(25, 30)


def daily_bonus(bonus_type: str) -> int:
    return get_daily_bonus_map().get(bonus_type, 0)


def apply_inactive_penalty(user: Dict) -> int:
    last_battle = user.get("last_battle_at")
    if not last_battle:
        return 0
    try:
        last = datetime.fromisoformat(last_battle)
    except ValueError:
        return 0
    days = (datetime.now() - last).days
    if days < INACTIVE_DAYS_START:
        return 0
    penalty_days = days - INACTIVE_DAYS_START + 1
    return penalty_days * INACTIVE_PENALTY_PER_DAY


def should_hide_rank(user: Dict) -> bool:
    last_login = user.get("last_login_at")
    if not last_login:
        return False
    try:
        last = datetime.fromisoformat(last_login)
    except ValueError:
        return False
    return (datetime.now() - last).days >= HIDE_RANK_DAYS


def can_challenge_rank(challenger_rank: int, target_rank: int) -> Tuple[bool, str]:
    rules = get_ladder_rules()
    rmin = rules["challenge_rank_min"]
    rmax = rules["challenge_rank_max"]

    if target_rank >= challenger_rank:
        return False, "只能挑战比自己排名高的玩家"
    gap = challenger_rank - target_rank
    if gap < rmin:
        return False, f"只能挑战高{rmin}~{rmax}名的玩家"
    if gap > rmax:
        if rules.get("beyond_rank_daily_bonus_only", True):
            return False, f"超出{rmax}名，仅计日常加分不计排位分"
        return False, f"只能挑战高{rmin}~{rmax}名的玩家"
    return True, "ok"


def ranked_quota_ok(user: Dict) -> Tuple[bool, str]:
    rules = get_ladder_rules()
    daily_limit = rules["daily_ranked_limit"]
    weekly_limit = rules["weekly_ranked_limit"]

    today = datetime.now().strftime("%Y-%m-%d")
    week = datetime.now().strftime("%Y-W%W")
    daily = user.get("daily_ranked_count", {})
    weekly = user.get("weekly_ranked_count", {})
    if daily.get("date") == today and daily.get("count", 0) >= daily_limit:
        return False, f"今日排位已达上限({daily_limit}场)"
    if weekly.get("week") == week and weekly.get("count", 0) >= weekly_limit:
        return False, f"本周排位已达上限({weekly_limit}场)"
    return True, "ok"


def inc_ranked_quota(user: Dict):
    today = datetime.now().strftime("%Y-%m-%d")
    week = datetime.now().strftime("%Y-W%W")
    daily = user.setdefault("daily_ranked_count", {})
    weekly = user.setdefault("weekly_ranked_count", {})
    if daily.get("date") != today:
        daily["date"] = today
        daily["count"] = 0
    if weekly.get("week") != week:
        weekly["week"] = week
        weekly["count"] = 0
    daily["count"] = daily.get("count", 0) + 1
    weekly["week"] = week
    weekly["count"] = weekly.get("count", 0) + 1


def build_leaderboard(users: List[Dict], limit: int = 100, include_hidden: bool = False) -> List[Dict]:
    active = [u for u in users if u.get("status") != "banned" and not u.get("deleted")]
    active.sort(key=lambda x: (-x.get("score", INITIAL_SCORE), x.get("created_at", "")))
    result = []
    rank = 0
    for u in active:
        if should_hide_rank(u) and not include_hidden:
            continue
        rank += 1
        tier = get_tier(u.get("score", INITIAL_SCORE))
        result.append({
            "rank": rank,
            "id": u["id"],
            "nickname": u.get("nickname", "球友"),
            "avatar": u.get("avatar", ""),
            "score": u.get("score", INITIAL_SCORE),
            "wins": u.get("wins", 0),
            "losses": u.get("losses", 0),
            "tier_name": tier["tier_name"],
            "star": tier["star"],
            "hidden": should_hide_rank(u),
        })
        if len(result) >= limit:
            break
    return result


def get_user_rank(users: List[Dict], user_id: str) -> int:
    board = build_leaderboard(users, limit=10000, include_hidden=True)
    for item in board:
        if item["id"] == user_id:
            return item["rank"]
    return 9999
