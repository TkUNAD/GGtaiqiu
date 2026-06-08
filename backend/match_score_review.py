"""对局内快速操作审核：60 秒内多次炸清/接清/胜/负触发积分冻结，待后台审核后结算"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config import (
    REVIEW_AUTO_APPROVE_HOURS,
    SCORE_REVIEW_ACTION_THRESHOLD,
    SCORE_REVIEW_WINDOW_SEC,
)
from db import find_by_id, load, mutate, mutate_multi, now_iso

TRACKED_ACTIONS = frozenset({"win", "lose", "break_run", "clearance"})


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


def note_match_score_action(m: Dict, user_id: str, action_kind: str) -> None:
    """记录一次可触发审核的操作，并在 60 秒内达到阈值时冻结积分变动"""
    if action_kind not in TRACKED_ACTIONS:
        return
    log = m.setdefault("score_action_log", [])
    log.append({"kind": action_kind, "user_id": user_id, "at": now_iso()})
    window_start = datetime.now() - timedelta(seconds=SCORE_REVIEW_WINDOW_SEC)
    recent: List[Dict] = []
    for entry in log:
        t = _parse_iso(entry.get("at"))
        if t and t >= window_start:
            recent.append(entry)
    m["score_action_log"] = recent[-40:]
    if len(recent) >= SCORE_REVIEW_ACTION_THRESHOLD:
        m["score_review_hold"] = True
        m.setdefault("score_review_since", now_iso())
        m["score_review_reason"] = (
            f"{SCORE_REVIEW_WINDOW_SEC}秒内快速操作{len(recent)}次，待后台审核结算"
        )


def match_blocks_score_update(match_id: str = None, m: Dict = None) -> bool:
    """对局处于积分冻结时不应直接改分"""
    item = m
    if item is None and match_id:
        item = find_by_id(load("matches"), match_id)
    if not item:
        return False
    if item.get("score_review_hold"):
        return True
    if item.get("status") == "pending_review":
        return True
    return False


def defer_match_score(
    m: Dict, user_id: str, delta: int, reason: str
) -> None:
    """积分冻结期间暂存待审核加分"""
    if not delta:
        return
    m.setdefault("deferred_scores", []).append({
        "user_id": user_id,
        "delta": delta,
        "reason": reason,
        "at": now_iso(),
    })


def match_should_defer_settlement(m: Dict) -> bool:
    from venue_user_review_service import match_venue_id_from_match, shutout_winner_should_auto

    if shutout_winner_should_auto(m, match_venue_id_from_match(m)):
        return False
    if m.get("score_review_hold"):
        return True
    if m.get("needs_bonus_review"):
        return True
    for b in m.get("bonuses") or []:
        if b.get("status") == "pending_review":
            return True
    return False


def match_review_notice(m: Dict) -> str:
    """小程序结算页：待审核说明"""
    parts = []
    if m.get("needs_bonus_review") or any(
        b.get("status") == "pending_review" for b in (m.get("bonuses") or [])
    ):
        n = sum(1 for b in (m.get("bonuses") or []) if b.get("status") == "pending_review")
        parts.append(f"本场有{n or 1}项炸清/接清待后台审核，积分暂未入账")
    if m.get("score_review_hold"):
        parts.append(m.get("score_review_reason") or "快速操作待审核，天梯积分暂未结算")
    if m.get("status") == "pending_review" and not parts:
        parts.append("本场对局待后台审核后结算积分")
    return "；".join(parts)


def build_pending_settlement(
    m: Dict,
    *,
    winner_id: Optional[str],
    loser_id: Optional[str],
    is_draw: bool,
    is_ranked: bool,
    w_delta: int,
    l_delta: int,
    casual_bonus: int,
    completed: bool,
) -> Dict[str, Any]:
    return {
        "winner_id": winner_id,
        "loser_id": loser_id,
        "is_draw": is_draw,
        "is_ranked": is_ranked,
        "w_delta": w_delta,
        "l_delta": l_delta,
        "casual_bonus": casual_bonus,
        "completed": completed,
        "half_points": bool(m.get("half_points")),
        "deferred_scores": list(m.get("deferred_scores") or []),
        "computed_at": now_iso(),
    }


def apply_pending_match_settlement(match_id: str, note: str = "") -> Dict:
    """审核通过：写入 pending_settlement 中的积分与胜负统计"""
    from services import _apply_finish_user_updates_inplace, _append_score_log_inplace
    from match_bonus import build_match_summary
    from config import INITIAL_SCORE

    holder: Dict[str, Any] = {"alerts": []}

    def _atomic(matches, users, score_logs, week_rank):
        m = find_by_id(matches, match_id)
        if not m:
            raise ValueError("对局不存在")
        if m.get("status") != "pending_review":
            raise ValueError("对局不在待审核状态")
        ps = m.get("pending_settlement")
        if not ps:
            raise ValueError("无待结算数据")

        # 合并对局级暂存加分（审核炸清/接清时写入）到待结算包
        ps_def = list(ps.get("deferred_scores") or [])
        seen = {
            (row.get("user_id"), int(row.get("delta") or 0), row.get("reason") or "")
            for row in ps_def
        }
        for row in m.get("deferred_scores") or []:
            key = (row.get("user_id"), int(row.get("delta") or 0), row.get("reason") or "")
            if key not in seen and key[0] and key[1]:
                ps_def.append(row)
                seen.add(key)
        ps["deferred_scores"] = ps_def

        m["status"] = "finished"
        m["review_note"] = note
        m["reviewed_at"] = now_iso()
        m.pop("score_review_hold", None)
        m.pop("score_review_reason", None)

        winner_id = ps.get("winner_id")
        loser_id = ps.get("loser_id")
        is_draw = bool(ps.get("is_draw"))
        is_ranked = bool(ps.get("is_ranked"))
        w_delta = int(ps.get("w_delta") or 0)
        l_delta = int(ps.get("l_delta") or 0)
        casual_bonus = int(ps.get("casual_bonus") or 0)

        if is_draw:
            holder["alerts"] = _apply_finish_user_updates_inplace(
                users,
                score_logs,
                week_rank,
                m.get("player1_id"),
                m.get("player2_id"),
                match_id,
                False,
                0,
                0,
                0,
                True,
                ranked_quota_consumed=bool(m.get("ranked_quota_consumed")),
            )
        else:
            holder["alerts"] = _apply_finish_user_updates_inplace(
                users,
                score_logs,
                week_rank,
                winner_id,
                loser_id,
                match_id,
                is_ranked,
                w_delta,
                l_delta,
                casual_bonus,
                False,
                ranked_quota_consumed=bool(m.get("ranked_quota_consumed")),
            )

        for row in ps.get("deferred_scores") or []:
            uid = row.get("user_id")
            delta = int(row.get("delta") or 0)
            if not uid or not delta:
                continue
            u = find_by_id(users, uid)
            if not u:
                continue
            u["score"] = max(0, u.get("score", INITIAL_SCORE) + delta)
            u["updated_at"] = now_iso()
            _append_score_log_inplace(
                score_logs, uid, delta, row.get("reason") or "审核补发", match_id
            )
            from services import _update_week_score_inplace

            _update_week_score_inplace(week_rank, uid, delta)
            holder["alerts"].append((uid, max(0, delta)))

        m.pop("pending_settlement", None)
        m.pop("deferred_scores", None)
        m.pop("score_review_hold", None)
        m.pop("needs_bonus_review", None)
        m["bonus_review_queue"] = []
        for bp in m.get("bonus_pending") or []:
            if bp.get("status") == "pending_review":
                bp["status"] = "applied"
        m["summary"] = build_match_summary(m)
        holder["m"] = m
        return matches

    mutate_multi(["matches", "users", "score_logs", "week_rank"], _atomic)
    from services import check_daily_score_alert
    from anti_cheat import add_violation

    for uid, delta in holder.get("alerts") or []:
        alert = check_daily_score_alert(uid, delta)
        if alert:
            add_violation(uid, alert, "warn", False)
    return holder.get("m") or find_by_id(load("matches"), match_id) or {}


def process_stale_admin_reviews() -> None:
    """24 小时未审核的炸清/接清、对局结算、兑换自动通过"""
    from match_bonus import approve_bonus_review

    cutoff = datetime.now() - timedelta(hours=REVIEW_AUTO_APPROVE_HOURS)
    auto_note = f"{REVIEW_AUTO_APPROVE_HOURS}小时未审核，系统自动通过"

    matches = load("matches")
    for m in matches:
        mid = m.get("id")
        if not mid:
            continue
        for q in list(m.get("bonus_review_queue") or []):
            created = _parse_iso(q.get("created_at"))
            if created and created < cutoff:
                try:
                    approve_bonus_review(mid, q.get("bonus_id"), auto_note)
                except ValueError:
                    pass

    for m in load("matches"):
        if m.get("status") != "pending_review":
            continue
        since = _parse_iso(m.get("score_review_since") or m.get("ended_at"))
        if not since or since >= cutoff:
            continue
        try:
            if m.get("pending_settlement"):
                apply_pending_match_settlement(m["id"], auto_note)
            else:
                from services import finish_match

                s1, s2 = m.get("score1", 0), m.get("score2", 0)
                if s1 == s2:
                    continue
                winner_id = m.get("winner_id") or (
                    m["player1_id"] if s1 > s2 else m["player2_id"]
                )
                finish_match(m["id"], winner_id, completed=m.get("completed", True))
        except ValueError:
            pass

    def _auto_exchanges(exs):
        changed = False
        for e in exs:
            if e.get("status") != "pending":
                continue
            created = _parse_iso(e.get("created_at"))
            if not created or created >= cutoff:
                continue
            e["status"] = "approved"
            e["review_note"] = auto_note
            e["reviewed_at"] = now_iso()
            changed = True
        return exs if changed else exs

    mutate("exchanges", _auto_exchanges)
