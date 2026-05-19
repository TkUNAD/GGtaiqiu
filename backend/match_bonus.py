"""对局内炸清/接清：双方确认后加分"""
from typing import Dict, List, Optional, Tuple

from db import find_by_id, load, mutate, new_id, now_iso, save
from ladder_settings import get_ladder_rules
from rating import daily_bonus

BONUS_TYPES = {"break_run", "clearance"}
BONUS_LABELS = {"break_run": "炸清", "clearance": "接清"}


def _players(m: Dict) -> Tuple[str, str]:
    return m["player1_id"], m["player2_id"]


def _other_player(m: Dict, user_id: str) -> Optional[str]:
    p1, p2 = _players(m)
    if user_id == p1:
        return p2
    if user_id == p2:
        return p1
    return None


def request_bonus(match_id: str, user_id: str, bonus_type: str) -> Dict:
    if bonus_type not in BONUS_TYPES:
        raise ValueError("仅支持炸清、接清申报")

    item_holder: Dict = {}

    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m or m["status"] != "playing":
            raise ValueError("对局不存在或已结束")
        if user_id not in _players(m):
            raise ValueError("非本局玩家")

        pending = m.setdefault("bonus_pending", [])
        for p in pending:
            if p.get("status") == "pending" and p.get("type") == bonus_type and p.get("claimer_id") == user_id:
                raise ValueError("已有相同申报待确认")

        item = {
            "id": new_id("BN"),
            "type": bonus_type,
            "claimer_id": user_id,
            "confirmed_by": [],
            "status": "pending",
            "created_at": now_iso(),
        }
        pending.append(item)
        item_holder["item"] = item
        return ms

    mutate("matches", _fn)
    return item_holder["item"]


def confirm_bonus(match_id: str, user_id: str, bonus_id: str = None) -> Dict:
    result_holder: Dict = {}

    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m or m["status"] != "playing":
            raise ValueError("对局不存在或已结束")
        if user_id not in _players(m):
            raise ValueError("非本局玩家")

        pending = m.get("bonus_pending", [])
        item = None
        if bonus_id:
            item = next((p for p in pending if p.get("id") == bonus_id), None)
        else:
            for p in pending:
                if p.get("status") == "pending" and user_id not in p.get("confirmed_by", []):
                    item = p
                    break
        if not item:
            raise ValueError("没有待确认的申报")
        if user_id in item.get("confirmed_by", []):
            raise ValueError("您已确认过")

        item.setdefault("confirmed_by", []).append(user_id)
        p1, p2 = _players(m)
        if p1 in item["confirmed_by"] and p2 in item["confirmed_by"]:
            _apply_bonus(m, item)
            if item.get("status") == "applied":
                item["applied_at"] = now_iso()
            elif item.get("status") == "pending_review":
                item["awaiting_admin_review"] = True

        result_holder["item"] = item
        result_holder["match"] = m
        return ms

    mutate("matches", _fn)
    return {"item": result_holder["item"], "match": result_holder["match"]}


def reject_bonus(match_id: str, user_id: str, bonus_id: str) -> Dict:
    result_holder: Dict = {}

    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m or m["status"] != "playing":
            raise ValueError("对局不存在或已结束")
        if user_id not in _players(m):
            raise ValueError("非本局玩家")

        pending = m.get("bonus_pending", [])
        item = next((p for p in pending if p.get("id") == bonus_id), None)
        if not item or item.get("status") != "pending":
            raise ValueError("没有可拒绝的申报")
        if user_id == item.get("claimer_id"):
            raise ValueError("不能拒绝自己的申报")

        item["status"] = "rejected"
        item["rejected_by"] = user_id
        item["rejected_at"] = now_iso()
        result_holder["item"] = item
        result_holder["match"] = m
        return ms

    mutate("matches", _fn)
    return {"item": result_holder["item"], "match": result_holder["match"]}


