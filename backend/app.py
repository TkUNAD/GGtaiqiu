"""台球天梯系统 - Flask + SocketIO 主入口"""
import io
import os
from datetime import datetime
from functools import wraps
from typing import Dict

from flask import Flask, jsonify, request, render_template, session, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit

import config
from admin_auth import (
    admin_required,
    build_admin_session_info,
    has_permission,
    is_super_admin,
    member_permission_required,
    require_active_venue_member,
    super_admin_required,
)


def safe_int(val, default: int = 0, min_v: int = None, max_v: int = None) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        n = default
    if min_v is not None:
        n = max(min_v, n)
    if max_v is not None:
        n = min(max_v, n)
    return n
from anti_cheat import punish_user
from db import find_by_id, load, mutate, now_iso, save
from ladder_settings import (
    get_ladder_rules,
    ladder_rules_payload,
    save_global_ladder_rules,
    save_venue_ladder_rules,
    sync_venue_ladder_from_global,
)
from rating import build_leaderboard, get_tier, get_user_rank
from table_util import default_qr_link, enrich_table, enrich_tables
from venue_service import (
    DEFAULT_VENUE_ID,
    create_venue,
    delete_venue,
    ensure_table_venue_ids,
    ensure_venues_file,
    filter_tables_for_session,
    list_venues,
    mobile_venue_status,
    update_venue,
    authenticate_venue,
    get_venue_admin_detail,
    venue_public_view,
)
from services import (
    add_daily_bonus,
    adjust_user_score,
    exchange_product,
    finish_match,
    force_release_table,
    get_or_create_user,
    get_screen_data,
    open_table_hours_bonus,
    process_season_and_week,
    record_frame,
    refund_exchange,
    start_match,
    wx_code_to_openid,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = config.SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower()
    in ("1", "true", "yes"),
)
CORS(
    app,
    resources={r"/api/*": {"origins": config.CORS_ORIGINS}},
    supports_credentials=True,
)
socketio = SocketIO(
    app, cors_allowed_origins=config.CORS_ORIGINS, async_mode="threading"
)


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def _ok(data=None, msg="ok"):
    return jsonify({"code": 0, "msg": msg, "data": data})


def _err(msg, code=1, http_status=400):
    """code 为业务码；http_status 为 HTTP 状态（勿写成 return _err(...), 401 双重元组）"""
    return jsonify({"code": code, "msg": msg, "data": None}), http_status


def _broadcast():
    socketio.emit("update", get_screen_data())


# ---------- 页面 ----------
@app.route("/")
def index():
    return jsonify({"name": "台球天梯系统 API", "admin": "/admin", "screen": "/screen"})


@app.route("/api/health")
def health():
    return _ok({"status": "ok"})


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/screen")
def screen_page():
    return render_template("screen.html")


# ---------- 管理后台登录 ----------
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    from admin_auth import (
        build_admin_session_info,
        check_login_rate_limit,
        clear_login_attempts,
        record_login_failure,
    )

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    ip = _client_ip()

    blocked = check_login_rate_limit(ip)
    if blocked:
        return _err(blocked, 429, 429)

    session.clear()
    ensure_venues_file()

    if username == config.ADMIN_USER and password == config.ADMIN_PASS:
        session["admin_logged_in"] = True
        session["admin_role"] = "super"
        session["admin_username"] = username
        clear_login_attempts(ip)
        return _ok(build_admin_session_info())

    venue = authenticate_venue(username, password)
    if venue:
        from venue_service import is_member_active, venue_permissions

        session["admin_logged_in"] = True
        session["admin_role"] = "venue"
        session["venue_id"] = venue["id"]
        session["admin_username"] = username
        session["permissions"] = venue_permissions(venue)
        clear_login_attempts(ip)
        info = build_admin_session_info()
        if not is_member_active(venue):
            info["member_tip"] = "球房会员已过期，仅可查看基础数据；开通后可管理桌台、修改天梯规则、屏蔽手机端广告"
        return _ok(info)

    return _err(record_login_failure(ip))


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return _ok()


@app.route("/api/admin/me")
@admin_required
def admin_me():
    return _ok(build_admin_session_info())


@app.route("/api/admin/password/change", methods=["POST"])
@admin_required
def admin_password_change():
    from admin_auth import record_login_failure, check_login_rate_limit
    from admin_password import change_password_logged_in

    data = request.get_json(silent=True) or {}
    ip = _client_ip()
    blocked = check_login_rate_limit(ip)
    if blocked:
        return _err(blocked, 429, 429)

    try:
        result = change_password_logged_in(
            session.get("admin_role", ""),
            session.get("admin_username", ""),
            session.get("venue_id"),
            data.get("old_password") or "",
            data.get("new_password") or "",
            data.get("confirm_password") or data.get("new_password") or "",
        )
        return _ok(result)
    except ValueError as e:
        msg = str(e)
        if "密码" in msg or "账号" in msg:
            msg = record_login_failure(ip, msg)
        return _err(msg)


@app.route("/api/admin/password/change-with-old", methods=["POST"])
def admin_password_change_with_old():
    from admin_auth import check_login_rate_limit, record_login_failure, clear_login_attempts
    from admin_password import change_password_with_old

    data = request.get_json(silent=True) or {}
    ip = _client_ip()
    blocked = check_login_rate_limit(ip)
    if blocked:
        return _err(blocked, 429, 429)

    try:
        result = change_password_with_old(
            data.get("username") or "",
            data.get("old_password") or "",
            data.get("new_password") or "",
            data.get("confirm_password") or "",
        )
        clear_login_attempts(ip)
        return _ok(result)
    except ValueError as e:
        msg = str(e)
        if "密码" in msg or "账号" in msg or "密钥" in msg:
            msg = record_login_failure(ip, msg)
        return _err(msg)


@app.route("/api/admin/password/forgot", methods=["POST"])
def admin_password_forgot():
    from admin_auth import check_login_rate_limit, record_login_failure, clear_login_attempts
    from admin_password import reset_password_forgot

    data = request.get_json(silent=True) or {}
    ip = _client_ip()
    blocked = check_login_rate_limit(ip)
    if blocked:
        return _err(blocked, 429, 429)

    try:
        result = reset_password_forgot(
            data.get("username") or "",
            data.get("recovery_secret") or "",
            data.get("new_password") or "",
            data.get("confirm_password") or "",
        )
        clear_login_attempts(ip)
        return _ok(result)
    except ValueError as e:
        msg = str(e)
        if "密码" in msg or "账号" in msg or "密钥" in msg:
            msg = record_login_failure(ip, msg)
        return _err(msg)


@app.route("/api/venue/status")
def venue_status_api():
    venue_id = request.args.get("venue_id", DEFAULT_VENUE_ID)
    return _ok(mobile_venue_status(venue_id))


