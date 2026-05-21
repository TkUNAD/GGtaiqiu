"""用户/后台：对局与积分明细格式化"""
from typing import Dict, List, Optional

from db import find_by_id, load
from match_labels import match_status_label, match_type_label


def _point_delta_for_user(m: Dict, user_id: str) -> int:
    if m.get("status") == "invalid":
        return 0
    sd = m.get("score_delta") or {}
    w_id = m.get("winner_id")
    p1, p2 = m.get("player1_id"), m.get("player2_id")
    if not w_id:
        return 0
    if user_id == w_id:
        return sd.get("winner", 0)
    if user_id in (p1, p2):
        return sd.get("loser", 0)
    return 0


def format_user_match(m: Dict, user_id: str, users: List[Dict], tables: List[Dict]) -> Dict:
    p1, p2 = m.get("player1_id"), m.get("player2_id")
    is_p1 = user_id == p1
    opp_id = p2 if is_p1 else p1
    opp = find_by_id(users, opp_id) or {}
    my_frames = m.get("score1", 0) if is_p1 else m.get("score2", 0)
    opp_frames = m.get("score2", 0) if is_p1 else m.get("score1", 0)
    table = find_by_id(tables, m.get("table_id")) or {}
    w_id = m.get("winner_id")
    result = "平局"
    if w_id == user_id:
        result = "胜"
    elif w_id and w_id in (p1, p2):
        result = "负"

    return {
        "id": m.get("id"),
        "table_id": m.get("table_id"),
        "table_name": table.get("name", m.get("table_id", "")),
        "match_type": m.get("match_type"),
        "match_type_label": match_type_label(m.get("match_type")),
        "status": m.get("status"),
        "status_label": match_status_label(m.get("status")),
        "race_to": m.get("race_to"),
        "score1": m.get("score1", 0),
        "score2": m.get("score2", 0),
        "my_frames": my_frames,
        "opp_frames": opp_frames,
        "score_text": f"{my_frames}:{opp_frames}",
        "opponent_id": opp_id,
        "opponent_name": opp.get("nickname", "球友"),
        "result": result,
        "point_delta": _point_delta_for_user(m, user_id),
        "started_at": m.get("started_at"),
        "ended_at": m.get("ended_at"),
        "is_winner": w_id == user_id,
    }


def format_user_score_log(
    log: Dict, user_id: str, users: List[Dict], matches: List[Dict], tables: List[Dict]
) -> Dict:
    m = find_by_id(matches, log.get("match_id")) if log.get("match_id") else None
    match_snippet = None
    if m:
        fm = format_user_match(m, user_id, users, tables)
        match_snippet = {
            "id": m.get("id"),
            "score_text": fm["score_text"],
            "status_label": fm["status_label"],
            "opponent_name": fm["opponent_name"],
        }
    return {
        **log,
        "match_snippet": match_snippet,
        "created_at_short": (log.get("created_at") or "")[:19].replace("T", " "),
    }


def get_user_matches_list(user_id: str, limit: int = 20) -> List[Dict]:
    users = load("users")
    tables = load("tables")
    matches = [m for m in load("matches") if user_id in (m.get("player1_id"), m.get("player2_id"))]
    matches.sort(key=lambda x: x.get("ended_at") or x.get("started_at") or "", reverse=True)
    return [format_user_match(m, user_id, users, tables) for m in matches[:limit]]


def get_user_score_logs_list(user_id: str, limit: int = 20) -> List[Dict]:
    users = load("users")
    matches = load("matches")
    tables = load("tables")
    logs = [l for l in load("score_logs") if l.get("user_id") == user_id]
    logs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return [format_user_score_log(l, user_id, users, matches, tables) for l in logs[:limit]]


def format_admin_score_detail(log: Dict, users: List[Dict], matches: List[Dict]) -> Dict:
    u = find_by_id(users, log.get("user_id")) or {}
    m = find_by_id(matches, log.get("match_id")) if log.get("match_id") else None
    match_info = ""
    if m:
        p1 = find_by_id(users, m.get("player1_id")) or {}
        p2 = find_by_id(users, m.get("player2_id")) or {}
        match_info = (
            f"{match_type_label(m.get('match_type'))} "
            f"{p1.get('nickname', '?')} {m.get('score1', 0)}:{m.get('score2', 0)} "
            f"{p2.get('nickname', '?')} ({match_status_label(m.get('status'))})"
        )
    return {
        **log,
        "nickname": u.get("nickname", ""),
        "match_info": match_info,
        "created_at_short": (log.get("created_at") or "")[:19].replace("T", " "),
    }
