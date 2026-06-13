"""天梯榜：俱乐部 / 全平台排行、周榜月榜、选手公开信息"""
from datetime import datetime
from typing import Dict, List, Optional, Set

from admin_scope import users_linked_to_venue
from db import find_by_id, load
from db import _current_season_id
from rating import build_leaderboard, get_tier
from venue_service import DEFAULT_VENUE_ID, is_venue_deleted


def _month_key() -> str:
    return _current_season_id()


def _month_score_totals(user_ids: Optional[Set[str]] = None) -> Dict[str, int]:
    """本月积分增加（仅统计正分变动）"""
    prefix = datetime.now().strftime("%Y-%m")
    totals: Dict[str, int] = {}
    for log in load("score_logs"):
        uid = log.get("user_id")
        if not uid:
            continue
        if user_ids is not None and uid not in user_ids:
            continue
        created = (log.get("created_at") or "")[:7]
        if created != prefix:
            continue
        delta = int(log.get("delta") or 0)
        totals[uid] = totals.get(uid, 0) + max(0, delta)
    return totals


def _week_score_totals(user_ids: Optional[Set[str]] = None) -> Dict[str, int]:
    """本周积分增加（与 week_rank 一致，仅统计正分变动）"""
    week_id = datetime.now().strftime("%Y-W%W")
    wr = load("week_rank")
    if wr.get("week_id") != week_id:
        return {}
    scores = wr.get("scores") or {}
    if user_ids is None:
        return dict(scores)
    return {uid: sc for uid, sc in scores.items() if uid in user_ids}


def _rank_positions(scores: Dict[str, int], user_ids: List[str]) -> Dict[str, int]:
    ordered = sorted(
        [(uid, scores.get(uid, 0)) for uid in user_ids],
        key=lambda x: (-x[1], x[0]),
    )
    pos = {}
    r = 0
    last_score = None
    for uid, sc in ordered:
        r += 1
        if last_score is not None and sc == last_score:
            pass
        else:
            last_score = sc
        pos[uid] = r
    return pos


def _user_win_rate(u: Dict) -> float:
    w, l = u.get("wins", 0), u.get("losses", 0)
    total = w + l
    return round(w * 100 / total, 1) if total else 0.0


def _enrich_row(u: Dict, total_rank: int, week_rank: int, month_rank: int, rules) -> Dict:
    tier = get_tier(u.get("score", 1000), rules)
    w, l = u.get("wins", 0), u.get("losses", 0)
    return {
        "rank": total_rank,
        "id": u["id"],
        "nickname": u.get("nickname", "球友"),
        "avatar": u.get("avatar", ""),
        "score": u.get("score", 1000),
        "wins": w,
        "losses": l,
        "total_games": w + l,
        "win_rate": _user_win_rate(u),
        "tier_name": tier["tier_name"],
        "tier_index": tier["tier_index"],
        "star": tier["star"],
        "week_rank": week_rank,
        "month_rank": month_rank,
    }


def _club_member_users(venue_id: str) -> List[Dict]:
    venue_id = venue_id or DEFAULT_VENUE_ID
    linked = users_linked_to_venue(venue_id)
    users = load("users")
    return [
        u for u in users
        if u.get("id") in linked and u.get("status") != "banned" and not u.get("deleted")
    ]