@app.route("/api/venues/list")
def venues_list_mobile():
    from venue_service import VENUE_DISTANCE_WARN_METERS, list_mobile_venues

    lat_raw = request.args.get("latitude")
    lng_raw = request.args.get("longitude")
    lat = lng = None
    if lat_raw not in (None, "") and lng_raw not in (None, ""):
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except ValueError:
            return _err("坐标格式无效", 400)
    venues = list_mobile_venues(lat, lng)
    return _ok(
        {
            "venues": venues,
            "distance_warn_meters": VENUE_DISTANCE_WARN_METERS,
        }
    )


@app.route("/api/settings/ladder")
def public_ladder_rules():
    venue_id = request.args.get("venue_id", DEFAULT_VENUE_ID)
    return _ok(ladder_rules_payload(venue_id))


# ---------- 微信登录 ----------
@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    """
    前端传入 code（wx.login）、nickname、avatar（wx.getUserProfile）。
    后端仅用 code 调微信 jscode2session 换取 openid；头像昵称由前端传入直接保存，不再向微信拉取。
    须配置 WECHAT_APPID、WECHAT_SECRET。
    """
    data = request.get_json() or {}
    code = (data.get("code") or "").strip()
    nickname = (data.get("nickname") or "").strip()
    avatar = (data.get("avatar") or "").strip()
    if not code:
        return _err("缺少 code")
    if not nickname:
        return _err("请先完成微信昵称授权", 400, 400)
    openid, err = wx_code_to_openid(code)
    if not openid:
        return _err(err or "登录失败")
    try:
        user = get_or_create_user(
            openid,
            nickname=nickname,
            avatar=avatar,
            phone=data.get("phone", ""),
            ip=_client_ip(),
        )
    except ValueError as e:
        return _err(str(e))
    from auth_tokens import issue_tokens

    tier = get_tier(user["score"])
    users = load("users")
    rank = get_user_rank(users, user["id"])
    tokens = issue_tokens(user)
    return _ok({
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_in": tokens["expires_in"],
        "token_type": tokens["token_type"],
        "user": {**user, "tier": tier, "rank": rank},
    })


@app.route("/api/auth/refresh", methods=["POST"])
def auth_refresh():
    data = request.get_json(silent=True) or {}
    refresh = (data.get("refresh_token") or "").strip()
    from auth_tokens import refresh_access_token

    bundle, err = refresh_access_token(refresh)
    if err:
        return _err(err, 401, 401)
    return _ok(bundle)


def _user_from_token():
    from anti_cheat import check_user_allowed
    from auth_tokens import verify_access_token

    auth = request.headers.get("Authorization", "")
    token = auth or request.headers.get("X-Token", "")
    user_id = verify_access_token(token)
    if not user_id:
        return None
    users = load("users")
    user = find_by_id(users, user_id)
    if not user:
        return None
    ok, _msg = check_user_allowed(user)
    if not ok:
        return None
    return user


# ---------- 天梯榜 ----------
@app.route("/api/rank/list")
def rank_list():
    process_season_and_week()
    limit = safe_int(request.args.get("limit"), 50, 1, 500)
    users = load("users")
    board = build_leaderboard(users, limit=limit)
    return _ok(board)


@app.route("/api/rank/club")
def rank_club():
    process_season_and_week()
    from rank_board import build_club_leaderboard

    venue_id = request.args.get("venue_id", DEFAULT_VENUE_ID)
    limit = safe_int(request.args.get("limit"), 50, 1, 100)
    board = (request.args.get("board") or "total").lower()
    if board not in ("week", "month", "total"):
        board = "total"
    return _ok(build_club_leaderboard(venue_id, limit, board))


@app.route("/api/rank/global")
def rank_global():
    process_season_and_week()
    from rank_board import build_global_leaderboard

    limit = safe_int(request.args.get("limit"), 50, 1, 100)
    return _ok(build_global_leaderboard(limit))


@app.route("/api/rank/player/<user_id>")
def rank_player(user_id):
    from rank_board import player_public_info

    info = player_public_info(user_id)
    if not info:
        return _err("选手不存在", 404, 404)
    return _ok(info)


@app.route("/api/home/summary")
def home_summary():
    process_season_and_week()
    from rank_board import build_club_leaderboard
    from user_history import today_score_gain
    from ladder_settings import get_effective_ladder_rules
    from rating import ranked_quota_ok

    venue_id = request.args.get("venue_id", DEFAULT_VENUE_ID)
    user = _user_from_token()
    tables = [
        t for t in load("tables")
        if t.get("venue_id", DEFAULT_VENUE_ID) == venue_id
    ]
    enriched = enrich_tables(tables)
    top10 = build_club_leaderboard(venue_id, 10)

    payload = {
        "top_rank": top10,
        "tables": enriched,
        "challenge_targets": [],
        "today_score": 0,
        "ranked_remaining_daily": 0,
        "ranked_remaining_weekly": 0,
        "daily_ranked_limit": 2,
        "weekly_ranked_limit": 9,
    }
    if user:
        rules = get_effective_ladder_rules(venue_id)
        payload["daily_ranked_limit"] = rules.get("daily_ranked_limit", 2)
        payload["weekly_ranked_limit"] = rules.get("weekly_ranked_limit", 9)
        payload["today_score"] = today_score_gain(user["id"])
        today = datetime.now().strftime("%Y-%m-%d")
        week = datetime.now().strftime("%Y-W%W")
        daily = user.get("daily_ranked_count") or {}
        weekly = user.get("weekly_ranked_count") or {}
        d_used = daily.get("count", 0) if daily.get("date") == today else 0
        w_used = weekly.get("count", 0) if weekly.get("week") == week else 0
        payload["ranked_remaining_daily"] = max(
            0, payload["daily_ranked_limit"] - d_used
        )
        payload["ranked_remaining_weekly"] = max(
            0, payload["weekly_ranked_limit"] - w_used
        )
        users_all = load("users")
        my_rank = get_user_rank(users_all, user["id"])
        rmin = int(rules.get("challenge_rank_min", 1))
        rmax = int(rules.get("challenge_rank_max", 5))
        board = build_leaderboard(users_all, limit=min(my_rank, 500))
        targets = []
        if my_rank < 9999:
            for item in board:
                if item["id"] == user["id"]:
                    continue
                gap = my_rank - item["rank"]
                if rmin <= gap <= rmax:
                    targets.append(item)
        payload["challenge_targets"] = targets
        payload["challenge_rank_min"] = rmin
        payload["challenge_rank_max"] = rmax
        payload["my_rank"] = my_rank
        ok, msg = ranked_quota_ok(user, rules)
        payload["ranked_quota_ok"] = ok
        payload["ranked_quota_msg"] = msg
    return _ok(payload)


