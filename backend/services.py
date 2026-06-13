"""业务服务层"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from http_client import get as http_get

from anti_cheat import (
    add_violation,
    check_daily_score_alert,
    check_ip_limit,
    check_phone_unique,
    match_duration_valid,
    punish_user,
)
import config
from config import (
    DEV_MODE,
    EXCHANGE_DAILY_LIMIT,
    EXCHANGE_MIN_SCORE,
    INITIAL_SCORE,
    MATCH_ACTION_COOLDOWN,
)
from db import find_by_id, load, mutate, new_id, now_iso, save
from ladder_settings import get_effective_ladder_rules, get_ladder_rules
from venue_service import DEFAULT_VENUE_ID
from rating import (
    apply_inactive_penalty,
    build_leaderboard,
    can_challenge_rank,
    daily_bonus,
    get_tier,
    get_user_rank,
    dec_ranked_quota,
    inc_ranked_quota,
    can_ranked_by_tier,
    ranked_quota_ok,
    tier_gap,
    tier_match_point_deltas,
    should_hide_rank,
)


def ping_wx_api() -> Dict[str, Any]:
    """探测微信 AppID/Secret 是否配对正确（用于健康检查与部署验证）。"""
    import config as _cfg

    appid = (_cfg.WECHAT_APPID or "").strip()
    secret = (_cfg.WECHAT_SECRET or "").strip()
    out: Dict[str, Any] = {
        "ok": False,
        "appid": appid,
        "secret_len": len(secret),
    }
    if not appid or not secret:
        out["reason"] = "wechat_secret_missing"
        return out
    if len(secret) != 32:
        out["reason"] = "secret_len_invalid"
        return out
    try:
        tr = http_get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": appid,
                "secret": secret,
            },
            timeout=8,
        )
        tok = tr.json()
        if not tok.get("access_token"):
            out["token_ok"] = False
            out["reason"] = tok.get("errmsg") or "token_failed"
            return out
        out["token_ok"] = True
        r = http_get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": appid,
                "secret": secret,
                "js_code": "health_check_probe",
                "grant_type": "authorization_code",
            },
            timeout=8,
        )
        data = r.json()
        if isinstance(data, dict) and ("errcode" in data or "openid" in data):
            out["ok"] = True
            return out
        out["reason"] = "unexpected_response"
        return out
    except Exception as e:
        msg = str(e)
        if "api.weixin.qq.com" in msg and (
            "CERTIFICATE_VERIFY" in msg or "SSL" in msg.upper()
        ):
            out["reason"] = "ssl_verify_failed"
        else:
            out["reason"] = msg[:160]
        return out


def wx_code_to_openid(code: str) -> Tuple[Optional[str], Optional[str]]:
    """仅用 code 换取 openid/session_key；用户头像昵称由前端 getUserProfile 传入，不在此接口获取。"""
    # 测试账号固定 code，仅开发模式可用
    if code.startswith("test_player_"):
        if not DEV_MODE:
            return None, "测试入口已关闭"
        return f"dev_{code}", None
    appid = config.WECHAT_APPID
    secret = config.WECHAT_SECRET
    if not appid or not secret:
        if DEV_MODE:
            return f"dev_{code}", None
        return None, "未配置微信小程序 AppID/Secret，无法完成微信登录"
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": appid,
        "secret": secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        r = http_get(url, params=params, timeout=10)
        data = r.json()
        if "openid" in data:
            return data["openid"], data.get("session_key")
        errmsg = data.get("errmsg", "微信登录失败")
        if str(errmsg).startswith("invalid code"):
            return None, (
                f"登录码无效（小程序 AppID 与服务器不一致或 code 已过期）。"
                f"请确认开发者工具 AppID 为 {appid}，与云托管 WECHAT_APPID 一致后重新编译登录"
            )
        if "invalid appsecret" in errmsg or errmsg == "invalid signature":
            return None, "AppSecret 与 AppID 不匹配，请在 wechat.secret.txt 填写正确密钥后重启后端"
        return None, errmsg
    except Exception as e:
        msg = str(e)
        if "api.weixin.qq.com" in msg and (
            "CERTIFICATE_VERIFY" in msg or "SSL" in msg.upper()
        ):
            return None, "服务器无法连接微信登录服务，请稍后重试或联系管理员更新云托管"
        if "api.weixin.qq.com" in msg:
            return None, "微信登录服务暂时不可用，请稍后重试"
        return None, "微信登录失败，请稍后重试"


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
    if match_id:
        from match_score_review import match_blocks_score_update

        m = find_by_id(load("matches"), match_id)
        if m and match_blocks_score_update(match_id=match_id, m=m):

            def _stash(ms):
                mm = find_by_id(ms, match_id)
                if mm:
                    mm.setdefault("deferred_scores", []).append({
                        "user_id": user_id,
                        "delta": delta,
                        "reason": reason,
                        "at": now_iso(),
                    })
                return ms

            mutate("matches", _stash)
            return

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

    playing_ids = [m["id"] for m in to_delete if m.get("status") == "playing"]
    if playing_ids:
        raise ValueError("不能删除进行中的对局，请先结束或释放桌台")

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


def delete_score_logs(
    log_ids: List[str],
    venue_id: Optional[str] = None,
    is_super: bool = True,
) -> Dict:
    """删除积分日志（总后台任意；球房仅可删本球房关联用户的日志）"""
    from admin_scope import filter_score_logs_for_venue

    ids = list({lid for lid in (log_ids or []) if lid})
    if not ids:
        raise ValueError("请选择要删除的日志")

    logs = load("score_logs")
    id_set = set(ids)
    existing = {l.get("id") for l in logs if l.get("id")}
    missing = id_set - existing
    if missing:
        raise ValueError("日志不存在: " + ", ".join(list(missing)[:3]))

    scoped = filter_score_logs_for_venue(logs, venue_id, is_super)
    allowed_ids = {l.get("id") for l in scoped if l.get("id")}
    forbidden = id_set - allowed_ids
    if forbidden:
        raise ValueError("无权删除其他球房或范围外的积分日志")

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

    from super_setup_service import authenticate_super

    if not authenticate_super(username, password):
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
    from anti_cheat import check_user_allowed

    ok, msg = check_ip_limit(ip, openid)
    if not ok:
        raise ValueError(msg)
    if phone:
        ok2, msg2 = check_phone_unique(phone)
        if not ok2:
            raise ValueError(msg2)

    holder: Dict[str, Any] = {}

    def _upsert(us):
        for u in us:
            if u.get("openid") != openid:
                continue
            u["last_login_at"] = now_iso()
            if nickname:
                u["nickname"] = nickname
                u["updated_at"] = now_iso()
            if phone:
                okp, msgp = check_phone_unique(phone, u["id"])
                if not okp:
                    raise ValueError(msgp)
                u["phone"] = phone
            if ip:
                u["last_ip"] = ip
            penalty = apply_inactive_penalty(u)
            if penalty > 0:
                u["score"] = max(0, u.get("score", INITIAL_SCORE) - penalty)
                log_score(u["id"], -penalty, "长期未对战扣分")
            holder["user"] = u
            return us
        new_user = {
            "id": new_id("U"),
            "openid": openid,
            "nickname": nickname or f"球友{openid[-4:]}",
            "avatar": "",
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
        us.append(new_user)
        holder["user"] = new_user
        return us

    mutate("users", _upsert)
    user = holder.get("user")
    if not user:
        raise ValueError("用户创建失败，请重试")
    ok, msg = check_user_allowed(user)
    if not ok:
        raise ValueError(msg)
    return user


def process_season_and_week():
    from match_score_review import process_stale_admin_reviews

    process_stale_admin_reviews()

    now = datetime.now()
    season_id = f"{now.year}{now.month:02d}"
    week_id = now.strftime("%Y-W%W")

    def _season(s):
        if s.get("current") != season_id:
            s["current"] = season_id
            s["started_at"] = now_iso()
        return s

    mutate("season", _season)

    def _week(wr):
        if wr.get("week_id") != week_id:
            wr["week_id"] = week_id
            wr["scores"] = {}
        return wr

    mutate("week_rank", _week)


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
    venue_id = table.get("venue_id", DEFAULT_VENUE_ID)
    rules = get_effective_ladder_rules(venue_id)

    if p1 and p2:
        ok_tier, tier_msg = can_ranked_by_tier(p1, p2, rules=rules)
        if not ok_tier:
            return "casual", tier_msg

    for p, _pid in ((p1, player1_id), (p2, player2_id)):
        ok, msg = ranked_quota_ok(p, rules=rules)
        if not ok:
            if rules.get("ranked_over_limit_to_casual", True):
                return "casual", msg
            raise ValueError(msg)

    if challenger_id and target_id:
        cr = get_user_rank(users, challenger_id)
        tr = get_user_rank(users, target_id)
        ok, msg = can_challenge_rank(cr, tr, rules=rules)
        if ok:
            return "ranked", "挑战符合天梯规则，自动排位赛"
        return "casual", msg

    r1 = get_user_rank(users, player1_id)
    r2 = get_user_rank(users, player2_id)
    if r1 == r2:
        return "casual", "双方排名相同，本场为休闲局"
    ch_rank, tg_rank = (r1, r2) if r1 > r2 else (r2, r1)
    ok, msg = can_challenge_rank(ch_rank, tg_rank, rules=rules)
    if ok:
        return "ranked", "符合天梯挑战规则，自动排位赛"
    return "casual", msg or "不符合天梯规则，本场为休闲局"


def reconcile_table_matches(table_id: str) -> None:
    """清理桌台残留的 current_match_id 与同桌孤儿 playing 对局"""

    def _matches(ms):
        tables = load("tables")
        table = find_by_id(tables, table_id) or {}
        active_mid = table.get("current_match_id")
        if active_mid:
            am = find_by_id(ms, active_mid)
            if not am or am.get("status") != "playing":
                active_mid = None
        for m in ms:
            if m.get("table_id") != table_id:
                continue
            if m.get("status") != "playing":
                continue
            if active_mid and m.get("id") == active_mid:
                continue
            m["status"] = "cancelled"
            m["ended_at"] = now_iso()
            m["invalid_reason"] = "系统自动清理：残留未结束对局"
        return ms

    mutate("matches", _matches)

    def _tables(ts):
        t = find_by_id(ts, table_id)
        if not t:
            return ts
        mid = t.get("current_match_id")
        if mid:
            m = find_by_id(load("matches"), mid)
            if not m or m.get("status") != "playing":
                t["current_match_id"] = None
        return ts

    mutate("tables", _tables)


def table_has_active_match(table: Dict) -> bool:
    """桌台是否真有进行中对局（排除过期的 current_match_id）"""
    mid = table.get("current_match_id")
    if not mid:
        return False
    m = find_by_id(load("matches"), mid)
    return bool(m and m.get("status") == "playing")


def user_has_active_match(user_id: str, exclude_table_id: str = None) -> bool:
    """用户是否已在任意球台有进行中对局"""
    if not user_id:
        return False
    for m in load("matches"):
        if m.get("status") != "playing":
            continue
        if user_id not in (m.get("player1_id"), m.get("player2_id")):
            continue
        if exclude_table_id and m.get("table_id") == exclude_table_id:
            continue
        return True
    return False


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

    for uid in (player1_id, player2_id):
        if user_has_active_match(uid, exclude_table_id=table_id):
            raise ValueError("选手有进行中的对局，请先结束后再开始新对局")

    reconcile_table_matches(table_id)

    table = find_by_id(load("tables"), table_id)
    if not table:
        raise ValueError("桌台不存在")

    users = load("users")
    p1 = find_by_id(users, player1_id)
    p2 = find_by_id(users, player2_id)
    if not p1 or not p2:
        raise ValueError("玩家不存在")
    from anti_cheat import check_user_allowed

    for p in (p1, p2):
        ok, msg = check_user_allowed(p)
        if not ok:
            raise ValueError(msg)

    is_ranked = match_type == "ranked"
    if is_ranked and not table.get("opened"):
        is_ranked = False
        match_type = "casual"

    ranked_valid = True
    ranked_reason = ranked_reason_hint or ""

    venue_id = table.get("venue_id", DEFAULT_VENUE_ID)
    rules = get_effective_ladder_rules(venue_id)
    if is_ranked:
        ok_tier, tier_msg = can_ranked_by_tier(p1, p2, rules=rules)
        if not ok_tier:
            is_ranked = False
            match_type = "casual"
            ranked_valid = False
            ranked_reason = tier_msg
    if is_ranked:
        ok, msg = ranked_quota_ok(p1, rules=rules)
        if not ok:
            if rules.get("ranked_over_limit_to_casual", True):
                is_ranked = False
                ranked_valid = False
                ranked_reason = msg
            else:
                raise ValueError(msg)
        else:
            ok2, msg2 = ranked_quota_ok(p2, rules=rules)
            if not ok2:
                if rules.get("ranked_over_limit_to_casual", True):
                    is_ranked = False
                    ranked_valid = False
                    ranked_reason = msg2
                else:
                    raise ValueError(msg2)

    if challenger_id and target_id:
        ids = {player1_id, player2_id}
        if challenger_id not in ids or target_id not in ids or challenger_id == target_id:
            challenger_id = None
            target_id = None
        elif is_ranked:
            users_list = load("users")
            cr = get_user_rank(users_list, challenger_id)
            tr = get_user_rank(users_list, target_id)
            ok3, msg3 = can_challenge_rank(cr, tr, rules=rules)
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
        "last_activity_at": now_iso(),
        "bonuses": [],
        "bonus_pending": [],
        "ranked_quota_consumed": False,
    }

    from db import mutate_multi

    def _start_atomic(matches, tables, users):
        for m in matches:
            if m.get("status") != "playing":
                continue
            if m.get("table_id") == table_id:
                raise ValueError("该桌台已有进行中的对局")
            if m.get("player1_id") in (player1_id, player2_id) or m.get(
                "player2_id"
            ) in (player1_id, player2_id):
                raise ValueError("选手有进行中的对局，请先结束后再开始新对局")
        t = find_by_id(tables, table_id)
        if not t:
            raise ValueError("桌台不存在")
        if t.get("current_match_id"):
            existing = find_by_id(matches, t["current_match_id"])
            if existing and existing.get("status") == "playing":
                raise ValueError("该桌台已有进行中的对局")
        matches.append(match)
        t["current_match_id"] = match["id"]
        t["waiting_players"] = []
        _consume_ranked_quota_inplace(users, match)
        return match

    return mutate_multi(["matches", "tables", "users"], _start_atomic)


def _latest_match_action_time(last: Dict) -> Optional[datetime]:
    """取对局内最近一次操作时间（双方任一方操作均触发共用冷却）"""
    latest = None
    for v in (last or {}).values():
        try:
            t = datetime.fromisoformat(str(v).replace("Z", ""))
            if latest is None or t > latest:
                latest = t
        except ValueError:
            continue
    return latest


def get_match_action_cooldown_remaining(m: Dict, user_id: str = None) -> int:
    """距下次可操作剩余秒数（双方共用：任一方炸清/接清/胜/负后双方均冷却）"""
    del user_id  # 双方同一倒计时，与操作者无关
    last = m.get("last_action_at") or {}
    latest = _latest_match_action_time(last)
    if latest is None:
        return 0
    elapsed = (datetime.now() - latest).total_seconds()
    if elapsed >= MATCH_ACTION_COOLDOWN:
        return 0
    return max(1, int(MATCH_ACTION_COOLDOWN - elapsed))


def _check_match_action_cooldown(m: Dict, user_id: str, action_label: str = "操作") -> None:
    remain = get_match_action_cooldown_remaining(m, user_id)
    if remain > 0:
        raise ValueError(f"请等待{remain}秒后再{action_label}")


def _touch_match_action_cooldown(
    m: Dict, user_id: str, action_kind: str = None
) -> None:
    last = m.setdefault("last_action_at", {})
    ts = now_iso()
    last["match"] = ts
    last[f"{user_id}_action"] = ts
    if action_kind:
        from match_score_review import note_match_score_action

        note_match_score_action(m, user_id, action_kind)
    from match_idle import touch_match_activity

    touch_match_activity(m)


def auto_finish_idle_match(match_id: str, reason: str = "") -> Dict:
    """闲置/超时自动结束：按当前局分结算并释放桌台"""
    m = find_by_id(load("matches"), match_id)
    if not m:
        raise ValueError("对局不存在")
    if m.get("status") != "playing":
        return m
    from match_idle import _winner_from_scores, touch_match_activity

    touch_match_activity(m)

    def _clear(ms):
        mm = find_by_id(ms, match_id)
        if mm:
            mm.pop("idle_state", None)
        return ms

    mutate("matches", _clear)

    winner_id, completed = _winner_from_scores(m)
    result = finalize_match(match_id, winner_id, completed=completed)
    if reason and result:
        result["auto_end_reason"] = reason
    return result


def record_frame(match_id: str, user_id: str, action: str) -> Dict:
    """action: win | lose"""
    finish_holder: Dict[str, Any] = {}

    def _fn(ms):
        m = find_by_id(ms, match_id)
        if not m or m["status"] != "playing":
            raise ValueError("对局不存在或已结束")

        label = "本局胜利" if action == "win" else "本局失败"
        _check_match_action_cooldown(m, user_id, label)

        if action == "win":
            if user_id == m["player1_id"]:
                m["score1"] += 1
            elif user_id == m["player2_id"]:
                m["score2"] += 1
            else:
                raise ValueError("非本局玩家")
        elif action == "lose":
            if user_id == m["player1_id"]:
                m["score2"] += 1
            elif user_id == m["player2_id"]:
                m["score1"] += 1
            else:
                raise ValueError("非本局玩家")
        else:
            raise ValueError("无效操作")

        _touch_match_action_cooldown(m, user_id, action_kind=action)

        race = m["race_to"]
        if m["score1"] >= race or m["score2"] >= race:
            finish_holder["winner"] = (
                m["player1_id"] if m["score1"] >= race else m["player2_id"]
            )
            finish_holder["finish"] = True
        return ms

    mutate("matches", _fn)

    if finish_holder.get("finish"):
        return finalize_match(match_id, finish_holder["winner"], completed=True)
    return find_by_id(load("matches"), match_id) or {}


def _append_score_log_inplace(
    logs: List[Dict], user_id: str, delta: int, reason: str, match_id: str = None
) -> None:
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


def _update_week_score_inplace(wr: Dict, user_id: str, delta: int) -> None:
    if delta <= 0:
        return
    week_id = datetime.now().strftime("%Y-W%W")
    if wr.get("week_id") != week_id:
        wr["week_id"] = week_id
        wr["scores"] = {}
    scores = wr.setdefault("scores", {})
    scores[user_id] = scores.get(user_id, 0) + delta


def _release_table_inplace(tables: List[Dict], table_id: str) -> None:
    t = find_by_id(tables, table_id)
    if not t:
        return
    t["current_match_id"] = None
    t["waiting_players"] = []
    t["opened"] = False
    t["opened_at"] = None
    t.pop("opened_by_scan", None)


def _consume_ranked_quota_inplace(users: List[Dict], match: Dict) -> None:
    """有效排位赛开始时扣减双方今日/本周排位次数"""
    if match.get("ranked_quota_consumed"):
        return
    if match.get("match_type") != "ranked" or not match.get("ranked_valid", True):
        return
    for uid in (match.get("player1_id"), match.get("player2_id")):
        u = find_by_id(users, uid)
        if u:
            inc_ranked_quota(u)
    match["ranked_quota_consumed"] = True


def _refund_ranked_quota_inplace(users: List[Dict], match: Dict) -> None:
    """无效/取消的排位局退回次数"""
    if not match.get("ranked_quota_consumed"):
        return
    for uid in (match.get("player1_id"), match.get("player2_id")):
        u = find_by_id(users, uid)
        if u:
            dec_ranked_quota(u)
    match["ranked_quota_consumed"] = False


def _apply_finish_user_updates_inplace(
    users: List[Dict],
    score_logs: List[Dict],
    week_rank: Dict,
    winner_id: Optional[str],
    loser_id: Optional[str],
    match_id: str,
    is_ranked: bool,
    w_delta: int,
    l_delta: int,
    casual_winner_bonus: int,
    is_draw: bool,
    ranked_quota_consumed: bool = False,
) -> List[Tuple[str, int]]:
    """内存中更新用户/日志/周榜，返回需事后风控检查的 (user_id, delta) 列表"""
    alerts: List[Tuple[str, int]] = []
    battle_at = now_iso()

    if is_draw:
        for uid in (winner_id, loser_id):
            if not uid:
                continue
            u = find_by_id(users, uid)
            if u:
                u["last_battle_at"] = battle_at
                u["updated_at"] = battle_at
        return alerts

    uw = find_by_id(users, winner_id)
    ul = find_by_id(users, loser_id)
    if not uw or not ul:
        raise ValueError("玩家数据异常")

    if is_ranked:
        if not ranked_quota_consumed:
            inc_ranked_quota(uw)
            inc_ranked_quota(ul)
        uw["score"] = max(0, uw.get("score", INITIAL_SCORE) + w_delta)
        ul["score"] = max(0, ul.get("score", INITIAL_SCORE) + l_delta)
        _append_score_log_inplace(score_logs, winner_id, w_delta, "排位胜利", match_id)
        alerts.append((winner_id, max(0, w_delta)))
        if l_delta:
            _append_score_log_inplace(score_logs, loser_id, l_delta, "排位失败", match_id)
            alerts.append((loser_id, max(0, l_delta)))
        _update_week_score_inplace(week_rank, winner_id, w_delta)
        if l_delta:
            _update_week_score_inplace(week_rank, loser_id, l_delta)
    else:
        uw["score"] = max(0, uw.get("score", INITIAL_SCORE) + casual_winner_bonus)
        _append_score_log_inplace(
            score_logs, winner_id, casual_winner_bonus, "休闲对局有效局", match_id
        )
        alerts.append((winner_id, max(0, casual_winner_bonus)))
        if casual_winner_bonus:
            _update_week_score_inplace(week_rank, winner_id, casual_winner_bonus)

    uw["wins"] = uw.get("wins", 0) + 1
    ul["losses"] = ul.get("losses", 0) + 1
    uw["last_battle_at"] = battle_at
    ul["last_battle_at"] = battle_at
    uw["updated_at"] = battle_at
    ul["updated_at"] = battle_at
    return alerts


def finalize_match(match_id: str, winner_id: str = None, completed: bool = True) -> Dict:
    """对局结算：match、用户积分、日志、周榜、释放桌台单次原子提交"""
    from match_bonus import build_match_summary
    from db import mutate_multi

    holder: Dict[str, Any] = {"alerts": []}

    def _atomic(matches, users, score_logs, week_rank, tables):
        m = find_by_id(matches, match_id)
        if not m:
            raise ValueError("对局不存在")
        if m["status"] in ("finished", "invalid", "cancelled"):
            holder["m"] = m
            return m
        if m["status"] != "playing":
            raise ValueError("对局状态不可结算")

        p1, p2 = m["player1_id"], m["player2_id"]
        table_id = m.get("table_id")

        if m.get("score1", 0) == m.get("score2", 0):
            if winner_id:
                raise ValueError("比分相同，无法判定胜负")
            is_draw = True
            loser_id = None
        else:
            is_draw = False
            if winner_id not in (p1, p2):
                raise ValueError("胜者必须是本局选手之一")
            loser_id = p2 if winner_id == p1 else p1

        if not match_duration_valid(m["started_at"]):
            m["status"] = "invalid"
            m["ended_at"] = now_iso()
            m["invalid_reason"] = "对局时长过短，判定无效"
            _refund_ranked_quota_inplace(users, m)
            m["summary"] = build_match_summary(m)
            if table_id:
                _release_table_inplace(tables, table_id)
            holder["m"] = m
            return m

        m["winner_id"] = winner_id
        m["ended_at"] = now_iso()
        m["completed"] = completed
        m["half_points"] = not completed

        from match_score_review import (
            build_pending_settlement,
            match_should_defer_settlement,
        )

        if is_draw:
            m["score_delta"] = {"winner": 0, "loser": 0}
            if match_should_defer_settlement(m):
                m["status"] = "pending_review"
                m.setdefault("score_review_since", now_iso())
                m["pending_settlement"] = build_pending_settlement(
                    m,
                    winner_id=None,
                    loser_id=None,
                    is_draw=True,
                    is_ranked=False,
                    w_delta=0,
                    l_delta=0,
                    casual_bonus=0,
                    completed=completed,
                )
            else:
                m["status"] = "finished"
                holder["alerts"] = _apply_finish_user_updates_inplace(
                    users,
                    score_logs,
                    week_rank,
                    p1,
                    p2,
                    match_id,
                    False,
                    0,
                    0,
                    0,
                    True,
                    ranked_quota_consumed=bool(m.get("ranked_quota_consumed")),
                )
            m["summary"] = build_match_summary(m)
            if table_id:
                _release_table_inplace(tables, table_id)
            holder["m"] = m
            return m

        w = find_by_id(users, winner_id)
        l = find_by_id(users, loser_id)
        if not w or not l:
            raise ValueError("玩家数据异常")

        is_ranked = m.get("match_type") == "ranked" and m.get("ranked_valid", True)
        table_row = find_by_id(tables, m.get("table_id"))
        match_venue_id = (
            table_row.get("venue_id", DEFAULT_VENUE_ID) if table_row else DEFAULT_VENUE_ID
        )
        ladder_rules = get_effective_ladder_rules(match_venue_id)

        if is_ranked:
            w_delta, l_delta = tier_match_point_deltas(
                winner_id,
                loser_id,
                p1,
                m.get("score1", 0),
                m.get("score2", 0),
                w,
                l,
                rules=ladder_rules,
                half_points=bool(m.get("half_points")),
            )
            m["tier_gap"] = tier_gap(
                w.get("score", INITIAL_SCORE),
                l.get("score", INITIAL_SCORE),
                ladder_rules,
            )
            m["frame_diff"] = abs(m.get("score1", 0) - m.get("score2", 0))
            m["score_delta"] = {"winner": w_delta, "loser": l_delta}
            casual_bonus = 0
        else:
            w_delta, l_delta = 0, 0
            casual_bonus = daily_bonus("valid_match", rules=ladder_rules)
            if m.get("half_points"):
                casual_bonus = casual_bonus // 2
            m["score_delta"] = {"winner": casual_bonus, "loser": 0}

        if match_should_defer_settlement(m):
            m["status"] = "pending_review"
            m.setdefault("score_review_since", now_iso())
            m["pending_settlement"] = build_pending_settlement(
                m,
                winner_id=winner_id,
                loser_id=loser_id,
                is_draw=False,
                is_ranked=is_ranked,
                w_delta=w_delta,
                l_delta=l_delta,
                casual_bonus=casual_bonus,
                completed=completed,
            )
        else:
            m["status"] = "finished"
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
        m["summary"] = build_match_summary(m)
        if table_id:
            _release_table_inplace(tables, table_id)
        holder["m"] = m
        return m

    mutate_multi(
        ["matches", "users", "score_logs", "week_rank", "tables"], _atomic
    )
    result_m = holder.get("m") or find_by_id(load("matches"), match_id) or {}
    if result_m and result_m.get("table_id"):
        tbl = find_by_id(load("tables"), result_m.get("table_id"))
        vid = (tbl or {}).get("venue_id", DEFAULT_VENUE_ID)
        try:
            from review_log_service import log_match_settlement_outcome

            log_match_settlement_outcome(result_m, vid)
        except Exception:
            pass
    for uid, delta in holder.get("alerts") or []:
        alert = check_daily_score_alert(uid, delta)
        if alert:
            add_violation(uid, alert, "warn", False)
    return result_m


def finish_match(match_id: str, winner_id: str = None, completed: bool = True) -> Dict:
    return finalize_match(match_id, winner_id, completed)


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


def exchange_rules_for_user(
    user_id: str, user_score: int, venue_id: str = None
) -> Dict:
    from venue_service import DEFAULT_VENUE_ID, get_venue, is_member_active

    today_count = count_user_exchanges_today(user_id)
    vid = (venue_id or DEFAULT_VENUE_ID).strip()
    venue = get_venue(vid)
    venue_active = is_member_active(venue) if venue else False
    base_ok = user_score >= EXCHANGE_MIN_SCORE and today_count < EXCHANGE_DAILY_LIMIT
    can_exchange = base_ok and venue_active
    rule_text = f"积分达到{EXCHANGE_MIN_SCORE}分方可兑换，每日限兑{EXCHANGE_DAILY_LIMIT}次"
    if not venue_active:
        rule_text = "俱乐部会员已过期，积分兑换已暂停，请联系球房续费"
    return {
        "min_score": EXCHANGE_MIN_SCORE,
        "daily_limit": EXCHANGE_DAILY_LIMIT,
        "user_score": user_score,
        "exchanges_today": today_count,
        "can_exchange": can_exchange,
        "venue_member_active": venue_active,
        "rule_text": rule_text,
    }


def exchange_product(user_id: str, product_id: str, venue_id: str = None) -> Dict:
    from db import mutate_multi
    from membership_service import assert_venue_allows_exchange

    assert_venue_allows_exchange(venue_id)

    def _exchange_atomic(products, users, exchanges):
        prod = find_by_id(products, product_id)
        if not prod or not prod.get("enabled"):
            raise ValueError("商品不存在或已下架")
        if prod.get("stock", 0) <= 0:
            raise ValueError("库存不足")
        u = find_by_id(users, user_id)
        if not u:
            raise ValueError("用户不存在")
        score = u.get("score", INITIAL_SCORE)
        if score < EXCHANGE_MIN_SCORE:
            raise ValueError(
                f"积分需达到{EXCHANGE_MIN_SCORE}分方可兑换（当前{score}分）"
            )
        today = datetime.now().strftime("%Y-%m-%d")
        count = sum(
            1
            for e in exchanges
            if e.get("user_id") == user_id
            and (e.get("created_at") or "").startswith(today)
        )
        if count >= EXCHANGE_DAILY_LIMIT:
            raise ValueError(f"今日兑换次数已达上限（每日{EXCHANGE_DAILY_LIMIT}次）")
        pts = prod["points"]
        if score < pts:
            raise ValueError("积分不足")
        prod["stock"] -= 1
        u["score"] = max(0, score - pts)
        u["updated_at"] = now_iso()
        record = {
            "id": new_id("E"),
            "user_id": user_id,
            "product_id": product_id,
            "product_name": prod["name"],
            "points": pts,
            "status": "pending",
            "created_at": now_iso(),
            "reviewed_at": None,
            "review_note": "",
        }
        exchanges.append(record)
        return record

    record = mutate_multi(["products", "users", "exchanges"], _exchange_atomic)
    log_score(user_id, -record["points"], f"兑换:{record['product_name']}")
    return record


def refund_exchange(ex_id: str, note: str = "") -> Dict:
    """拒绝兑换：退回积分并恢复库存（原子）"""
    from db import mutate_multi

    holder: Dict = {}

    def _refund_atomic(products, users, exchanges, score_logs, week_rank):
        item = find_by_id(exchanges, ex_id)
        if not item:
            raise ValueError("兑换记录不存在")
        if item.get("status") != "pending":
            raise ValueError("仅待审核记录可拒绝退款")
        uid = item["user_id"]
        pts = int(item.get("points") or 0)
        u = find_by_id(users, uid)
        if not u:
            raise ValueError("用户不存在")
        u["score"] = max(0, u.get("score", INITIAL_SCORE) + pts)
        u["updated_at"] = now_iso()
        _append_score_log_inplace(
            score_logs,
            uid,
            pts,
            f"兑换拒绝退回:{item.get('product_name', '')}",
        )
        _update_week_score_inplace(week_rank, uid, pts)
        prod = find_by_id(products, item.get("product_id"))
        if prod:
            prod["stock"] = prod.get("stock", 0) + 1
        item["status"] = "rejected"
        item["review_note"] = note
        item["reviewed_at"] = now_iso()
        holder["ex"] = item
        return item

    mutate_multi(
        ["products", "users", "exchanges", "score_logs", "week_rank"],
        _refund_atomic,
    )
    return holder.get("ex") or find_by_id(load("exchanges"), ex_id)


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
