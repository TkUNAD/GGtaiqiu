"""段位、积分、赛季规则（六段位积分从 ladder_settings 读取）"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from config import HIDE_RANK_DAYS, INACTIVE_DAYS_START, INACTIVE_PENALTY_PER_DAY, INITIAL_SCORE
from ladder_settings import default_tier_definitions, get_daily_bonus_map, get_ladder_rules


def _tier_list(rules: Optional[Dict] = None) -> List[Dict]:
    if rules and rules.get("tier_definitions"):
        return rules["tier_definitions"]
    return default_tier_definitions()


def get_tier(score: int, rules: Optional[Dict] = None) -> Dict:
    tiers = _tier_list(rules)
    for idx, tier in enumerate(tiers):
        if tier["min"] <= score <= tier["max"]:
            span = tier["max"] - tier["min"] + 1
            if tier["max"] >= 99999:
                star = 5
            else:
                pos = score - tier["min"]
                star = min(5, max(1, int(pos / (span / 5)) + 1))
            return {
                "tier_name": tier["name"],
                "tier_index": idx + 1,
                "star": star,
                "min": tier["min"],
                "max": tier["max"],
            }
    first = tiers[0] if tiers else {"name": "新锐学徒", "min": 1000, "max": 1199}
    return {
        "tier_name": first["name"],
        "tier_index": 1,
        "star": 1,
        "min": first["min"],
        "max": first["max"],
    }


def get_tier_index(score: int, rules: Optional[Dict] = None) -> int:
    return get_tier(score, rules)["tier_index"]


def tier_gap(score_a: int, score_b: int, rules: Optional[Dict] = None) -> int:
    return abs(get_tier_index(score_a, rules) - get_tier_index(score_b, rules))


def can_ranked_by_tier(
    user_a: Dict,
    user_b: Dict,
    rules: Optional[Dict] = None,
) -> Tuple[bool, str]:
    rules = rules or get_ladder_rules()
    pr = rules.get("point_rules") or {}
    max_gap = int(pr.get("max_ranked_tier_gap", 1))
    gap = tier_gap(user_a.get("score", INITIAL_SCORE), user_b.get("score", INITIAL_SCORE), rules)
    if gap > max_gap:
        return False, f"段位相差{gap}级（超过{max_gap}级），本场为休闲赛"
    return True, "ok"


def tier_match_point_deltas(
    winner_id: str,
    loser_id: str,
    player1_id: str,
    score1: int,
    score2: int,
    winner_user: Dict,
    loser_user: Dict,
    rules: Optional[Dict] = None,
    half_points: bool = False,
) -> Tuple[int, int]:
    """按六段位与局分差（score1/score2）计算排位加减分"""
    rules = rules or get_ladder_rules()
    pr = rules.get("point_rules") or {}

    if winner_id == player1_id:
        w_frames, l_frames = int(score1), int(score2)
    else:
        w_frames, l_frames = int(score2), int(score1)
    frame_diff = max(0, w_frames - l_frames)

    w_tier = get_tier_index(winner_user.get("score", INITIAL_SCORE), rules)
    l_tier = get_tier_index(loser_user.get("score", INITIAL_SCORE), rules)
    tier_gap_val = abs(w_tier - l_tier)

    if tier_gap_val >= 2:
        bonus = int(pr.get("casual_winner_bonus", 5))
        return bonus, 0

    if tier_gap_val == 0:
        w_delta = int(pr.get("same_winner_base", 20)) + frame_diff * int(
            pr.get("same_winner_per_frame", 2)
        )
        l_delta = -(
            int(pr.get("same_loser_base", 15))
            + frame_diff * int(pr.get("same_loser_per_frame", 2))
        )
    elif w_tier > l_tier:
        w_delta = int(pr.get("high_win_winner_base", 15)) + frame_diff * int(
            pr.get("high_win_winner_per_frame", 2)
        )
        l_delta = -(
            int(pr.get("high_win_loser_base", 10))
            + frame_diff * int(pr.get("high_win_loser_per_frame", 2))
        )
    else:
        w_delta = int(pr.get("low_win_winner_base", 25)) + frame_diff * int(
            pr.get("low_win_winner_per_frame", 3)
        )
        l_delta = -(
            int(pr.get("low_win_loser_base", 15))
            + frame_diff * int(pr.get("low_win_loser_per_frame", 3))
        )

    if half_points:
        w_delta = w_delta // 2
        l_delta = l_delta // 2
    return w_delta, l_delta


def ranked_point_delta(
    winner_score: int,
    loser_score: int,
    is_winner: bool,
    rules: Optional[Dict] = None,
) -> int:
    """兼容旧接口：无局分时按同段位、局分差0估算"""
    rules = rules or get_ladder_rules()
    fake_w = {"score": winner_score}
    fake_l = {"score": loser_score}
    w_d, l_d = tier_match_point_deltas(
        "w",
        "l",
        "w",
        0,
        0,
        fake_w,
        fake_l,
        rules=rules,
        half_points=False,
    )
    return w_d if is_winner else l_d


def daily_bonus(bonus_type: str, rules: Optional[Dict] = None) -> int:
    return get_daily_bonus_map(rules).get(bonus_type, 0)


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


def can_challenge_rank(
    challenger_rank: int,
    target_rank: int,
    rules: Optional[Dict] = None,
) -> Tuple[bool, str]:
    rules = rules or get_ladder_rules()
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


def ranked_quota_ok(user: Dict, rules: Optional[Dict] = None) -> Tuple[bool, str]:
    rules = rules or get_ladder_rules()
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


def dec_ranked_quota(user: Dict):
    """无效/取消排位局时退回已扣次数（不低于 0）"""
    today = datetime.now().strftime("%Y-%m-%d")
    week = datetime.now().strftime("%Y-W%W")
    daily = user.setdefault("daily_ranked_count", {})
    weekly = user.setdefault("weekly_ranked_count", {})
    if daily.get("date") == today and daily.get("count", 0) > 0:
        daily["count"] = daily.get("count", 0) - 1
    if weekly.get("week") == week and weekly.get("count", 0) > 0:
        weekly["count"] = weekly.get("count", 0) - 1


def build_leaderboard(users: List[Dict], limit: int = 100, include_hidden: bool = False) -> List[Dict]:
    rules = get_ladder_rules()
    active = [u for u in users if u.get("status") != "banned" and not u.get("deleted")]
    active.sort(key=lambda x: (-x.get("score", INITIAL_SCORE), x.get("created_at", "")))
    result = []
    rank = 0
    for u in active:
        if should_hide_rank(u) and not include_hidden:
            continue
        rank += 1
        tier = get_tier(u.get("score", INITIAL_SCORE), rules)
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