@app.route("/api/rank/challenge-targets")
def challenge_targets():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    from venue_service import DEFAULT_VENUE_ID

    venue_id = request.args.get("venue_id") or user.get("venue_id") or DEFAULT_VENUE_ID
    rules = get_effective_ladder_rules(venue_id)
    rmin = int(rules.get("challenge_rank_min", 1))
    rmax = int(rules.get("challenge_rank_max", 5))
    users = load("users")
    my_rank = get_user_rank(users, user["id"])
    if my_rank >= 9999:
        return _ok({
            "my_rank": my_rank,
            "targets": [],
            "ladder_rules": {
                "challenge_rank_min": rmin,
                "challenge_rank_max": rmax,
                "daily_ranked_limit": rules.get("daily_ranked_limit", 2),
                "weekly_ranked_limit": rules.get("weekly_ranked_limit", 9),
            },
            "hint": "您暂无天梯排名，暂无可挑战玩家",
        })
    board = build_leaderboard(users, limit=min(my_rank, 500))
    targets = []
    for item in board:
        if item["id"] == user["id"]:
            continue
        gap = my_rank - item["rank"]
        if rmin <= gap <= rmax:
            targets.append(item)
    return _ok({
        "my_rank": my_rank,
        "targets": targets,
        "ladder_rules": {
            "challenge_rank_min": rmin,
            "challenge_rank_max": rmax,
            "daily_ranked_limit": rules["daily_ranked_limit"],
            "weekly_ranked_limit": rules["weekly_ranked_limit"],
        },
    })


# ---------- 玩家列表（选对手） ----------
@app.route("/api/users/active")
def active_users():
    from admin_scope import users_linked_to_venue
    from user_public import sanitize_user_list

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    venue_id = request.args.get("venue_id") or DEFAULT_VENUE_ID
    limit = safe_int(request.args.get("limit"), 30, 1, 100)
    linked = users_linked_to_venue(venue_id)
    users = load("users")
    club = [
        u for u in users
        if u.get("id") in linked and u.get("status") != "banned" and not u.get("deleted")
    ]
    club.sort(key=lambda x: (-x.get("score", 1000), x.get("created_at", "")))
    return _ok(sanitize_user_list(club, limit))


# ---------- 桌台 ----------
@app.route("/api/tables")
def tables_list():
    ensure_table_venue_ids()
    venue_id = request.args.get("venue_id")
    tables = load("tables")
    if venue_id:
        tables = [t for t in tables if t.get("venue_id", DEFAULT_VENUE_ID) == venue_id]
    matches = load("matches")
    users = load("users")
    result = []
    for t in tables:
        item = dict(t)
        mid = t.get("current_match_id")
        if mid:
            m = find_by_id(matches, mid)
            if m:
                p1 = find_by_id(users, m["player1_id"])
                p2 = find_by_id(users, m["player2_id"])
                item["match"] = {
                    "id": m["id"],
                    "score1": m["score1"],
                    "score2": m["score2"],
                    "race_to": m["race_to"],
                    "p1": p1.get("nickname") if p1 else "",
                    "p2": p2.get("nickname") if p2 else "",
                }
        result.append(item)
    return _ok(result)


@app.route("/api/table/<table_id>")
def table_detail(table_id):
    from table_queue import build_table_view, prune_all_stale_waiting_players

    token = request.args.get("qr_token", "")
    prune_all_stale_waiting_players()
    tables = load("tables")
    t = find_by_id(tables, table_id)
    if not t:
        return _err("桌台不存在")
    from table_queue import _require_qr_token_match

    try:
        _require_qr_token_match(t, token)
    except ValueError as e:
        return _err(str(e))
    user = _user_from_token()
    view = build_table_view(t, user["id"] if user else None)
    return _ok(view)


@app.route("/api/table/<table_id>/scan-check")
def table_scan_check(table_id):
    from table_queue import check_table_scan
    from venue_service import DEFAULT_VENUE_ID

    token = request.args.get("qr_token", "")
    venue_id = request.args.get("venue_id") or DEFAULT_VENUE_ID
    try:
        return _ok(check_table_scan(table_id, token, venue_id))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/table/<table_id>/join", methods=["POST"])
def table_join(table_id):
    from table_queue import join_table
    from venue_service import DEFAULT_VENUE_ID

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    venue_id = data.get("venue_id") or request.args.get("venue_id") or DEFAULT_VENUE_ID
    try:
        view = join_table(
            table_id,
            user["id"],
            data.get("qr_token", ""),
            venue_id=venue_id,
        )
        _broadcast()
        return _ok(view)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/table/<table_id>/race", methods=["POST"])
def table_set_race(table_id):
    from table_queue import set_waiting_race

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    try:
        race_raw = int(data.get("race_to", 5))
    except (TypeError, ValueError):
        return _err("局数格式无效", 400)
    from table_queue import ALLOWED_RACE_TO, normalize_race_to

    if race_raw not in ALLOWED_RACE_TO:
        return _err("局数仅支持 5/7/9/11/13", 400)
    try:
        view = set_waiting_race(table_id, user["id"], normalize_race_to(race_raw))
        _broadcast()
        return _ok(view)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/table/<table_id>/leave", methods=["POST"])
def table_leave(table_id):
    from table_queue import leave_table

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    try:
        view = leave_table(table_id, user["id"])
        _broadcast()
        return _ok(view)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/table/<table_id>/start", methods=["POST"])
def table_start_match(table_id):
    from table_queue import start_from_table

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    from venue_service import DEFAULT_VENUE_ID

    venue_id = data.get("venue_id") or request.args.get("venue_id") or DEFAULT_VENUE_ID
    try:
        m = start_from_table(
            table_id,
            user["id"],
            int(data.get("race_to", 5)),
            data.get("match_type", "casual"),
            challenger_id=data.get("challenger_id"),
            target_id=data.get("target_id"),
            venue_id=venue_id,
        )
        _broadcast()
        return _ok(m)
    except ValueError as e:
        return _err(str(e))


# ---------- 对局 ----------
@app.route("/api/match/start", methods=["POST"])
def match_start():
    """兼容旧版；请使用 /api/table/<id>/start"""
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    table_id = data.get("table_id")
    if table_id:
        from table_queue import start_from_table

        try:
            m = start_from_table(
                table_id,
                user["id"],
                int(data.get("race_to", 5)),
                data.get("match_type", "casual"),
                challenger_id=data.get("challenger_id"),
                target_id=data.get("target_id"),
            )
            _broadcast()
            return _ok(m)
        except ValueError as e:
            return _err(str(e))
    return _err("请两名选手扫码到场后再开始（需 table_id）")


def _match_player_card(u: Dict) -> Dict:
    from config import INITIAL_SCORE
    from rating import get_tier

    if not u:
        return {}
    tier = get_tier(u.get("score", INITIAL_SCORE))
    return {
        "id": u.get("id"),
        "nickname": u.get("nickname", "球友"),
        "avatar": u.get("avatar") or "",
        "score": u.get("score", INITIAL_SCORE),
        "tier_index": tier.get("tier_index", 1),
        "tier_name": tier.get("tier_name", ""),
        "star": tier.get("star", 1),
    }