def count_match_bonus_events(m: Dict) -> int:
    """本场已生效或待审核的炸清/接清总次数"""
    n = 0
    for b in m.get("bonuses", []):
        if b.get("type") in BONUS_TYPES and b.get("status") in ("applied", "pending_review"):
            n += 1
    return n


def get_bonus_points_by_player(m: Dict) -> Dict[str, int]:
    """各选手因炸清/接清已获得的积分（含待审核不计入，仅 applied）"""
    p1_id, p2_id = _players(m)
    pts = {p1_id: 0, p2_id: 0}
    for b in m.get("bonuses", []):
        if b.get("status") != "applied":
            continue
        uid = b.get("user_id")
        if uid in pts:
            pts[uid] += daily_bonus(b.get("type"))
    return pts


def get_bonus_breakdown_by_player(m: Dict) -> Dict[str, Dict[str, int]]:
    """各选手炸清/接清已生效加分（分左右展示）"""
    p1_id, p2_id = _players(m)
    breakdown = {
        p1_id: {"break_run": 0, "clearance": 0},
        p2_id: {"break_run": 0, "clearance": 0},
    }
    for b in m.get("bonuses", []):
        if b.get("status") != "applied":
            continue
        uid = b.get("user_id")
        t = b.get("type")
        if uid in breakdown and t in BONUS_TYPES:
            breakdown[uid][t] += daily_bonus(t)
    return breakdown


def enrich_match_display(m: Dict) -> Dict:
    """小程序对局页：附带炸清/接清加分显示"""
    p1_id, p2_id = _players(m)
    bp = get_bonus_points_by_player(m)
    bd = get_bonus_breakdown_by_player(m)
    return {
        "p1_bonus_pts": bp.get(p1_id, 0),
        "p2_bonus_pts": bp.get(p2_id, 0),
        "p1_break_pts": bd[p1_id]["break_run"],
        "p1_clear_pts": bd[p1_id]["clearance"],
        "p2_break_pts": bd[p2_id]["break_run"],
        "p2_clear_pts": bd[p2_id]["clearance"],
    }


def _apply_bonus(m: Dict, item: Dict):
    from services import adjust_user_score

    rules = get_ladder_rules()
    threshold = int(rules.get("bonus_review_threshold", 2))
    bonus_type = item["type"]
    claimer = item["claimer_id"]
    pts = daily_bonus(bonus_type)
    existing = count_match_bonus_events(m)
    needs_review = existing >= threshold - 1 and threshold >= 2

    record = {
        "id": item["id"],
        "user_id": claimer,
        "type": bonus_type,
        "at": now_iso(),
    }

    if needs_review:
        record["status"] = "pending_review"
        m.setdefault("bonuses", []).append(record)
        m["needs_bonus_review"] = True
        m.setdefault("bonus_review_queue", []).append({
            "bonus_id": item["id"],
            "user_id": claimer,
            "type": bonus_type,
            "points": pts,
            "label": BONUS_LABELS.get(bonus_type, bonus_type),
            "created_at": now_iso(),
        })
        item["status"] = "pending_review"
    else:
        if pts:
            adjust_user_score(claimer, pts, f"{BONUS_LABELS.get(bonus_type, bonus_type)}(双方确认)", m["id"])
        record["status"] = "applied"
        m.setdefault("bonuses", []).append(record)
        item["status"] = "applied"


def approve_bonus_review(match_id: str, bonus_id: str, note: str = "") -> Dict:
    from services import adjust_user_score

    holder: Dict = {}

    def _approve_fn(ms):
        m = find_by_id(ms, match_id)
        if not m:
            raise ValueError("对局不存在")
        bonus = next((b for b in m.get("bonuses", []) if b.get("id") == bonus_id), None)
        if not bonus or bonus.get("status") != "pending_review":
            raise ValueError("无待审核的加分项")
        holder["bonus"] = bonus
        holder["user_id"] = bonus["user_id"]
        holder["bonus_type"] = bonus["type"]
        bonus["status"] = "applied"
        bonus["review_note"] = note
        bonus["reviewed_at"] = now_iso()
        queue = m.get("bonus_review_queue", [])
        m["bonus_review_queue"] = [q for q in queue if q.get("bonus_id") != bonus_id]
        if not m["bonus_review_queue"]:
            m["needs_bonus_review"] = False
        return ms

    mutate("matches", _approve_fn)
    pts = daily_bonus(holder.get("bonus_type", ""))
    if pts and holder.get("user_id"):
        adjust_user_score(
            holder["user_id"],
            pts,
            f"{BONUS_LABELS.get(holder['bonus_type'], holder['bonus_type'])}(审核通过)",
            match_id,
        )
    m = find_by_id(load("matches"), match_id)
    return {"match": m, "bonus": holder.get("bonus")}


