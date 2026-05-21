"""对局闲置检测：10 分钟无操作提醒，继续需双方确认，结束需对方同意或超时自动结算"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from config import (
    MATCH_END_REQUEST_SECONDS,
    MATCH_IDLE_ALERT_SECONDS,
    MATCH_IDLE_PROMPT_SECONDS,
)
from db import find_by_id, load, mutate, now_iso


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        return None


def seconds_until(deadline_iso: str) -> int:
    end = _parse_iso(deadline_iso)
    if not end:
        return 0
    return max(0, int((end - datetime.now()).total_seconds()))


def touch_match_activity(m: Dict) -> None:
    """任意有效操作后刷新活跃时间并清除闲置状态"""
    m["last_activity_at"] = now_iso()
    if m.get("idle_state"):
        m.pop("idle_state", None)


def _winner_from_scores(m: Dict) -> Tuple[Optional[str], bool]:
    s1, s2 = int(m.get("score1", 0)), int(m.get("score2", 0))
    race = int(m.get("race_to", 5))
    completed = s1 >= race or s2 >= race
    if s1 == s2:
        return None, completed
    if s1 > s2:
        return m["player1_id"], completed
    return m["player2_id"], completed


def _mark_auto_finish(m: Dict, reason: str) -> None:
    m["_idle_should_finish"] = True
    m["idle_finish_reason"] = reason


def _process_idle_on_match(m: Dict) -> bool:
    """在对局对象上推进闲置状态，返回是否有字段变更"""
    now = datetime.now()
    state = m.get("idle_state")
    changed = False

    if state:
        phase = state.get("phase")
        if phase == "prompt":
            deadline = state.get("deadline_at", "")
            if seconds_until(deadline) <= 0:
                _mark_auto_finish(m, "长时间无操作，提醒超时系统自动结束")
                return True
            return False

        if phase == "end_pending":
            end_req = state.get("end_request") or {}
            resp = end_req.get("opponent_response")
            if resp == "agree":
                _mark_auto_finish(m, "双方同意结束对局")
                return True
            if resp == "reject":
                m.pop("idle_state", None)
                touch_match_activity(m)
                return True
            deadline = end_req.get("deadline_at", "")
            if seconds_until(deadline) <= 0 and not resp:
                _mark_auto_finish(m, "对方未响应结束请求，系统自动结束")
                return True
            return False

    last = m.get("last_activity_at") or m.get("started_at")
    last_dt = _parse_iso(last)
    if not last_dt:
        m["last_activity_at"] = now_iso()
        return True
    idle_sec = (now - last_dt).total_seconds()
    if idle_sec >= MATCH_IDLE_ALERT_SECONDS:
        m["idle_state"] = {
            "phase": "prompt",
            "started_at": now_iso(),
            "deadline_at": (now + timedelta(seconds=MATCH_IDLE_PROMPT_SECONDS)).isoformat(),
            "continue_confirm": {},
            "end_request": None,
        }
        changed = True
    return changed


def process_idle_match(match_id: str) -> Dict:
    """检查闲置/超时，必要时自动结束对局。返回最新对局对象。"""
    holder: Dict[str, Any] = {}

    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m:
            holder["missing"] = True
            return ms
        if m.get("status") != "playing":
            holder["m"] = m
            return ms
        _process_idle_on_match(m)
        holder["m"] = m
        holder["finish"] = bool(m.get("_idle_should_finish"))
        holder["reason"] = m.get("idle_finish_reason", "")
        if holder["finish"]:
            m.pop("_idle_should_finish", None)
            m.pop("idle_finish_reason", None)
        return ms

    mutate("matches", _fn)
    if holder.get("missing"):
        raise ValueError("对局不存在")
    if holder.get("finish"):
        from services import auto_finish_idle_match

        return auto_finish_idle_match(match_id, holder.get("reason", ""))
    return holder["m"]


def build_idle_ui(m: Dict, user_id: str) -> Dict:
    state = m.get("idle_state")
    if not state or m.get("status") != "playing":
        return {"active": False}

    p1, p2 = m.get("player1_id"), m.get("player2_id")
    opponent = p2 if user_id == p1 else p1
    confirms = state.get("continue_confirm") or {}
    my_continue = bool(confirms.get(user_id))
    opp_continue = bool(confirms.get(opponent))

    ui: Dict[str, Any] = {
        "active": True,
        "phase": state.get("phase", "prompt"),
        "seconds_left": seconds_until(state.get("deadline_at", "")),
        "my_continue_confirmed": my_continue,
        "opponent_continue_confirmed": opp_continue,
        "both_continue_ready": my_continue and opp_continue,
        "show_continue_btn": True,
        "show_end_btn": True,
        "need_my_continue": not my_continue,
        "need_my_end_response": False,
        "end_requested_by_me": False,
        "end_requested_by_opponent": False,
        "end_seconds_left": 0,
    }

    end_req = state.get("end_request")
    if end_req:
        ui["phase"] = "end_pending"
        ui["show_continue_btn"] = False
        ui["show_end_btn"] = False
        req_uid = end_req.get("user_id")
        ui["end_requested_by_me"] = req_uid == user_id
        ui["end_requested_by_opponent"] = req_uid != user_id
        ui["end_seconds_left"] = seconds_until(end_req.get("deadline_at", ""))
        ui["need_my_end_response"] = (
            req_uid != user_id and not end_req.get("opponent_response")
        )
        ui["opponent_response"] = end_req.get("opponent_response")
    return ui


def idle_confirm_continue(match_id: str, user_id: str) -> Dict:
    both_ready = False

    def _fn(ms):
        nonlocal both_ready
        m = find_by_id(ms, match_id)
        if not m or m.get("status") != "playing":
            raise ValueError("对局不存在或已结束")
        if user_id not in (m.get("player1_id"), m.get("player2_id")):
            raise ValueError("非本局选手")
        state = m.get("idle_state")
        if not state or state.get("phase") != "prompt":
            raise ValueError("当前无需确认继续比赛")
        if state.get("end_request"):
            raise ValueError("已发起结束请求，请等待对方响应")
        confirms = state.setdefault("continue_confirm", {})
        confirms[user_id] = True
        p1, p2 = m["player1_id"], m["player2_id"]
        if confirms.get(p1) and confirms.get(p2):
            both_ready = True
            m.pop("idle_state", None)
            touch_match_activity(m)
        return ms

    mutate("matches", _fn)
    result = process_idle_match(match_id)
    return {"match": result, "both_confirmed": both_ready, "resumed": both_ready}


def idle_request_end(match_id: str, user_id: str) -> Dict:
    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m or m.get("status") != "playing":
            raise ValueError("对局不存在或已结束")
        if user_id not in (m.get("player1_id"), m.get("player2_id")):
            raise ValueError("非本局选手")
        state = m.get("idle_state")
        if not state or state.get("phase") != "prompt":
            raise ValueError("请先等待系统闲置提醒后再选择结束比赛")
        now = datetime.now()
        state["phase"] = "end_pending"
        state["end_request"] = {
            "user_id": user_id,
            "requested_at": now_iso(),
            "deadline_at": (now + timedelta(seconds=MATCH_END_REQUEST_SECONDS)).isoformat(),
            "opponent_response": None,
        }
        m["idle_state"] = state
        return ms

    mutate("matches", _fn)
    result = process_idle_match(match_id)
    return {"match": result}


def idle_respond_end(match_id: str, user_id: str, agree: bool) -> Dict:
    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m or m.get("status") != "playing":
            raise ValueError("对局不存在或已结束")
        state = m.get("idle_state")
        if not state or state.get("phase") != "end_pending":
            raise ValueError("当前无待处理的结束请求")
        end_req = state.get("end_request") or {}
        if end_req.get("user_id") == user_id:
            raise ValueError("请由对方确认是否结束")
        if user_id not in (m.get("player1_id"), m.get("player2_id")):
            raise ValueError("非本局选手")
        end_req["opponent_response"] = "agree" if agree else "reject"
        state["end_request"] = end_req
        if agree:
            _mark_auto_finish(m, "对方同意结束对局")
        return ms

    mutate("matches", _fn)
    result = process_idle_match(match_id)
    return {"match": result, "agreed": agree}
