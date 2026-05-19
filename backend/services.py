"""业务服务层"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from anti_cheat import (
    add_violation,
    check_daily_score_alert,
    check_ip_limit,
    check_phone_unique,
    match_duration_valid,
    punish_user,
)
from config import (
    DEV_MODE,
    EXCHANGE_DAILY_LIMIT,
    EXCHANGE_MIN_SCORE,
    INITIAL_SCORE,
    WECHAT_APPID,
    WECHAT_SECRET,
    WIN_LOSE_COOLDOWN,
)
from db import find_by_id, load, mutate, new_id, now_iso, save
from ladder_settings import get_ladder_rules
from rating import (
    apply_inactive_penalty,
    build_leaderboard,
    can_challenge_rank,
    daily_bonus,
    get_tier,
    get_user_rank,
    inc_ranked_quota,
    ranked_point_delta,
    ranked_quota_ok,
    should_hide_rank,
)


def wx_code_to_openid(code: str) -> Tuple[Optional[str], Optional[str]]:
    # 测试账号固定 code，仅开发模式可用
    if code.startswith("test_player_"):
        if not DEV_MODE:
            return None, "测试入口已关闭"
        return f"dev_{code}", None
    if not WECHAT_APPID or not WECHAT_SECRET:
        if DEV_MODE:
            return f"dev_{code}", None
        return None, "未配置微信小程序 AppID/Secret，无法完成微信登录"
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": WECHAT_APPID,
        "secret": WECHAT_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if "openid" in data:
            return data["openid"], data.get("session_key")
        return None, data.get("errmsg", "微信登录失败")
    except Exception as e:
        return None, str(e)


def log_score(user_id: str, delta: int, reason: str, match_id: str = None):
    def _fn(logs):
        logs.append({
            "id": new_id("L"),
            "user_id": user_id,
            "delta": delta,
            "reason": reason,
            "match_id": match_id,
            "created_at": now_iso(),
        })
        if len(logs) > 50000:
            logs[:] = logs[-40000:]
        return logs

    mutate("score_logs", _fn)
    alert = check_daily_score_alert(user_id, max(0, delta))
    if alert:
        add_violation(user_id, alert, "warn", False)


def adjust_user_score(user_id: str, delta: int, reason: str, match_id: str = None):
    users = load("users")
    if not find_by_id(users, user_id):
        return

    def _fn(us):
        u = find_by_id(us, user_id)
        if not u:
            return us
        u["score"] = max(0, u.get("score", INITIAL_SCORE) + delta)
        u["updated_at"] = now_iso()
        return us

    mutate("users", _fn)
    log_score(user_id, delta, reason, match_id)
    _update_week_score(user_id, delta)


def _update_week_score(user_id: str, delta: int):
    week_id = datetime.now().strftime("%Y-W%W")

    def _fn(wr):
        if wr.get("week_id") != week_id:
            wr["week_id"] = week_id
            wr["scores"] = {}
        wr["scores"][user_id] = wr["scores"].get(user_id, 0) + max(0, delta)
        return wr

    mutate("week_rank", _fn)


def delete_users(user_ids: List[str]) -> Dict:
    """管理后台删除玩家（进行中对局不可删）"""
    ids = list({uid for uid in (user_ids or []) if uid})
    if not ids:
        raise ValueError("请选择要删除的玩家")

    users = load("users")
    existing = {u["id"] for u in users}
    missing = [uid for uid in ids if uid not in existing]
    if missing:
        raise ValueError("玩家不存在: " + ", ".join(missing[:5]))

    id_set = set(ids)
    matches = load("matches")
    for m in matches:
        if m.get("status") != "playing":
            continue
        if m.get("player1_id") in id_set or m.get("player2_id") in id_set:
            raise ValueError("所选玩家有进行中的对局，请先结束对局后再删除")

    def _users(us):
        return [u for u in us if u.get("id") not in id_set]

    mutate("users", _users)

    def _tables(ts):
        for t in ts:
            waiting = t.get("waiting_players") or []
            if waiting:
                t["waiting_players"] = [w for w in waiting if w.get("user_id") not in id_set]
        return ts

    mutate("tables", _tables)

    def _wr(wr):
        scores = wr.get("scores") or {}
        for uid in id_set:
            scores.pop(uid, None)
        wr["scores"] = scores
        return wr

    mutate("week_rank", _wr)

    cancel_pending_exchanges_for_users(id_set, "玩家已删除，兑换取消")

    return {"deleted": len(ids), "user_ids": ids}


def delete_matches(
    match_ids: List[str],
    venue_id: Optional[str] = None,
    is_super: bool = True,
) -> Dict:
    """管理后台删除对局记录，并释放关联桌台、清理相关积分日志"""
    from venue_service import DEFAULT_VENUE_ID

    ids = list({mid for mid in (match_ids or []) if mid})
    if not ids:
        raise ValueError("请选择要删除的对局")

    matches = load("matches")
    id_set = set(ids)
    to_delete = [m for m in matches if m.get("id") in id_set]
    if len(to_delete) != len(ids):
        missing = id_set - {m["id"] for m in to_delete}
        raise ValueError("对局不存在: " + ", ".join(list(missing)[:3]))

    if not is_super and venue_id:
        tables = load("tables")
        for m in to_delete:
            t = find_by_id(tables, m.get("table_id"))
            if t and t.get("venue_id", DEFAULT_VENUE_ID) != venue_id:
                raise ValueError("无权删除其他球房的对局")

    def _matches(ms):
        return [m for m in ms if m.get("id") not in id_set]

    mutate("matches", _matches)

    def _tables(ts):
        for t in ts:
            if t.get("current_match_id") in id_set:
                t["current_match_id"] = None
                t["waiting_players"] = []
                t["opened"] = False
                t["opened_at"] = None
                t.pop("opened_by_scan", None)
        return ts

    mutate("tables", _tables)

    def _logs(logs):
        return [l for l in logs if l.get("match_id") not in id_set]

    mutate("score_logs", _logs)

    return {"deleted": len(ids), "match_ids": ids}


def delete_exchanges(exchange_ids: List[str]) -> Dict:
    """总后台删除兑换记录；待审核的将退回积分"""
    ids = list({eid for eid in (exchange_ids or []) if eid})
    if not ids:
        raise ValueError("请选择要删除的兑换记录")

    exchanges = load("exchanges")
    id_set = set(ids)
    existing = {e["id"] for e in exchanges}
    missing = id_set - existing
    if missing:
        raise ValueError("兑换记录不存在: " + ", ".join(list(missing)[:3]))

    for ex in exchanges:
        if ex.get("id") in id_set and ex.get("status") == "pending":
            refund_exchange(ex["id"], "管理员删除记录")

    def _fn(exs):
        return [e for e in exs if e.get("id") not in id_set]

    mutate("exchanges", _fn)
    return {"deleted": len(ids), "exchange_ids": ids}


def delete_score_logs(log_ids: List[str]) -> Dict:
    """总后台删除积分日志"""
    ids = list({lid for lid in (log_ids or []) if lid})
    if not ids:
        raise ValueError("请选择要删除的日志")

    logs = load("score_logs")
    id_set = set(ids)
    existing = {l.get("id") for l in logs if l.get("id")}
    missing = id_set - existing
    if missing:
        raise ValueError("日志不存在: " + ", ".join(list(missing)[:3]))

    def _fn(logs):
        return [l for l in logs if l.get("id") not in id_set]

    mutate("score_logs", _fn)
    return {"deleted": len(ids), "log_ids": ids}


def reset_system_data(confirm_username: str, confirm_password: str) -> Dict:
    """总后台：验证账号密码后重置全部业务数据（保留球房、商品、天梯规则配置）"""
    import config
    from db import _current_season_id, _current_week_id, _default_data
    from venue_service import authenticate_venue

    username = (confirm_username or "").strip()
    password = confirm_password or ""
    if not username or not password:
        raise ValueError("请输入管理员账号和密码")

    if username != config.ADMIN_USER or password != config.ADMIN_PASS:
        if authenticate_venue(username, password):
            raise ValueError("仅总管理员账号可执行全量数据重置")
        raise ValueError("账号或密码错误")

    settings = load("settings")
    ladder_rules = (settings or {}).get("ladder_rules")
    venues = load("venues")
    products = load("products")

    save("users", [])
    save("matches", [])
    save("exchanges", [])
    save("score_logs", [])
    save("violations", [])

    tables = _default_data("tables")
    for t in tables:
        t["waiting_players"] = []
        t["opened"] = False
        t["current_match_id"] = None
    save("tables", tables)

    save("week_rank", {"week_id": _current_week_id(), "scores": {}})
    save("season", {"current": _current_season_id(), "started_at": now_iso()})

    new_settings = _default_data("settings")
    if ladder_rules:
        new_settings["ladder_rules"] = ladder_rules
    save("settings", new_settings)
    save("venues", venues)
    save("products", products)

    return {"reset": True, "scope": "all", "message": "全部数据已重置"}


def reset_venue_data(venue_id: str, confirm_username: str, confirm_password: str) -> Dict:
    """球房后台：验证本球房账号密码后，仅重置该球房相关数据"""
    from venue_service import DEFAULT_VENUE_ID, authenticate_venue, get_venue

    username = (confirm_username or "").strip()
    password = confirm_password or ""
    if not username or not password:
        raise ValueError("请输入球房登录账号和密码")

    venue = authenticate_venue(username, password)
    if not venue or venue.get("id") != venue_id:
        raise ValueError("账号或密码错误，或非本球房账号")

    vinfo = get_venue(venue_id) or venue
    venue_name = vinfo.get("name", "本球房")

    table_ids = {
        t["id"]
        for t in load("tables")
        if t.get("venue_id", DEFAULT_VENUE_ID) == venue_id
    }
    if not table_ids:
        raise ValueError("该球房暂无桌台数据")

    matches = load("matches")
    remove_match_ids = {m["id"] for m in matches if m.get("table_id") in table_ids}
    affected_users = set()
    for m in matches:
        if m.get("id") in remove_match_ids:
            if m.get("player1_id"):
                affected_users.add(m["player1_id"])
            if m.get("player2_id"):
                affected_users.add(m["player2_id"])

    for t in load("tables"):
        if t.get("id") in table_ids:
            for w in t.get("waiting_players") or []:
                uid = w.get("user_id")
                if uid:
                    affected_users.add(uid)

    remaining = [m for m in matches if m.get("id") not in remove_match_ids]
    users_with_other_matches = set()
    for m in remaining:
        if m.get("player1_id"):
            users_with_other_matches.add(m["player1_id"])
        if m.get("player2_id"):
            users_with_other_matches.add(m["player2_id"])

    def _matches(ms):
        return [m for m in ms if m.get("id") not in remove_match_ids]

    mutate("matches", _matches)

    def _tables(ts):
        for t in ts:
            if t.get("id") in table_ids:
                t["waiting_players"] = []
                t["opened"] = False
                t["opened_at"] = None
                t["current_match_id"] = None
        return ts

    mutate("tables", _tables)

    def _logs(logs):
        return [l for l in logs if l.get("match_id") not in remove_match_ids]

    mutate("score_logs", _logs)

    delete_user_ids = {uid for uid in affected_users if uid not in users_with_other_matches}

    def _users(us):
        kept = []
        for u in us:
            uid = u.get("id")
            if uid in delete_user_ids:
                continue
            if uid in affected_users:
                u["score"] = INITIAL_SCORE
                u["wins"] = 0
                u["losses"] = 0
                u["updated_at"] = now_iso()
            kept.append(u)
        return kept

    mutate("users", _users)

    def _wr(wr):
        scores = wr.get("scores") or {}
        for uid in delete_user_ids | affected_users:
            scores.pop(uid, None)
        wr["scores"] = scores
        return wr

    mutate("week_rank", _wr)

    cancel_pending_exchanges_for_users(
        affected_users | delete_user_ids,
        "球房数据重置，兑换取消",
    )

    def _ex(exs):
        return [ex for ex in exs if ex.get("user_id") not in delete_user_ids]

    mutate("exchanges", _ex)

    def _violations(vs):
        return [v for v in vs if v.get("user_id") not in delete_user_ids]

    mutate("violations", _violations)

    return {
        "reset": True,
        "scope": "venue",
        "venue_id": venue_id,
        "venue_name": venue_name,
        "matches_removed": len(remove_match_ids),
        "users_removed": len(delete_user_ids),
        "message": f"球房「{venue_name}」数据已重置",
    }


def admin_reset_data(
    role: str,
    venue_id: Optional[str],
    confirm_username: str,
    confirm_password: str,
) -> Dict:
    """管理后台重置：总后台全量；球房仅本球房范围"""
    if role == "super":
        return reset_system_data(confirm_username, confirm_password)
    if not venue_id:
        raise ValueError("未识别球房，请重新登录")
    return reset_venue_data(venue_id, confirm_username, confirm_password)


def get_or_create_user(openid: str, nickname: str = "", avatar: str = "", phone: str = "", ip: str = "") -> Dict:
    holder: Dict[str, Any] = {}

    def _update_existing(us):
        for u in us:
            if u.get("openid") != openid:
                continue
            u["last_login_at"] = now_iso()
            if nickname:
                u["nickname"] = nickname
            if avatar:
                u["avatar"] = avatar
            if phone:
                ok2, msg2 = check_phone_unique(phone, u["id"])
                if not ok2:
                    raise ValueError(msg2)
                u["phone"] = phone
            if ip:
                u["last_ip"] = ip
            penalty = apply_inactive_penalty(u)
            if penalty > 0:
                u["score"] = max(0, u.get("score", INITIAL_SCORE) - penalty)
                log_score(u["id"], -penalty, "长期未对战扣分")
            holder["user"] = u
            return us
        return us

    mutate("users", _update_existing)
    if holder.get("user"):
        return holder["user"]

    ok, msg = check_ip_limit(ip, openid)
    if not ok:
        raise ValueError(msg)

    if phone:
        ok2, msg2 = check_phone_unique(phone)
        if not ok2:
            raise ValueError(msg2)

    user = {
        "id": new_id("U"),
        "openid": openid,
        "nickname": nickname or f"球友{openid[-4:]}",
        "avatar": avatar or "",
        "phone": phone or "",
        "score": INITIAL_SCORE,
        "wins": 0,
        "losses": 0,
        "status": "active",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "last_login_at": now_iso(),
        "last_battle_at": None,
        "last_ip": ip,
        "daily_ranked_count": {},
        "weekly_ranked_count": {},
        "open_table_hours": 0,
    }

    def _create(us):
        for u in us:
            if u.get("openid") == openid:
                holder["user"] = u
                return us
        us.append(user)
        holder["user"] = user
        return us

    mutate("users", _create)
    return holder["user"]


def process_season_and_week():
    now = datetime.now()
    season_id = f"{now.year}{now.month:02d}"
    week_id = now.strftime("%Y-W%W")

    season = load("season")
    if season.get("current") != season_id:
        season["current"] = season_id
        season["started_at"] = now_iso()
        save("season", season)

    wr = load("week_rank")
    if wr.get("week_id") != week_id:
        wr = {"week_id": week_id, "scores": {}}
        save("week_rank", wr)


def resolve_match_type(
    table: Dict,
    player1_id: str,
    player2_id: str,
    challenger_id: str = None,
    target_id: str = None,
) -> Tuple[str, str]:
    """根据天梯规则自动判定排位赛或休闲局"""
    if not table.get("opened"):
        return "casual", "桌台未开台，本场为休闲局"

    users = load("users")
    p1 = find_by_id(users, player1_id)
    p2 = find_by_id(users, player2_id)
    rules = get_ladder_rules()

    for p, _pid in ((p1, player1_id), (p2, player2_id)):
        ok, msg = ranked_quota_ok(p)
        if not ok:
            if rules.get("ranked_over_limit_to_casual", True):
                return "casual", msg
            raise ValueError(msg)

    if challenger_id and target_id:
        cr = get_user_rank(users, challenger_id)
        tr = get_user_rank(users, target_id)
        ok, msg = can_challenge_rank(cr, tr)
        if ok:
            return "ranked", "挑战符合天梯规则，自动排位赛"
        return "casual", msg

    r1 = get_user_rank(users, player1_id)
    r2 = get_user_rank(users, player2_id)
    if r1 == r2:
        return "casual", "双方排名相同，本场为休闲局"
    ch_rank, tg_rank = (r1, r2) if r1 > r2 else (r2, r1)
    ok, msg = can_challenge_rank(ch_rank, tg_rank)
    if ok:
        return "ranked", "符合天梯挑战规则，自动排位赛"
    return "casual", msg or "不符合天梯规则，本场为休闲局"


def start_match(
    table_id: str,
    player1_id: str,
    player2_id: str,
    race_to: int,
    match_type: str = "casual",
    challenger_id: str = None,
    target_id: str = None,
    ranked_reason_hint: str = "",
) -> Dict:
    if player1_id == player2_id:
        raise ValueError("禁止虚拟对战")

    table = find_by_id(load("tables"), table_id)
    if not table:
        raise ValueError("桌台不存在")

    users = load("users")
    p1 = find_by_id(users, player1_id)
    p2 = find_by_id(users, player2_id)
    if not p1 or not p2:
        raise ValueError("玩家不存在")
    if p1.get("status") == "banned" or p2.get("status") == "banned":
        raise ValueError("账号已封禁")

    is_ranked = match_type == "ranked"
    if is_ranked and not table.get("opened"):
        is_ranked = False
        match_type = "casual"

    ranked_valid = True
    ranked_reason = ranked_reason_hint or ""

    rules = get_ladder_rules()
    if is_ranked:
        ok, msg = ranked_quota_ok(p1)
        if not ok:
            if rules.get("ranked_over_limit_to_casual", True):
                is_ranked = False
                ranked_valid = False
                ranked_reason = msg
            else:
                raise ValueError(msg)
        else:
            ok2, msg2 = ranked_quota_ok(p2)
            if not ok2:
                if rules.get("ranked_over_limit_to_casual", True):
                    is_ranked = False
                    ranked_valid = False
                    ranked_reason = msg2
                else:
                    raise ValueError(msg2)

    if is_ranked and challenger_id and target_id:
        users_list = load("users")
        cr = get_user_rank(users_list, challenger_id)
        tr = get_user_rank(users_list, target_id)
        ok3, msg3 = can_challenge_rank(cr, tr)
        if not ok3:
            if "超出" in msg3 and "日常加分" in msg3:
                is_ranked = False
                ranked_valid = False
                ranked_reason = msg3
            else:
                raise ValueError(msg3)

    match = {
        "id": new_id("M"),
        "table_id": table_id,
        "player1_id": player1_id,
        "player2_id": player2_id,
        "race_to": race_to,
        "score1": 0,
        "score2": 0,
        "match_type": "ranked" if is_ranked else "casual",
        "original_type": match_type,
        "ranked_valid": ranked_valid,
        "ranked_reason": ranked_reason,
        "challenger_id": challenger_id,
        "target_id": target_id,
        "status": "playing",
        "started_at": now_iso(),
        "ended_at": None,
        "winner_id": None,
        "completed": False,
        "half_points": False,
        "last_action_at": {},
        "bonuses": [],
        "bonus_pending": [],
    }

    def _matches(ms):
        for m in ms:
            if (
                m.get("table_id") == table_id
                and m.get("status") == "playing"
            ):
                raise ValueError("该桌台已有进行中的对局")
        ms.append(match)
        return ms

    try:
        mutate("matches", _matches)

        def _tables(ts):
            t = find_by_id(ts, table_id)
            if not t:
                raise ValueError("桌台不存在")
            if t.get("current_match_id"):
                mid = t["current_match_id"]
                existing = find_by_id(load("matches"), mid)
                if existing and existing.get("status") == "playing":
                    raise ValueError("该桌台已有进行中的对局")
            t["current_match_id"] = match["id"]
            t["waiting_players"] = []
            return ts

        mutate("tables", _tables)
    except ValueError:
        def _rollback(ms):
            return [m for m in ms if m.get("id") != match["id"]]

        mutate("matches", _rollback)
        raise

    return match


def record_frame(match_id: str, user_id: str, action: str) -> Dict:
    """action: win | lose"""
    finish_holder: Dict[str, Any] = {}

    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m or m["status"] != "playing":
            raise ValueError("对局不存在或已结束")

        now = datetime.now()
        last = m.setdefault("last_action_at", {})
        key = f"{user_id}_{action}"
        if key in last:
            try:
                prev = datetime.fromisoformat(last[key])
            except ValueError:
                prev = None
            if prev is not None and (now - prev).total_seconds() < WIN_LOSE_COOLDOWN:
                raise ValueError(f"请等待{WIN_LOSE_COOLDOWN}秒后再操作")

        if action == "win":
            if user_id == m["player1_id"]:
                m["score1"] += 1
            elif user_id == m["player2_id"]:
                m["score2"] += 1
            else:
                raise ValueError("非本局玩家")
            last[f"{user_id}_win"] = now_iso()
        elif action == "lose":
            if user_id == m["player1_id"]:
                m["score2"] += 1
            elif user_id == m["player2_id"]:
                m["score1"] += 1
            else:
                raise ValueError("非本局玩家")
            last[f"{user_id}_lose"] = now_iso()
        else:
            raise ValueError("无效操作")

        race = m["race_to"]
        if m["score1"] >= race or m["score2"] >= race:
            finish_holder["winner"] = (
                m["player1_id"] if m["score1"] >= race else m["player2_id"]
            )
            finish_holder["finish"] = True
        return ms

    mutate("matches", _fn)

    if finish_holder.get("finish"):
        return finish_match(match_id, finish_holder["winner"], completed=True)
    return find_by_id(load("matches"), match_id) or {}


def _apply_finish_user_updates(
    winner_id: Optional[str],
    loser_id: Optional[str],
    match_id: str,
    is_ranked: bool,
    w_delta: int,
    l_delta: int,
    casual_winner_bonus: int,
    is_draw: bool,
):
    """单次 mutate 持久化：积分、排位配额、胜/负场"""

    def _users(us):
        if is_draw:
            for uid in (winner_id, loser_id):
                if not uid:
                    continue
                u = find_by_id(us, uid)
                if u:
                    u["last_battle_at"] = now_iso()
                    u["updated_at"] = now_iso()
            return us
        uw = find_by_id(us, winner_id)
        ul = find_by_id(us, loser_id)
        if not uw or not ul:
            return us
        if is_ranked:
            inc_ranked_quota(uw)
            inc_ranked_quota(ul)
            uw["score"] = max(0, uw.get("score", INITIAL_SCORE) + w_delta)
            ul["score"] = max(0, ul.get("score", INITIAL_SCORE) + l_delta)
        else:
            uw["score"] = max(0, uw.get("score", INITIAL_SCORE) + casual_winner_bonus)
        uw["wins"] = uw.get("wins", 0) + 1
        ul["losses"] = ul.get("losses", 0) + 1
        battle_at = now_iso()
        uw["last_battle_at"] = battle_at
        ul["last_battle_at"] = battle_at
        uw["updated_at"] = battle_at
        ul["updated_at"] = battle_at
        return us

    mutate("users", _users)

    if is_draw:
        return
    if is_ranked:
        log_score(winner_id, w_delta, "排位胜利", match_id)
        if l_delta:
            log_score(loser_id, l_delta, "排位失败", match_id)
        _update_week_score(winner_id, w_delta)
        if l_delta:
            _update_week_score(loser_id, l_delta)
    else:
        log_score(winner_id, casual_winner_bonus, "休闲对局有效局", match_id)
        if casual_winner_bonus:
            _update_week_score(winner_id, casual_winner_bonus)


def finish_match(match_id: str, winner_id: str = None, completed: bool = True) -> Dict:
    from match_bonus import build_match_summary

    outcome: Dict[str, Any] = {}

    def _finish_matches(ms):
        m = find_by_id(ms, match_id)
        if not m:
            raise ValueError("对局不存在")
        if m["status"] in ("finished", "invalid", "cancelled"):
            outcome["m"] = m
            outcome["skip"] = True
            return ms
        if m["status"] != "playing":
            raise ValueError("对局状态不可结算")

        p1, p2 = m["player1_id"], m["player2_id"]
        if m.get("score1", 0) == m.get("score2", 0):
            if winner_id:
                raise ValueError("比分相同，无法判定胜负")
            is_draw = True
        else:
            is_draw = False
            if winner_id not in (p1, p2):
                raise ValueError("胜者必须是本局选手之一")
            loser_id = p2 if winner_id == p1 else p1

        if not match_duration_valid(m["started_at"]):
            m["status"] = "invalid"
            m["ended_at"] = now_iso()
            m["invalid_reason"] = "对局时长过短，判定无效"
            m["summary"] = build_match_summary(m)
            outcome["m"] = m
            outcome["release_table"] = m.get("table_id")
            outcome["skip"] = True
            return ms

        m["winner_id"] = winner_id
        m["status"] = "finished"
        m["ended_at"] = now_iso()
        m["completed"] = completed
        m["half_points"] = not completed

        if is_draw:
            m["score_delta"] = {"winner": 0, "loser": 0}
            outcome["m"] = m
            outcome["is_draw"] = True
            outcome["release_table"] = m.get("table_id")
            return ms

        users = load("users")
        w = find_by_id(users, winner_id)
        l = find_by_id(users, loser_id)
        if not w or not l:
            raise ValueError("玩家数据异常")

        is_ranked = m.get("match_type") == "ranked" and m.get("ranked_valid", True)
        w_score = w.get("score", INITIAL_SCORE)
        l_score = l.get("score", INITIAL_SCORE)

        if is_ranked:
            w_delta = ranked_point_delta(w_score, l_score, True)
            l_delta = ranked_point_delta(w_score, l_score, False)
            if m.get("half_points"):
                w_delta = w_delta // 2
                l_delta = l_delta // 2
            m["score_delta"] = {"winner": w_delta, "loser": l_delta}
            outcome["w_delta"] = w_delta
            outcome["l_delta"] = l_delta
        else:
            bonus = daily_bonus("valid_match")
            if m.get("half_points"):
                bonus = bonus // 2
            m["score_delta"] = {"winner": bonus, "loser": 0}
            outcome["casual_bonus"] = bonus

        outcome["m"] = m
        outcome["winner_id"] = winner_id
        outcome["loser_id"] = loser_id
        outcome["is_ranked"] = is_ranked
        outcome["is_draw"] = False
        outcome["release_table"] = m.get("table_id")
        return ms

    mutate("matches", _finish_matches)
    m = outcome["m"]

    if outcome.get("release_table"):
        _release_table(outcome["release_table"])

    if outcome.get("skip"):
        return m

    if outcome.get("is_draw"):
        m0 = outcome["m"]
        _apply_finish_user_updates(
            m0["player1_id"], m0["player2_id"], match_id, False, 0, 0, 0, True
        )

        def _summary(ms):
            mm = find_by_id(ms, match_id)
            if mm:
                mm["summary"] = build_match_summary(mm)
            return ms

        mutate("matches", _summary)
        return find_by_id(load("matches"), match_id) or m

    _apply_finish_user_updates(
        outcome["winner_id"],
        outcome["loser_id"],
        match_id,
        outcome["is_ranked"],
        outcome.get("w_delta", 0),
        outcome.get("l_delta", 0),
        outcome.get("casual_bonus", 0),
        False,
    )

    def _summary(ms):
        mm = find_by_id(ms, match_id)
        if mm:
            mm["summary"] = build_match_summary(mm)
        return ms

    mutate("matches", _summary)
    return find_by_id(load("matches"), match_id) or m


def _release_table(table_id: str):
    """对局结束/无效后释放桌台：关台、清空等候，下次需重新扫码开台"""

    def _fn(ts):
        t = find_by_id(ts, table_id)
        if t:
            t["current_match_id"] = None
            t["waiting_players"] = []
            t["opened"] = False
            t["opened_at"] = None
            t.pop("opened_by_scan", None)
        return ts

    mutate("tables", _fn)


def force_release_table(table_id: str) -> Dict:
    """强制释放桌台：取消进行中对局并清空等候"""
    tables = load("tables")
    table = find_by_id(tables, table_id)
    if not table:
        raise ValueError("桌台不存在")

    mid = table.get("current_match_id")
    if mid:

        def _cancel(ms):
            m = find_by_id(ms, mid)
            if m and m.get("status") == "playing":
                m["status"] = "cancelled"
                m["ended_at"] = now_iso()
                m["invalid_reason"] = "管理员释放桌台，对局已取消"
            return ms

        mutate("matches", _cancel)

    def _fn(ts):
        t = find_by_id(ts, table_id)
        if t:
            t["current_match_id"] = None
            t["waiting_players"] = []
            t["opened"] = False
            t["opened_at"] = None
            t.pop("opened_by_scan", None)
        return ts

    mutate("tables", _fn)
    return find_by_id(load("tables"), table_id) or {}


def add_daily_bonus(user_id: str, bonus_type: str):
    pts = daily_bonus(bonus_type)
    if pts:
        adjust_user_score(user_id, pts, f"日常加分:{bonus_type}")


def open_table_hours_bonus(user_id: str, hours: float):
    pts = int(hours * daily_bonus("hour_open"))
    if pts > 0:
        adjust_user_score(user_id, pts, f"开台{hours}小时加分")


def cancel_pending_exchanges_for_users(user_ids, note: str = "") -> int:
    """待审核兑换取消并退回积分、恢复库存"""
    id_set = {uid for uid in (user_ids or []) if uid}
    if not id_set:
        return 0
    exchanges = load("exchanges")
    pending_ids = [
        ex["id"]
        for ex in exchanges
        if ex.get("user_id") in id_set and ex.get("status") == "pending"
    ]
    for ex_id in pending_ids:
        refund_exchange(ex_id, note)
    return len(pending_ids)


def count_user_exchanges_today(user_id: str) -> int:
    """统计用户当日已提交的兑换次数（任意状态）"""
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(
        1
        for e in load("exchanges")
        if e.get("user_id") == user_id and (e.get("created_at") or "").startswith(today)
    )


def check_exchange_eligibility(user_id: str, user_score: int) -> None:
    """校验积分兑换门槛与每日次数"""
    if user_score < EXCHANGE_MIN_SCORE:
        raise ValueError(
            f"积分需达到{EXCHANGE_MIN_SCORE}分方可兑换（当前{user_score}分）"
        )
    if count_user_exchanges_today(user_id) >= EXCHANGE_DAILY_LIMIT:
        raise ValueError(f"今日兑换次数已达上限（每日{EXCHANGE_DAILY_LIMIT}次）")


def exchange_rules_for_user(user_id: str, user_score: int) -> Dict:
    today_count = count_user_exchanges_today(user_id)
    return {
        "min_score": EXCHANGE_MIN_SCORE,
        "daily_limit": EXCHANGE_DAILY_LIMIT,
        "user_score": user_score,
        "exchanges_today": today_count,
        "can_exchange": user_score >= EXCHANGE_MIN_SCORE and today_count < EXCHANGE_DAILY_LIMIT,
        "rule_text": f"积分达到{EXCHANGE_MIN_SCORE}分方可兑换，每日限兑{EXCHANGE_DAILY_LIMIT}次",
    }


def exchange_product(user_id: str, product_id: str) -> Dict:
    record_holder: Dict[str, Any] = {}

    def _products(ps):
        prod = find_by_id(ps, product_id)
        if not prod or not prod.get("enabled"):
            raise ValueError("商品不存在或已下架")
        if prod.get("stock", 0) <= 0:
            raise ValueError("库存不足")
        prod["stock"] -= 1
        record_holder["points"] = prod["points"]
        record_holder["name"] = prod["name"]
        return ps

    mutate("products", _products)

    try:
        def _users(us):
            u = find_by_id(us, user_id)
            if not u:
                raise ValueError("用户不存在")
            score = u.get("score", INITIAL_SCORE)
            if score < EXCHANGE_MIN_SCORE:
                raise ValueError(
                    f"积分需达到{EXCHANGE_MIN_SCORE}分方可兑换（当前{score}分）"
                )
            pts = record_holder["points"]
            if score < pts:
                raise ValueError("积分不足")
            u["score"] = max(0, score - pts)
            u["updated_at"] = now_iso()
            record_holder["record"] = {
                "id": new_id("E"),
                "user_id": user_id,
                "product_id": product_id,
                "product_name": record_holder["name"],
                "points": pts,
                "status": "pending",
                "created_at": now_iso(),
                "reviewed_at": None,
                "review_note": "",
            }
            return us

        mutate("users", _users)

        def _ex(exs):
            today = datetime.now().strftime("%Y-%m-%d")
            count = sum(
                1
                for e in exs
                if e.get("user_id") == user_id
                and (e.get("created_at") or "").startswith(today)
            )
            if count >= EXCHANGE_DAILY_LIMIT:
                raise ValueError(
                    f"今日兑换次数已达上限（每日{EXCHANGE_DAILY_LIMIT}次）"
                )
            exs.append(record_holder["record"])
            return exs

        mutate("exchanges", _ex)
    except ValueError:
        def _restore_stock(ps):
            prod = find_by_id(ps, product_id)
            if prod:
                prod["stock"] = prod.get("stock", 0) + 1
            return ps

        mutate("products", _restore_stock)

        def _restore_user(us):
            u = find_by_id(us, user_id)
            if u and record_holder.get("points"):
                u["score"] = u.get("score", INITIAL_SCORE) + record_holder["points"]
                u["updated_at"] = now_iso()
            return us

        if record_holder.get("record"):
            mutate("users", _restore_user)
        raise

    log_score(user_id, -record_holder["points"], f"兑换:{record_holder['name']}")
    return record_holder["record"]


def refund_exchange(ex_id: str, note: str = "") -> Dict:
    """拒绝兑换：退回积分并恢复库存"""
    exchanges = load("exchanges")
    ex = find_by_id(exchanges, ex_id)
    if not ex:
        raise ValueError("兑换记录不存在")
    if ex.get("status") != "pending":
        raise ValueError("仅待审核记录可拒绝退款")

    adjust_user_score(ex["user_id"], ex["points"], f"兑换拒绝退回:{ex.get('product_name', '')}")

    def _products(ps):
        prod = find_by_id(ps, ex.get("product_id"))
        if prod:
            prod["stock"] = prod.get("stock", 0) + 1
        return ps

    mutate("products", _products)

    def _fn(exs):
        item = find_by_id(exs, ex_id)
        item["status"] = "rejected"
        item["review_note"] = note
        item["reviewed_at"] = now_iso()
        return exs

    mutate("exchanges", _fn)
    return find_by_id(load("exchanges"), ex_id)


def get_screen_data() -> Dict:
    process_season_and_week()
    users = load("users")
    tables = load("tables")
    matches = load("matches")
    settings = load("settings")

    board = build_leaderboard(users, limit=20)
    active_matches = []
    for t in tables:
        mid = t.get("current_match_id")
        if mid:
            m = find_by_id(matches, mid)
            if m and m["status"] == "playing":
                p1 = find_by_id(users, m["player1_id"])
                p2 = find_by_id(users, m["player2_id"])
                active_matches.append({
                    "table_name": t["name"],
                    "table_id": t["id"],
                    "score1": m["score1"],
                    "score2": m["score2"],
                    "race_to": m["race_to"],
                    "p1_name": p1.get("nickname", "玩家1") if p1 else "玩家1",
                    "p2_name": p2.get("nickname", "玩家2") if p2 else "玩家2",
                })

    return {
        "leaderboard": board,
        "tables": active_matches,
        "violations": settings.get("public_violations", [])[:10],
        "cheat_announcements": settings.get("cheat_announcements", [])[:5],
        "season": load("season"),
    }