def reject_bonus_review(match_id: str, bonus_id: str, note: str = "") -> Dict:
    def _reject_fn(ms):
        m = find_by_id(ms, match_id)
        if not m:
            raise ValueError("对局不存在")
        bonus = next((b for b in m.get("bonuses", []) if b.get("id") == bonus_id), None)
        if not bonus or bonus.get("status") != "pending_review":
            raise ValueError("无待审核的加分项")
        bonus["status"] = "review_rejected"
        bonus["review_note"] = note
        bonus["reviewed_at"] = now_iso()
        queue = m.get("bonus_review_queue", [])
        m["bonus_review_queue"] = [q for q in queue if q.get("bonus_id") != bonus_id]
        if not m["bonus_review_queue"]:
            m["needs_bonus_review"] = False
        return ms

    mutate("matches", _reject_fn)
    m = find_by_id(load("matches"), match_id)
    bonus = next((b for b in m.get("bonuses", []) if b.get("id") == bonus_id), None)
    return {"match": m, "bonus": bonus}


def punish_bonus_cheat(match_id: str, user_id: str, bonus_id: str, reason: str = "") -> Dict:
    """作弊：扣积分并大屏滚动公示"""
    from anti_cheat import add_violation, publish_cheat_announcement
    from services import adjust_user_score

    rules = get_ladder_rules()
    penalty = int(rules.get("cheat_penalty_points", 200))
    scroll_times = int(rules.get("cheat_scroll_times", 3))
    holder: Dict = {}

    def _cheat_fn(ms):
        m = find_by_id(ms, match_id)
        if not m:
            raise ValueError("对局不存在")
        if user_id not in (m.get("player1_id"), m.get("player2_id")):
            raise ValueError("只能处罚本局选手")
        bonus = next((b for b in m.get("bonuses", []) if b.get("id") == bonus_id), None)
        holder["bonus"] = bonus
        if bonus and bonus.get("status") == "pending_review":
            bonus["status"] = "cheat_rejected"
            bonus["reviewed_at"] = now_iso()
            queue = m.get("bonus_review_queue", [])
            m["bonus_review_queue"] = [q for q in queue if q.get("bonus_id") != bonus_id]
            if not m.get("bonus_review_queue"):
                m["needs_bonus_review"] = False
        return ms

    mutate("matches", _cheat_fn)

    users = load("users")
    u = find_by_id(users, user_id) or {}
    nickname = u.get("nickname", "球友")
    label = BONUS_LABELS.get((holder.get("bonus") or {}).get("type"), "炸清/接清")
    msg = reason or f"{nickname} 在本场对局虚报{label}，扣除{penalty}积分"

    adjust_user_score(user_id, -penalty, f"炸清/接清作弊处罚(-{penalty})", match_id)
    add_violation(user_id, msg, "cheat_penalty", True)
    publish_cheat_announcement(nickname, msg, scroll_times)
    m = find_by_id(load("matches"), match_id)
    return {"match": m, "penalty": penalty, "scroll_times": scroll_times}


