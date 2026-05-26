"""俱乐部后台：审核记录与重新审核"""
from typing import Any, Dict, List, Optional

from db import find_by_id, load, mutate, new_id, now_iso

TYPE_BONUS_BREAK = "bonus_break"
TYPE_BONUS_CLEAR = "bonus_clear"
TYPE_MATCH_SETTLE = "match_settlement"
TYPE_SHUTOUT = "shutout_finish"

TYPE_LABELS = {
    TYPE_BONUS_BREAK: "炸清加分",
    TYPE_BONUS_CLEAR: "接清加分",
    TYPE_MATCH_SETTLE: "对局结算",
    TYPE_SHUTOUT: "零封结束",
}

RESULT_PENDING = "pending"
RESULT_APPROVED = "approved"
RESULT_REJECTED = "rejected"
RESULT_CHEAT = "cheat"


def _logs() -> List[Dict]:
    return load("review_logs")


def _save_logs(rows: List[Dict]) -> List[Dict]:
    mutate("review_logs", lambda _: rows)
    return rows


def _user_name(user_id: str) -> str:
    u = find_by_id(load("users"), user_id) or {}
    return u.get("nickname") or user_id or "球友"


def append_review_log(
    *,
    venue_id: str,
    match_id: str,
    user_id: str,
    review_type: str,
    ref_id: str,
    result: str,
    auto_approved: bool = False,
    points_delta: int = 0,
    note: str = "",
    admin_by: str = "",
    extra: Optional[Dict] = None,
) -> Dict:
    if not venue_id or not match_id:
        raise ValueError("缺少球房或对局")
    rec = {
        "id": new_id("RL"),
        "venue_id": venue_id,
        "match_id": match_id,
        "user_id": user_id or "",
        "user_name": _user_name(user_id) if user_id else "",
        "type": review_type,
        "type_label": TYPE_LABELS.get(review_type, review_type),
        "ref_id": ref_id or "",
        "result": result,
        "auto_approved": bool(auto_approved),
        "points_delta": int(points_delta or 0),
        "note": (note or "").strip(),
        "admin_by": (admin_by or "").strip(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "history": [
            {
                "result": result,
                "auto_approved": bool(auto_approved),
                "points_delta": int(points_delta or 0),
                "note": (note or "").strip() or ("自动通过审核" if auto_approved else ""),
                "admin_by": (admin_by or "").strip() or ("系统" if auto_approved else ""),
                "at": now_iso(),
            }
        ],
    }
    if extra:
        rec.update(extra)

    def _fn(rows):
        rows.append(rec)
        return rows

    mutate("review_logs", _fn)
    return rec


def update_review_log_result(
    log_id: str,
    result: str,
    *,
    note: str = "",
    admin_by: str = "",
    points_delta: Optional[int] = None,
    auto_approved: Optional[bool] = None,
) -> Dict:
    updated = {}

    def _fn(rows):
        r = find_by_id(rows, log_id)
        if not r:
            raise ValueError("审核记录不存在")
        r["result"] = result
        r["updated_at"] = now_iso()
        if note is not None:
            r["note"] = note
        if admin_by:
            r["admin_by"] = admin_by
        if points_delta is not None:
            r["points_delta"] = int(points_delta)
        if auto_approved is not None:
            r["auto_approved"] = bool(auto_approved)
        hist = r.setdefault("history", [])
        hist.append(
            {
                "result": result,
                "auto_approved": r.get("auto_approved", False),
                "points_delta": r.get("points_delta", 0),
                "note": (note or "").strip(),
                "admin_by": admin_by or "",
                "at": now_iso(),
            }
        )
        updated["log"] = r
        return rows

    mutate("review_logs", _fn)
    return updated["log"]


def list_review_logs(
    venue_id: str,
    *,
    limit: int = 200,
    match_id: str = None,
    user_id: str = None,
) -> List[Dict]:
    rows = _logs()
    out = []
    for r in rows:
        if r.get("venue_id") != venue_id:
            continue
        if match_id and r.get("match_id") != match_id:
            continue
        if user_id and r.get("user_id") != user_id:
            continue
        out.append(public_review_log_view(r))
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out[: max(1, min(limit, 500))]


def public_review_log_view(r: Dict) -> Dict:
    return {
        "id": r.get("id"),
        "venue_id": r.get("venue_id"),
        "match_id": r.get("match_id"),
        "user_id": r.get("user_id"),
        "user_name": r.get("user_name") or _user_name(r.get("user_id", "")),
        "type": r.get("type"),
        "type_label": r.get("type_label") or TYPE_LABELS.get(r.get("type"), ""),
        "ref_id": r.get("ref_id"),
        "result": r.get("result"),
        "result_label": _result_label(r.get("result"), r.get("auto_approved")),
        "auto_approved": bool(r.get("auto_approved")),
        "points_delta": r.get("points_delta", 0),
        "note": r.get("note", ""),
        "admin_by": r.get("admin_by", ""),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "history": r.get("history") or [],
        "can_re_review": r.get("result") in (RESULT_APPROVED, RESULT_REJECTED, RESULT_CHEAT),
    }


def _result_label(result: str, auto_approved: bool) -> str:
    if auto_approved and result == RESULT_APPROVED:
        return "自动通过"
    m = {
        RESULT_PENDING: "待审核",
        RESULT_APPROVED: "已通过",
        RESULT_REJECTED: "已驳回",
        RESULT_CHEAT: "认定作弊",
    }
    return m.get(result, result or "-")


def get_review_log(log_id: str) -> Optional[Dict]:
    r = find_by_id(_logs(), log_id)
    return public_review_log_view(r) if r else None


def resolve_pending_review_log(
    venue_id: str,
    match_id: str,
    ref_id: str,
    new_result: str,
    *,
    note: str = "",
    admin_by: str = "",
    points_delta: Optional[int] = None,
    auto_approved: Optional[bool] = None,
) -> Optional[Dict]:
    """将已有待审记录更新为终态，避免重复写入"""
    if not venue_id or not match_id or not ref_id:
        return None
    for r in reversed(_logs()):
        if (
            r.get("venue_id") == venue_id
            and r.get("match_id") == match_id
            and r.get("ref_id") == ref_id
            and r.get("result") == RESULT_PENDING
        ):
            return update_review_log_result(
                r["id"],
                new_result,
                note=note,
                admin_by=admin_by,
                points_delta=points_delta,
                auto_approved=auto_approved,
            )
    return None


def log_match_settlement_outcome(m: Dict, venue_id: str) -> None:
    """对局结束：待审核结算入记录；零封自动通过入记录"""
    if not m or not venue_id:
        return
    from venue_user_review_service import is_shutout_match, shutout_winner_should_auto

    winner = m.get("winner_id")
    sd = m.get("score_delta") or {}
    w_pts = int(sd.get("winner", 0) if winner else 0)
    l_pts = int(sd.get("loser", 0) if winner else 0)
    pts = w_pts if winner else 0

    if m.get("status") == "pending_review":
        append_review_log(
            venue_id=venue_id,
            match_id=m["id"],
            user_id=winner or m.get("player1_id"),
            review_type=TYPE_MATCH_SETTLE,
            ref_id=m["id"],
            result=RESULT_PENDING,
            auto_approved=False,
            points_delta=pts,
            note=m.get("score_review_reason") or "对局结果待审核",
        )
        return

    if m.get("status") == "finished" and shutout_winner_should_auto(m, venue_id):
        append_review_log(
            venue_id=venue_id,
            match_id=m["id"],
            user_id=winner,
            review_type=TYPE_SHUTOUT,
            ref_id=m["id"],
            result=RESULT_APPROVED,
            auto_approved=True,
            points_delta=pts,
            note="选手已开启自动通过：零封结束",
            extra={"score1": m.get("score1"), "score2": m.get("score2")},
        )


def log_admin_match_settlement_approved(m: Dict, venue_id: str, admin_by: str, note: str = "") -> None:
    if not m or not venue_id:
        return
    winner = m.get("winner_id")
    sd = m.get("score_delta") or {}
    pts = int(sd.get("winner", 0) if winner else 0)
    from venue_user_review_service import is_shutout_match

    rtype = TYPE_SHUTOUT if is_shutout_match(m) else TYPE_MATCH_SETTLE
    resolved = resolve_pending_review_log(
        venue_id,
        m["id"],
        m["id"],
        RESULT_APPROVED,
        note=note or "管理员通过对局结果",
        admin_by=admin_by,
        points_delta=pts,
        auto_approved=False,
    )
    if not resolved:
        append_review_log(
            venue_id=venue_id,
            match_id=m["id"],
            user_id=winner or "",
            review_type=rtype,
            ref_id=m["id"],
            result=RESULT_APPROVED,
            auto_approved=False,
            points_delta=pts,
            note=note or "管理员通过对局结果",
            admin_by=admin_by,
        )


def _reverse_bonus_points(log: Dict, note: str) -> None:
    from services import adjust_user_score

    uid = log.get("user_id")
    delta = int(log.get("points_delta") or 0)
    if uid and delta:
        adjust_user_score(uid, -delta, f"重新审核冲正({note})", log.get("match_id"))


def _apply_bonus_points(log: Dict, delta: int, reason: str) -> None:
    from services import adjust_user_score

    uid = log.get("user_id")
    if uid and delta:
        adjust_user_score(uid, delta, reason, log.get("match_id"))


def re_review_log(
    log_id: str,
    action: str,
    *,
    note: str = "",
    admin_by: str = "",
) -> Dict:
    """重新审核：可改通过/驳回/作弊，并冲正或补发积分（炸清/接清类）"""
    action = (action or "").strip()
    if action not in ("approve", "reject", "cheat"):
        raise ValueError("action 需为 approve / reject / cheat")

    log = find_by_id(_logs(), log_id)
    if not log:
        raise ValueError("审核记录不存在")

    old_result = log.get("result")
    old_delta = int(log.get("points_delta") or 0)
    match_id = log.get("match_id")
    ref_id = log.get("ref_id")
    rtype = log.get("type")

    if old_result == RESULT_APPROVED and old_delta:
        _reverse_bonus_points(log, "重新审核")

    new_result = RESULT_APPROVED if action == "approve" else (
        RESULT_CHEAT if action == "cheat" else RESULT_REJECTED
    )
    new_delta = old_delta

    if rtype in (TYPE_BONUS_BREAK, TYPE_BONUS_CLEAR) and ref_id:
        from match_bonus import approve_bonus_review, punish_bonus_cheat, reject_bonus_review

        if action == "approve":
            approve_bonus_review(
                match_id, ref_id, note or "重新审核通过", write_log=False, admin_by=admin_by
            )
            if not old_delta:
                m = find_by_id(load("matches"), match_id)
                bonus = next((b for b in (m or {}).get("bonuses", []) if b.get("id") == ref_id), None)
                if bonus:
                    from match_bonus import daily_bonus, _match_ladder_rules

                    new_delta = daily_bonus(bonus.get("type"), rules=_match_ladder_rules(m))
        elif action == "cheat":
            punish_bonus_cheat(match_id, log.get("user_id"), ref_id, note or "重新审核认定作弊")
            new_delta = 0
        else:
            reject_bonus_review(match_id, ref_id, note or "重新审核驳回")
            new_delta = 0
    elif rtype in (TYPE_MATCH_SETTLE, TYPE_SHUTOUT):
        m = find_by_id(load("matches"), match_id)
        if not m:
            raise ValueError("对局不存在")
        if action == "approve":
            if m.get("status") == "pending_review" and m.get("pending_settlement"):
                from match_score_review import apply_pending_match_settlement

                apply_pending_match_settlement(match_id, note or "重新审核通过对局")
            elif m.get("status") not in ("finished", "invalid"):
                raise ValueError("对局状态不可结算")
        elif action == "reject":
            if m.get("status") == "pending_review":

                def _rej(ms):
                    mm = find_by_id(ms, match_id)
                    if mm:
                        mm["status"] = "rejected"
                        mm["review_note"] = note or "重新审核驳回"
                        mm["reviewed_at"] = now_iso()
                        mm.pop("pending_settlement", None)
                    return ms

                mutate("matches", _rej)
        else:
            raise ValueError("对局结算类记录不支持认定作弊，请使用驳回")
    else:
        if action == "approve" and new_delta:
            _apply_bonus_points(log, new_delta, f"{log.get('type_label')}(重新审核通过)")

    updated = update_review_log_result(
        log_id,
        new_result,
        note=note,
        admin_by=admin_by,
        points_delta=new_delta,
        auto_approved=False,
    )
    return {"log": updated}
