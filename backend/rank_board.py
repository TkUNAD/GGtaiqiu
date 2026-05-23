"""天梯榜：俱乐部 / 全平台排行、周榜月榜、选手公开信息"""
from datetime import datetime
from typing import Dict, List, Optional, Set

from admin_scope import users_linked_to_venue
from db import find_by_id, load
from db import _current_season_id
from rating import build_leaderboard, get_tier
from venue_service import DEFAULT_VENUE_ID


def _month_key() -> str:
    return _current_season_id()


def _month_score_totals(user_ids: Optional[Set[str]] = None) -> Dict[str, int]:
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


def build_club_leaderboard(venue_id: str, limit: int = 50) -> List[Dict]:
    from ladder_settings import get_effective_ladder_rules

    venue_id = venue_id or DEFAULT_VENUE_ID
    rules = get_effective_ladder_rules(venue_id)
    linked = users_linked_to_venue(venue_id)
    users = load("users")
    club_users = [
        u for u in users
        if u.get("id") in linked and u.get("status") != "banned" and not u.get("deleted")
    ]
    club_users.sort(key=lambda x: (-x.get("score", 1000), x.get("created_at", "")))

    global_board = build_leaderboard(users, limit=10000, include_hidden=True)
    global_rank_map = {item["id"]: item["rank"] for item in global_board}

    week_scores = load("week_rank").get("scores") or {}
    month_scores = _month_score_totals(linked)
    uids = [u["id"] for u in club_users]
    week_pos = _rank_positions(week_scores, uids)
    month_pos = _rank_positions(month_scores, uids)

    result = []
    for i, u in enumerate(club_users[:limit], start=1):
        uid = u["id"]
        row = _enrich_row(
            u,
            global_rank_map.get(uid, 9999),
            week_pos.get(uid, 9999),
            month_pos.get(uid, 9999),
            rules,
        )
        row["club_rank"] = i
        result.append(row)
    return result


def build_global_leaderboard(limit: int = 50) -> List[Dict]:
    from ladder_settings import get_ladder_rules

    rules = get_ladder_rules()
    users = load("users")
    board = build_leaderboard(users, limit=limit)
    linked_all: Set[str] = set()
    for v in load("venues"):
        linked_all |= users_linked_to_venue(v.get("id", DEFAULT_VENUE_ID))

    week_scores = load("week_rank").get("scores") or {}
    month_scores = _month_score_totals()
    uids = [item["id"] for item in board]
    week_pos = _rank_positions(week_scores, uids)
    month_pos = _rank_positions(month_scores, uids)

    result = []
    for item in board:
        u = find_by_id(users, item["id"]) or {}
        if item["id"] not in linked_all:
            continue
        result.append(
            _enrich_row(
                u,
                item["rank"],
                week_pos.get(item["id"], 9999),
                month_pos.get(item["id"], 9999),
                rules,
            )
        )
        if len(result) >= limit:
            break
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