def _match_api_payload(m: Dict, user_id: str, run_idle: bool = False) -> Dict:
    from match_bonus import enrich_match_display, get_pending_for_user
    from match_idle import build_idle_ui, process_idle_match

    if run_idle:
        m = process_idle_match(m["id"])
    else:
        fresh = find_by_id(load("matches"), m.get("id"))
        if fresh:
            m = fresh
    users = load("users")
    p1 = _match_player_card(find_by_id(users, m.get("player1_id")))
    p2 = _match_player_card(find_by_id(users, m.get("player2_id")))
    pending = get_pending_for_user(m, user_id)
    display = enrich_match_display(m, user_id)
    idle_ui = build_idle_ui(m, user_id)
    return {**m, "p1": p1, "p2": p2, "bonus_pending_list": pending, "idle_ui": idle_ui, **display}


@app.route("/api/match/<match_id>")
def match_detail(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    matches = load("matches")
    m = find_by_id(matches, match_id)
    if not m:
        return _err("对局不存在")
    if user["id"] not in (m.get("player1_id"), m.get("player2_id")):
        return _err("无权查看该对局", 403, 403)
    return _ok(_match_api_payload(m, user["id"], run_idle=False))


@app.route("/api/match/<match_id>/sync", methods=["POST"])
def match_sync(match_id):
    """轮询同步：推进闲置检测并返回最新对局（GET 不再写库）"""
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    matches = load("matches")
    m0 = find_by_id(matches, match_id)
    if not m0:
        return _err("对局不存在")
    if user["id"] not in (m0.get("player1_id"), m0.get("player2_id")):
        return _err("无权查看该对局", 403, 403)
    m = _match_api_payload(m0, user["id"], run_idle=True)
    return _ok(m)


@app.route("/api/match/<match_id>/frame", methods=["POST"])
def match_frame(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json() or {}
    action = data.get("action")
    try:
        m = record_frame(match_id, user["id"], action)
        _broadcast()
        return _ok(_match_api_payload(m, user["id"], run_idle=True))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/finish", methods=["POST"])
def match_finish(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    matches = load("matches")
    m0 = find_by_id(matches, match_id)
    if not m0:
        return _err("对局不存在")
    if user["id"] not in (m0.get("player1_id"), m0.get("player2_id")):
        return _err("非本局玩家", 403, 403)
    data = request.get_json() or {}
    s1, s2 = m0.get("score1", 0), m0.get("score2", 0)
    race_to = int(m0.get("race_to") or 5)
    completed = (s1 + s2) >= race_to
    if m0.get("match_type") != "ranked" or not m0.get("ranked_valid", True):
        completed = bool(data.get("completed", completed))
    if s1 == s2:
        if data.get("winner_id"):
            return _err("平局时不能指定胜者", 400)
        winner_id = None
    else:
        winner_id = m0["player1_id"] if s1 > s2 else m0["player2_id"]
        client_winner = data.get("winner_id")
        if client_winner and client_winner != winner_id:
            return _err("胜者信息与比分不一致", 400)
    try:
        m = finish_match(match_id, winner_id, completed=completed)
        _broadcast()
        if m.get("status") in ("finished", "invalid"):
            return _ok(m)
        return _ok(_match_api_payload(m, user["id"], run_idle=False))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/idle/continue", methods=["POST"])
def match_idle_continue(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    try:
        from match_idle import idle_confirm_continue

        result = idle_confirm_continue(match_id, user["id"])
        _broadcast()
        m = result["match"]
        if m.get("status") in ("finished", "invalid"):
            return _ok(m)
        return _ok(_match_api_payload(m, user["id"], run_idle=False))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/idle/end", methods=["POST"])
def match_idle_end(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    try:
        from match_idle import idle_request_end

        result = idle_request_end(match_id, user["id"])
        _broadcast()
        m = result["match"]
        if m.get("status") in ("finished", "invalid"):
            return _ok(m)
        return _ok(_match_api_payload(m, user["id"], run_idle=False))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/idle/end-response", methods=["POST"])
def match_idle_end_response(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    agree = bool(data.get("agree"))
    try:
        from match_idle import idle_respond_end

        result = idle_respond_end(match_id, user["id"], agree)
        _broadcast()
        m = result["match"]
        if m.get("status") in ("finished", "invalid"):
            return _ok(m)
        return _ok(_match_api_payload(m, user["id"], run_idle=False))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/bonus/request", methods=["POST"])
def match_bonus_request(match_id):
    from match_bonus import get_pending_for_user, request_bonus

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    try:
        item = request_bonus(match_id, user["id"], data.get("type"))
        m = find_by_id(load("matches"), match_id)
        _broadcast()
        users = load("users")
        claimer = find_by_id(users, user["id"]) or {}
        item_out = dict(item)
        item_out["claimer_name"] = claimer.get("nickname", "球友")
        payload = _match_api_payload(m, user["id"], run_idle=True)
        return _ok({
            "item": item_out,
            "pending": get_pending_for_user(m, user["id"]),
            "action_cooldown_remaining": payload.get("action_cooldown_remaining", 0),
        })
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/bonus/confirm", methods=["POST"])
def match_bonus_confirm(match_id):
    from match_bonus import get_pending_for_user, confirm_bonus

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    try:
        result = confirm_bonus(match_id, user["id"], data.get("bonus_id"))
        m = result["match"]
        _broadcast()
        payload = _match_api_payload(m, user["id"]) if m.get("status") == "playing" else m
        cd = payload.get("action_cooldown_remaining", 0) if isinstance(payload, dict) else 0
        return _ok({
            "item": result["item"],
            "pending": get_pending_for_user(m, user["id"]) if m.get("status") == "playing" else [],
            "applied": result["item"].get("status") == "applied",
            "frame_awarded": result.get("frame_awarded", False),
            "match_finished": result.get("match_finished", False),
            "match": payload,
            "action_cooldown_remaining": cd,
        })
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/bonus/reject", methods=["POST"])
def match_bonus_reject(match_id):
    from match_bonus import get_pending_for_user, reject_bonus

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    data = request.get_json(silent=True) or {}
    try:
        result = reject_bonus(match_id, user["id"], data.get("bonus_id"))
        m = result["match"]
        _broadcast()
        return _ok({
            "item": result["item"],
            "pending": get_pending_for_user(m, user["id"]),
        })
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/match/<match_id>/bonus-review", methods=["POST"])
@admin_required
def admin_bonus_review(match_id):
    from admin_auth import is_super_admin
    from admin_scope import assert_match_in_venue
    from match_bonus import approve_bonus_review, punish_bonus_cheat, reject_bonus_review

    try:
        assert_match_in_venue(match_id, session.get("venue_id"), is_super_admin())
    except ValueError as e:
        return _err(str(e))

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    bonus_id = data.get("bonus_id")
    try:
        if action == "approve":
            result = approve_bonus_review(match_id, bonus_id, data.get("note", ""))
        elif action == "reject":
            result = reject_bonus_review(match_id, bonus_id, data.get("note", ""))
        elif action == "cheat":
            result = punish_bonus_cheat(
                match_id,
                data.get("user_id"),
                bonus_id,
                data.get("note", ""),
            )
        else:
            return _err("action 需为 approve / reject / cheat")
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/summary")
def match_summary(match_id):
    from match_bonus import build_match_summary

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    m = find_by_id(load("matches"), match_id)
    if not m:
        return _err("对局不存在")
    if user["id"] not in (m.get("player1_id"), m.get("player2_id")):
        return _err("无权查看该对局", 403, 403)
    if m.get("status") not in ("finished", "invalid"):
        return _err("对局未结束")
    summary = m.get("summary") or build_match_summary(m)
    return _ok(summary)


# ---------- 个人中心 ----------
@app.route("/api/user/profile")
def user_profile():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    users = load("users")
    tier = get_tier(user["score"])
    rank = get_user_rank(users, user["id"])
    total = user.get("wins", 0) + user.get("losses", 0)
    win_rate = round(user.get("wins", 0) / total * 100, 1) if total else 0
    from services import exchange_rules_for_user
    from user_history import (
        count_user_exchanges,
        count_user_matches,
        count_user_score_logs,
        get_user_exchanges_list,
        get_user_matches_list,
        get_user_score_logs_list,
        today_score_gain,
    )
    from ladder_settings import get_effective_ladder_rules

    recent_matches = get_user_matches_list(user["id"], 5)
    score_logs = get_user_score_logs_list(user["id"], 5)
    recent_exchanges = get_user_exchanges_list(user["id"], 5)
    rules = get_effective_ladder_rules(user.get("venue_id") or DEFAULT_VENUE_ID)
    today = datetime.now().strftime("%Y-%m-%d")
    week = datetime.now().strftime("%Y-W%W")
    daily = user.get("daily_ranked_count") or {}
    weekly = user.get("weekly_ranked_count") or {}
    d_used = daily.get("count", 0) if daily.get("date") == today else 0
    w_used = weekly.get("count", 0) if weekly.get("week") == week else 0
    exchange_rules = exchange_rules_for_user(user["id"], user.get("score", 1000))
    from user_public import sanitize_user_public

    return _ok({
        "user": sanitize_user_public(user),
        "tier": tier,
        "rank": rank,
        "win_rate": win_rate,
        "wins": user.get("wins", 0),
        "losses": user.get("losses", 0),
        "total_games": total,
        "recent_matches": recent_matches,
        "score_logs": score_logs,
        "recent_exchanges": recent_exchanges,
        "match_total": count_user_matches(user["id"]),
        "log_total": count_user_score_logs(user["id"]),
        "exchange_total": count_user_exchanges(user["id"]),
        "today_score": today_score_gain(user["id"]),
        "ranked_remaining_daily": max(0, rules.get("daily_ranked_limit", 2) - d_used),
        "ranked_remaining_weekly": max(0, rules.get("weekly_ranked_limit", 9) - w_used),
        "exchange_rules": exchange_rules,
    })


@app.route("/api/user/matches")
def user_matches():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    from user_history import get_user_matches_list

    limit = min(int(request.args.get("limit", 20)), 50)
    return _ok(get_user_matches_list(user["id"], limit))


@app.route("/api/user/score-logs")
def user_score_logs():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    from user_history import get_user_score_logs_list

    limit = safe_int(request.args.get("limit"), 20, 1, 50)
    return _ok(get_user_score_logs_list(user["id"], limit))


@app.route("/api/user/exchanges")
def user_exchanges():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    from user_history import get_user_exchanges_list

    limit = safe_int(request.args.get("limit"), 20, 1, 50)
    return _ok(get_user_exchanges_list(user["id"], limit))


@app.route("/api/user/nickname", methods=["POST"])
def update_nickname():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    nickname = (request.get_json() or {}).get("nickname", "").strip()
    if not nickname:
        return _err("昵称不能为空")
    if len(nickname) > 20:
        return _err("昵称最多20个字符")

    def _fn(users):
        u = find_by_id(users, user["id"])
        if not u:
            raise ValueError("用户不存在")
        u["nickname"] = nickname
        u["updated_at"] = now_iso()
        return users

    try:
        mutate("users", _fn)
    except ValueError as e:
        return _err(str(e))
    users = load("users")
    u = find_by_id(users, user["id"])
    tier = get_tier(u["score"])
    rank = get_user_rank(users, u["id"])
    return _ok({"user": {**u, "tier": tier, "rank": rank}})


@app.route("/api/user/bind-phone", methods=["POST"])
def bind_phone():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    phone = (request.get_json() or {}).get("phone", "")
    if not phone:
        return _err("请输入手机号")
    from anti_cheat import check_phone_unique

    ok, msg = check_phone_unique(phone, user["id"])
    if not ok:
        return _err(msg)

    def _fn(users):
        u = find_by_id(users, user["id"])
        if not u:
            raise ValueError("用户不存在")
        u["phone"] = phone
        return users

    try:
        mutate("users", _fn)
    except ValueError as e:
        return _err(str(e))
    return _ok()


# ---------- 商城 ----------
@app.route("/api/shop/products")
def shop_products():
    from config import EXCHANGE_DAILY_LIMIT, EXCHANGE_MIN_SCORE, INITIAL_SCORE
    from services import exchange_rules_for_user

    products = [p for p in load("products") if p.get("enabled")]
    rules = {
        "min_score": EXCHANGE_MIN_SCORE,
        "daily_limit": EXCHANGE_DAILY_LIMIT,
        "rule_text": f"积分达到{EXCHANGE_MIN_SCORE}分方可兑换，每日限兑{EXCHANGE_DAILY_LIMIT}次",
    }
    user = _user_from_token()
    if user:
        rules = exchange_rules_for_user(user["id"], user.get("score", INITIAL_SCORE))
    return _ok({"products": products, "rules": rules})


@app.route("/api/shop/exchange", methods=["POST"])
def shop_exchange():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    product_id = (request.get_json() or {}).get("product_id")
    try:
        record = exchange_product(user["id"], product_id)
        _broadcast()
        return _ok(record)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/shop/my-exchanges")
def my_exchanges():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401, 401)
    exs = [e for e in load("exchanges") if e.get("user_id") == user["id"]]
    exs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return _ok(exs)


# ---------- 大屏数据 ----------
@app.route("/api/screen/data")
def screen_data():
    return _ok(get_screen_data())


# ---------- 管理后台 API ----------
@app.route("/api/admin/settings/ladder", methods=["GET"])
@admin_required
def admin_get_ladder_settings():
    if is_super_admin():
        payload = ladder_rules_payload(None)
        payload["scope"] = "global"
        return _ok(payload)
    vid = session.get("venue_id")
    payload = ladder_rules_payload(vid)
    payload["scope"] = "venue"
    payload["can_edit"] = has_permission("ladder_settings")
    return _ok(payload)


@app.route("/api/admin/settings/ladder", methods=["PUT"])
@member_permission_required("ladder_settings")
def admin_save_ladder_settings():
    data = request.get_json(silent=True) or {}
    if is_super_admin():
        save_global_ladder_rules(data)
        payload = ladder_rules_payload(None)
        payload["scope"] = "global"
        return _ok(payload)
    vid = session.get("venue_id")
    if not vid:
        return _err("球房会话无效")
    save_venue_ladder_rules(vid, data)
    payload = ladder_rules_payload(vid)
    payload["scope"] = "venue"
    return _ok(payload)


@app.route("/api/admin/settings/ladder/sync", methods=["POST"])
@member_permission_required("ladder_settings")
def admin_sync_ladder_settings():
    if is_super_admin():
        return _err("总后台请直接编辑全局默认规则")
    vid = session.get("venue_id")
    if not vid:
        return _err("球房会话无效")
    sync_venue_ladder_from_global(vid)
    return _ok(ladder_rules_payload(vid))


@app.route("/api/admin/venues", methods=["GET"])
@super_admin_required
def admin_list_venues():
    return _ok(list_venues())


@app.route("/api/admin/venues", methods=["POST"])
@super_admin_required
def admin_create_venue():
    data = request.get_json(silent=True) or {}
    try:
        return _ok(create_venue(data))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/venue/<venue_id>", methods=["PUT"])
@super_admin_required
def admin_update_venue(venue_id):
    data = request.get_json(silent=True) or {}
    try:
        return _ok(update_venue(venue_id, data))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/venue/<venue_id>", methods=["DELETE"])
@super_admin_required
def admin_delete_venue(venue_id):
    try:
        delete_venue(venue_id)
        return _ok()
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/venues/<venue_id>/detail", methods=["GET"])
@super_admin_required
def admin_venue_detail(venue_id):
    try:
        return _ok(get_venue_admin_detail(venue_id))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/dashboard")
@admin_required
def admin_dashboard():
    from admin_auth import is_super_admin
    from admin_scope import scoped_dashboard_stats

    return _ok(scoped_dashboard_stats(session.get("venue_id"), is_super_admin()))


@app.route("/api/admin/matches")
@admin_required
def admin_matches():
    from admin_scope import filter_matches_for_venue
    from admin_auth import is_super_admin
    from match_bonus import enrich_match_for_admin

    matches = load("matches")
    matches = filter_matches_for_venue(
        matches, session.get("venue_id"), is_super_admin()
    )
    matches.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return _ok([enrich_match_for_admin(m) for m in matches[:500]])


@app.route("/api/admin/match/<match_id>/review", methods=["POST"])
@admin_required
def admin_review_match(match_id):
    from admin_auth import is_super_admin
    from admin_scope import assert_match_in_venue
    from services import _release_table

    try:
        assert_match_in_venue(match_id, session.get("venue_id"), is_super_admin())
    except ValueError as e:
        return _err(str(e))

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    m = find_by_id(load("matches"), match_id)
    if not m:
        return _err("对局不存在")

    if action == "approve":
        try:
            if m.get("status") == "pending_review" and m.get("pending_settlement"):
                from match_score_review import apply_pending_match_settlement

                m = apply_pending_match_settlement(
                    match_id, data.get("note", "管理员审核通过")
                )
            else:
                winner_id = data.get("winner_id")
                if not winner_id:
                    s1, s2 = m.get("score1", 0), m.get("score2", 0)
                    if s1 == s2:
                        return _err("比分相同，请指定胜者或改判")
                    winner_id = m["player1_id"] if s1 > s2 else m["player2_id"]
                m = finish_match(
                    match_id,
                    winner_id,
                    completed=data.get("completed", True),
                )
        except ValueError as e:
            return _err(str(e))
    elif action == "reject":
        def _reject(ms):
            item = find_by_id(ms, match_id)
            if not item:
                raise ValueError("对局不存在")
            item["status"] = "rejected"
            item["review_note"] = data.get("note", "")
            return ms

        try:
            mutate("matches", _reject)
        except ValueError as e:
            return _err(str(e))
        table_id = m.get("table_id")
        if table_id:
            _release_table(table_id)
        m = find_by_id(load("matches"), match_id)
    elif action == "modify":
        return _err(
            "不支持直接改判比分。请使用「通过」完成结算，或「拒绝」取消对局。",
            400,
            400,
        )
    else:
        return _err("未知操作")

    _broadcast()
    return _ok(m)


@app.route("/api/admin/match/<match_id>", methods=["DELETE"])
@admin_required
def admin_delete_match(match_id):
    from admin_auth import is_super_admin
    from services import delete_matches

    try:
        result = delete_matches(
            [match_id],
            venue_id=session.get("venue_id"),
            is_super=is_super_admin(),
        )
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/matches/batch-delete", methods=["POST"])
@admin_required
def admin_batch_delete_matches():
    from admin_auth import is_super_admin
    from services import delete_matches

    data = request.get_json(silent=True) or {}
    match_ids = data.get("match_ids") or []
    try:
        result = delete_matches(
            match_ids,
            venue_id=session.get("venue_id"),
            is_super=is_super_admin(),
        )
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/users")
@admin_required
def admin_users():
    from admin_scope import filter_users_for_venue
    from admin_auth import is_super_admin

    from anti_cheat import count_serious_violations

    users = filter_users_for_venue(
        load("users"), session.get("venue_id"), is_super_admin()
    )
    board = build_leaderboard(users, limit=1000, include_hidden=True)
    rank_map = {b["id"]: b["rank"] for b in board}
    for u in users:
        u["rank"] = rank_map.get(u["id"], 9999)
        u["tier"] = get_tier(u.get("score", 1000))
        u["serious_violation_count"] = count_serious_violations(u["id"])
    return _ok(users)


@app.route("/api/admin/user/<user_id>/score", methods=["POST"])
@admin_required
@require_active_venue_member
def admin_adjust_score(user_id):
    from admin_scope import assert_user_in_venue
    from admin_auth import is_super_admin

    try:
        assert_user_in_venue(user_id, session.get("venue_id"), is_super_admin())
    except ValueError as e:
        return _err(str(e))
    data = request.get_json(silent=True) or {}
    try:
        delta = int(data.get("delta", 0))
    except (TypeError, ValueError):
        return _err("积分变动必须为整数")
    reason = data.get("reason", "管理员调整")
    adjust_user_score(user_id, delta, reason)
    _broadcast()
    return _ok()


@app.route("/api/admin/user/<user_id>/punish", methods=["POST"])
@admin_required
@require_active_venue_member
def admin_punish(user_id):
    from admin_scope import assert_user_in_venue
    from admin_auth import is_super_admin

    try:
        assert_user_in_venue(user_id, session.get("venue_id"), is_super_admin())
    except ValueError as e:
        return _err(str(e))
    data = request.get_json() or {}
    action = data.get("action", "warn")
    reason = data.get("reason", "")
    if action == "record_cheat" and not reason:
        reason = "球房后台记录：恶意刷分/作弊"
    extra = {}
    if action == "record_cheat":
        from anti_cheat import add_violation_and_check_permanent

        extra = add_violation_and_check_permanent(user_id, reason, "record_cheat", data.get("public", True))
    else:
        punish_user(user_id, action, reason, data.get("public", True))
    from anti_cheat import count_serious_violations

    u = find_by_id(load("users"), user_id) or {}
    _broadcast()
    return _ok({
        "serious_violation_count": count_serious_violations(user_id),
        "ban_permanent": bool(u.get("ban_permanent")),
        "status": u.get("status"),
        "auto_permanent_ban": extra.get("auto_permanent_ban", False),
    })


@app.route("/api/admin/user/<user_id>", methods=["DELETE"])
@admin_required
@require_active_venue_member
def admin_delete_user(user_id):
    from admin_scope import assert_user_in_venue
    from admin_auth import is_super_admin
    from services import delete_users

    try:
        assert_user_in_venue(user_id, session.get("venue_id"), is_super_admin())
        result = delete_users([user_id])
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/users/batch-delete", methods=["POST"])
@admin_required
def admin_batch_delete_users():
    from admin_scope import assert_user_in_venue
    from admin_auth import is_super_admin
    from services import delete_users

    data = request.get_json(silent=True) or {}
    user_ids = data.get("user_ids") or []
    try:
        for uid in user_ids:
            assert_user_in_venue(uid, session.get("venue_id"), is_super_admin())
        result = delete_users(user_ids)
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/system/reset", methods=["POST"])
@admin_required
def admin_reset_system_data():
    from admin_auth import is_super_admin
    from services import admin_reset_data

    data = request.get_json(silent=True) or {}
    role = "super" if is_super_admin() else "venue"
    venue_id = session.get("venue_id")
    try:
        result = admin_reset_data(
            role,
            venue_id,
            data.get("username", ""),
            data.get("password", ""),
        )
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/tables", methods=["GET", "POST"])
@admin_required
def admin_tables():
    ensure_table_venue_ids()
    if request.method == "GET":
        tables = filter_tables_for_session(
            load("tables"),
            session.get("venue_id"),
            is_super_admin(),
        )
        return _ok(enrich_tables(tables))
    if not has_permission("table_manage"):
        return _err("球房未开通会员，无法管理桌台", 403, 403)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return _err("请输入桌台名称")

    created = {}

    def _fn(ts):
        nums = []
        for t in ts:
            tid = t.get("id", "")
            if tid.startswith("T") and tid[1:].isdigit():
                nums.append(int(tid[1:]))
        next_num = max(nums) + 1 if nums else 1
        import secrets

        tid = f"T{next_num:02d}"
        token = secrets.token_urlsafe(16)
        venue_id = data.get("venue_id") or session.get("venue_id") or DEFAULT_VENUE_ID
        if not is_super_admin() and venue_id != session.get("venue_id"):
            raise ValueError("无权为该球房添加桌台")
        row = {
            "id": tid,
            "name": name,
            "venue_id": venue_id,
            "qr_token": token,
            "qr_link": data.get("qr_link") or default_qr_link({"id": tid, "qr_token": token}),
            "opened": False,
            "current_match_id": None,
            "opened_at": None,
            "waiting_players": [],
        }
        ts.append(row)
        created["table"] = row
        return ts

    mutate("tables", _fn)
    _broadcast()
    return _ok(created.get("table"))


def _assert_table_venue_read(table: dict):
    """仅校验桌台归属；会员到期也可查看/下载二维码"""
    if is_super_admin():
        return
    if table.get("venue_id", DEFAULT_VENUE_ID) != session.get("venue_id"):
        raise ValueError("无权查看该桌台")


def _assert_table_access(table: dict):
    _assert_table_venue_read(table)
    if is_super_admin():
        return
    if not has_permission("table_manage"):
        raise ValueError("球房未开通会员，无法管理桌台")


@app.route("/api/admin/table/<table_id>", methods=["PUT", "DELETE"])
@admin_required
def admin_table_manage(table_id):
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}

        def _update(ts):
            t = find_by_id(ts, table_id)
            if not t:
                raise ValueError("桌台不存在")
            _assert_table_access(t)
            if data.get("name") is not None:
                name = (data.get("name") or "").strip()
                if name:
                    t["name"] = name
            if data.get("qr_token") is not None:
                token = (data.get("qr_token") or "").strip()
                if token:
                    t["qr_token"] = token
            if data.get("qr_link") is not None:
                t["qr_link"] = (data.get("qr_link") or "").strip() or default_qr_link(t)
            return ts

        try:
            mutate("tables", _update)
        except ValueError as e:
            return _err(str(e))
        _broadcast()
        t = find_by_id(load("tables"), table_id)
        return _ok(enrich_table(t) if t else None)

    def _delete(ts):
        t = find_by_id(ts, table_id)
        if not t:
            raise ValueError("桌台不存在")
        _assert_table_access(t)
        if t.get("current_match_id"):
            raise ValueError("该桌台有进行中的对局，无法删除")
        if t.get("opened"):
            raise ValueError("请先关台再删除")
        return [x for x in ts if x.get("id") != table_id]

    try:
        mutate("tables", _delete)
    except ValueError as e:
        return _err(str(e))
    _broadcast()
    return _ok()


@app.route("/api/admin/table/<table_id>/qrcode.png")
@admin_required
def admin_table_qrcode_png(table_id):
    t = find_by_id(load("tables"), table_id)
    if t:
        try:
            _assert_table_venue_read(t)
        except ValueError as e:
            return _err(str(e), 403, 403)
    try:
        import qrcode
    except ImportError:
        return _err("请安装 qrcode: pip install qrcode[pil]", 500, 500)

    from io import BytesIO

    if not t:
        t = find_by_id(load("tables"), table_id)
    if not t:
        return jsonify({"code": 1, "msg": "桌台不存在"}), 404
    t = enrich_table(t)
    text = request.args.get("text") or t.get("qr_link") or default_qr_link(t)

    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#4C1D95", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"{table_id}.png")


@app.route("/api/admin/table/<table_id>/open", methods=["POST"])
@admin_required
@require_active_venue_member
def admin_open_table(table_id):
    t = find_by_id(load("tables"), table_id)
    if t:
        try:
            _assert_table_access(t)
        except ValueError as e:
            return _err(str(e), 403, 403)
    data = request.get_json() or {}
    opened = data.get("opened", True)
    hours = float(data.get("hours", 0))
    user_id = data.get("user_id")

    def _fn(ts):
        t = find_by_id(ts, table_id)
        if not t:
            raise ValueError("桌台不存在")
        t["opened"] = opened
        t["opened_at"] = now_iso() if opened else None
        return ts

    try:
        mutate("tables", _fn)
    except ValueError as e:
        return _err(str(e))
    if opened and user_id and hours > 0:
        from admin_scope import assert_user_in_venue
        from admin_auth import is_super_admin

        try:
            assert_user_in_venue(user_id, session.get("venue_id"), is_super_admin())
        except ValueError as e:
            return _err(str(e))
        open_table_hours_bonus(user_id, hours)
    _broadcast()
    return _ok()


@app.route("/api/admin/table/<table_id>/release", methods=["POST"])
@admin_required
def admin_release_table(table_id):
    t = find_by_id(load("tables"), table_id)
    if not t:
        return _err("桌台不存在")
    try:
        _assert_table_access(t)
        table = force_release_table(table_id)
        _broadcast()
        return _ok(enrich_table(table))
    except ValueError as e:
        return _err(str(e), 403, 403)


@app.route("/api/admin/products", methods=["GET", "POST"])
@admin_required
def admin_products():
    from admin_auth import is_super_admin

    if request.method == "GET":
        return _ok(load("products"))
    if not is_super_admin():
        return _err("仅总后台可添加或修改商品", 403, 403)
    data = request.get_json() or {}
    product = {
        "id": data.get("id") or f"P{datetime.now().strftime('%H%M%S')}",
        "name": data.get("name", ""),
        "type": data.get("type", "其他"),
        "points": int(data.get("points", 0)),
        "stock": int(data.get("stock", 0)),
        "desc": data.get("desc", ""),
        "enabled": data.get("enabled", True),
    }

    def _fn(ps):
        existing = find_by_id(ps, product["id"])
        if existing:
            existing.update(product)
        else:
            ps.append(product)
        return ps

    mutate("products", _fn)
    return _ok(product)


@app.route("/api/admin/product/<product_id>", methods=["DELETE"])
@super_admin_required
def admin_delete_product(product_id):
    def _fn(ps):
        return [p for p in ps if p.get("id") != product_id]

    mutate("products", _fn)
    return _ok()


@app.route("/api/admin/exchanges")
@admin_required
def admin_exchanges():
    from admin_auth import is_super_admin
    from admin_scope import filter_exchanges_for_venue

    exs = filter_exchanges_for_venue(
        load("exchanges"), session.get("venue_id"), is_super_admin()
    )
    users = load("users")
    for e in exs:
        u = find_by_id(users, e.get("user_id"))
        e["nickname"] = u.get("nickname") if u else ""
    exs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return _ok(exs)


@app.route("/api/admin/exchange/<ex_id>/review", methods=["POST"])
@admin_required
def admin_review_exchange(ex_id):
    from admin_auth import is_super_admin
    from admin_scope import assert_exchange_in_venue

    try:
        assert_exchange_in_venue(ex_id, session.get("venue_id"), is_super_admin())
    except ValueError as e:
        return _err(str(e))

    data = request.get_json(silent=True) or {}
    status = data.get("status", "approved")
    note = data.get("note", "")

    if status not in ("approved", "rejected"):
        return _err("无效的审核状态，仅支持 approved 或 rejected", 400)

    try:
        if status == "rejected":
            refund_exchange(ex_id, note)
        else:

            def _fn(exs):
                e = find_by_id(exs, ex_id)
                if not e:
                    raise ValueError("兑换记录不存在")
                e["status"] = status
                e["review_note"] = note
                e["reviewed_at"] = now_iso()
                return exs

            mutate("exchanges", _fn)
    except ValueError as e:
        return _err(str(e))

    _broadcast()
    return _ok()


@app.route("/api/admin/exchange/<ex_id>", methods=["DELETE"])
@super_admin_required
def admin_delete_exchange(ex_id):
    from services import delete_exchanges

    try:
        result = delete_exchanges([ex_id])
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/exchanges/batch-delete", methods=["POST"])
@super_admin_required
def admin_batch_delete_exchanges():
    from services import delete_exchanges

    data = request.get_json(silent=True) or {}
    try:
        result = delete_exchanges(data.get("exchange_ids") or [])
        _broadcast()
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/log/score/<log_id>", methods=["DELETE"])
@admin_required
@require_active_venue_member
def admin_delete_score_log(log_id):
    from admin_auth import is_super_admin
    from services import delete_score_logs

    try:
        result = delete_score_logs(
            [log_id],
            session.get("venue_id"),
            is_super_admin(),
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/logs/score/batch-delete", methods=["POST"])
@admin_required
@require_active_venue_member
def admin_batch_delete_score_logs():
    from admin_auth import is_super_admin
    from services import delete_score_logs

    data = request.get_json(silent=True) or {}
    try:
        result = delete_score_logs(
            data.get("log_ids") or [],
            session.get("venue_id"),
            is_super_admin(),
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/logs/score")
@admin_required
def admin_score_logs():
    from admin_auth import is_super_admin
    from admin_scope import filter_score_logs_for_venue
    from user_history import format_admin_score_detail

    logs = filter_score_logs_for_venue(
        load("score_logs"), session.get("venue_id"), is_super_admin()
    )
    users = load("users")
    matches = load("matches")
    logs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    out = [format_admin_score_detail(l, users, matches) for l in logs[:1000]]
    return _ok(out)


@app.route("/api/admin/logs/exchange")
@admin_required
def admin_exchange_logs():
    return admin_exchanges()


@app.route("/api/admin/export/matches")
@admin_required
def admin_export_matches():
    try:
        import openpyxl
        from openpyxl import Workbook
    except ImportError:
        return _err("请安装 openpyxl: pip install openpyxl")

    wb = Workbook()
    ws = wb.active
    ws.title = "对局记录"
    ws.append(["ID", "桌台", "玩家1", "玩家2", "比分", "类型", "状态", "开始", "结束", "胜者"])
    from admin_auth import is_super_admin
    from admin_scope import filter_matches_for_venue

    matches = filter_matches_for_venue(
        load("matches"), session.get("venue_id"), is_super_admin()
    )
    users = load("users")
    for m in matches:
        p1 = find_by_id(users, m.get("player1_id"))
        p2 = find_by_id(users, m.get("player2_id"))
        w = find_by_id(users, m.get("winner_id")) if m.get("winner_id") else None
        ws.append([
            m.get("id"),
            m.get("table_id"),
            p1.get("nickname") if p1 else "",
            p2.get("nickname") if p2 else "",
            f"{m.get('score1')}-{m.get('score2')}",
            m.get("match_type"),
            m.get("status"),
            m.get("started_at"),
            m.get("ended_at"),
            w.get("nickname") if w else "",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name="matches.xlsx")


# ---------- SocketIO ----------
@socketio.on("connect")
def on_connect():
    emit("update", get_screen_data())


@socketio.on("request_update")
def on_request_update():
    emit("update", get_screen_data())


if __name__ == "__main__":
    process_season_and_week()
    os.makedirs(config.DATA_DIR, exist_ok=True)
    ensure_venues_file()
    ensure_table_venue_ids()
    from venue_service import ensure_table_qr_tokens

    ensure_table_qr_tokens()
    print(f"台球天梯系统启动: http://{config.HOST}:{config.PORT}")
    print(f"管理后台: http://127.0.0.1:{config.PORT}/admin")
    print(f"投屏大屏: http://127.0.0.1:{config.PORT}/screen")
    if config.WECHAT_APPID and config.WECHAT_SECRET:
        print(f"微信登录: 已配置 AppID={config.WECHAT_APPID}")
    else:
        print("微信登录: 未就绪 — 请运行 setup-wechat.bat")
        print("  在 wechat.secret.txt 粘贴 AppSecret 后重启本窗口")
    try:
        config.validate_production_secrets()
    except RuntimeError as e:
        if config.DEV_MODE:
            print(f"WARN: {e}")
        else:
            raise
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.FLASK_DEBUG,
        allow_unsafe_werkzeug=True,
    )