def build_club_leaderboard(
    venue_id: str, limit: int = 50, board: str = "total"
) -> List[Dict]:
    """
    俱乐部天梯
    - week: 本周积分增加排名（不考虑段位）
    - month: 本月积分增加排名（不考虑段位）
    - total: 当前总积分排名
    """
    from ladder_settings import get_effective_ladder_rules

    venue_id = venue_id or DEFAULT_VENUE_ID
    board = (board or "total").lower()
    if board not in ("week", "month", "total"):
        board = "total"

    rules = get_effective_ladder_rules(venue_id)
    club_users = _club_member_users(venue_id)
    linked = {u["id"] for u in club_users}
    users = load("users")

    week_scores = _week_score_totals(linked)
    month_scores = _month_score_totals(linked)

    if board == "week":
        period_scores = week_scores
        sort_key = lambda u: (-period_scores.get(u["id"], 0), u.get("created_at", ""))
    elif board == "month":
        period_scores = month_scores
        sort_key = lambda u: (-period_scores.get(u["id"], 0), u.get("created_at", ""))
    else:
        period_scores = {}
        sort_key = lambda u: (-u.get("score", 1000), u.get("created_at", ""))

    club_users.sort(key=sort_key)

    global_board = build_leaderboard(users, limit=10000, include_hidden=True)
    global_rank_map = {item["id"]: item["rank"] for item in global_board}

    uids = [u["id"] for u in club_users]
    week_pos = _rank_positions(week_scores, uids)
    month_pos = _rank_positions(month_scores, uids)

    result = []
    for i, u in enumerate(club_users[:limit], start=1):
        uid = u["id"]
        global_rank = global_rank_map.get(uid, 9999)
        if board == "week":
            display_rank = week_pos.get(uid, 9999)
        elif board == "month":
            display_rank = month_pos.get(uid, 9999)
        else:
            display_rank = i
        row = _enrich_row(
            u,
            display_rank if board in ("week", "month") else global_rank,
            week_pos.get(uid, 9999),
            month_pos.get(uid, 9999),
            rules,
        )
        row["club_rank"] = i
        row["global_rank"] = global_rank
        row["board"] = board
        row["board_score"] = (
            period_scores.get(uid, 0) if board in ("week", "month") else u.get("score", 1000)
        )
        row["week_score"] = week_scores.get(uid, 0)
        row["month_score"] = month_scores.get(uid, 0)
        if board in ("week", "month"):
            row["rank"] = i
        result.append(row)
    return result


def _user_venue_label(user_id: str) -> str:
    """选手主要所属俱乐部（用于全平台榜展示，不参与排名计算）"""
    names = []
    for v in load("venues"):
        if is_venue_deleted(v):
            continue
        vid = v.get("id", DEFAULT_VENUE_ID)
        if user_id in users_linked_to_venue(vid):
            names.append(v.get("name") or vid)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{names[0]} 等"


def build_global_leaderboard(limit: int = 50) -> List[Dict]:
    """全平台总天梯：所有俱乐部的小程序注册用户按积分统一排名"""
    from ladder_settings import get_ladder_rules

    rules = get_ladder_rules()
    users = load("users")
    board = build_leaderboard(users, limit=limit)

    week_scores = load("week_rank").get("scores") or {}
    month_scores = _month_score_totals()
    uids = [item["id"] for item in board]
    week_pos = _rank_positions(week_scores, uids)
    month_pos = _rank_positions(month_scores, uids)

    result = []
    for item in board:
        u = find_by_id(users, item["id"]) or {}
        row = _enrich_row(
            u,
            item["rank"],
            week_pos.get(item["id"], 9999),
            month_pos.get(item["id"], 9999),
            rules,
        )
        row["venue_name"] = _user_venue_label(item["id"])
        result.append(row)
    return result


def player_public_info(user_id: str) -> Optional[Dict]:
    users = load("users")
    u = find_by_id(users, user_id)
    if not u or u.get("status") == "banned":
        return None
    rules = get_ladder_rules()
    tier = get_tier(u.get("score", 1000), rules)
    rank = next(
        (item["rank"] for item in build_leaderboard(users, limit=10000, include_hidden=True) if item["id"] == user_id),
        9999,
    )
    w, l = u.get("wins", 0), u.get("losses", 0)
    return {
        "id": u["id"],
        "nickname": u.get("nickname", "球友"),
        "avatar": u.get("avatar", ""),
        "score": u.get("score", 1000),
        "wins": w,
        "losses": l,
        "total_games": w + l,
        "win_rate": _user_win_rate(u),
        "rank": rank,
        "tier_name": tier["tier_name"],
        "tier_index": tier["tier_index"],
        "star": tier["star"],
    }