def get_pending_for_user(m: Dict, user_id: str) -> List[Dict]:
    result = []
    users = load("users")
    for p in m.get("bonus_pending", []):
        if p.get("status") != "pending":
            continue
        confirmed = p.get("confirmed_by", [])
        if user_id in confirmed:
            continue
        claimer = find_by_id(users, p.get("claimer_id")) or {}
        p_copy = dict(p)
        p_copy["claimer_name"] = claimer.get("nickname", "球友")
        p_copy["my_role"] = "claimer" if user_id == p.get("claimer_id") else "confirmer"
        p_copy["confirmed_count"] = len(confirmed)
        p_copy["needs_opponent_popup"] = p_copy["my_role"] == "confirmer"
        result.append(p_copy)
    return result


def count_applied_bonuses(m: Dict, user_id: str) -> Dict:
    counts = {"break_run": 0, "clearance": 0}
    for b in m.get("bonuses", []):
        if b.get("user_id") == user_id and b.get("status") in ("applied", "pending_review"):
            t = b.get("type")
            if t in counts:
                counts[t] += 1
    return counts


def enrich_match_for_admin(m: Dict) -> Dict:
    """管理后台：对局列表附带球员比分与积分变动"""
    users = load("users")
    p1 = find_by_id(users, m.get("player1_id")) or {}
    p2 = find_by_id(users, m.get("player2_id")) or {}
    sd = m.get("score_delta") or {}
    w_id = m.get("winner_id")
    p1_id, p2_id = m["player1_id"], m["player2_id"]

    def delta_for(uid):
        if m.get("status") == "invalid":
            return 0
        if uid == w_id:
            return sd.get("winner", 0)
        if w_id and uid != w_id:
            return sd.get("loser", 0)
        return 0

    c1 = count_applied_bonuses(m, p1_id)
    c2 = count_applied_bonuses(m, p2_id)
    total_bonus = count_match_bonus_events(m)
    review_alert = ""
    if m.get("needs_bonus_review") or total_bonus >= int(get_ladder_rules().get("bonus_review_threshold", 2)):
        review_alert = f"⚠ 本场炸清/接清已达{total_bonus}次，待审核加分"

    return {
        **m,
        "p1_name": p1.get("nickname", "球友"),
        "p2_name": p2.get("nickname", "球友"),
        "p1_current_score": p1.get("score", 1000),
        "p2_current_score": p2.get("score", 1000),
        "p1_point_delta": delta_for(p1_id),
        "p2_point_delta": delta_for(p2_id),
        "p1_break_run": c1["break_run"],
        "p1_clearance": c1["clearance"],
        "p2_break_run": c2["break_run"],
        "p2_clearance": c2["clearance"],
        "bonus_review_alert": review_alert,
        "bonus_review_queue": m.get("bonus_review_queue", []),
    }


def build_match_summary(m: Dict) -> Dict:
    users = load("users")
    p1 = find_by_id(users, m["player1_id"]) or {}
    p2 = find_by_id(users, m["player2_id"]) or {}
    sd = m.get("score_delta") or {}
    w_id = m.get("winner_id")
    p1_id, p2_id = m["player1_id"], m["player2_id"]

    def delta_for(uid):
        if m.get("status") == "invalid":
            return 0
        if uid == w_id:
            return sd.get("winner", 0)
        if w_id and uid != w_id:
            return sd.get("loser", 0)
        return 0

    def player_summary(u, uid):
        c = count_applied_bonuses(m, uid)
        return {
            "id": uid,
            "nickname": u.get("nickname", "球友"),
            "avatar": u.get("avatar", ""),
            "score": u.get("score", 1000),
            "frames_won": m["score1"] if uid == p1_id else m["score2"],
            "point_delta": delta_for(uid),
            "break_run": c["break_run"],
            "clearance": c["clearance"],
            "is_winner": uid == w_id,
        }

    return {
        "match_id": m["id"],
        "table_id": m.get("table_id"),
        "race_to": m.get("race_to"),
        "match_type": m.get("match_type"),
        "status": m.get("status"),
        "score1": m.get("score1", 0),
        "score2": m.get("score2", 0),
        "completed": m.get("completed", True),
        "half_points": m.get("half_points", False),
        "invalid_reason": m.get("invalid_reason"),
        "player1": player_summary(p1, p1_id),
        "player2": player_summary(p2, p2_id),
    }
