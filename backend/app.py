"""台球天梯系统 - Flask + SocketIO 主入口"""
import io
import os
from datetime import datetime
from functools import wraps

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
    super_admin_required,
)
from anti_cheat import punish_user
from db import find_by_id, load, mutate, now_iso, save
from ladder_settings import get_ladder_rules, save_ladder_rules
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
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def _ok(data=None, msg="ok"):
    return jsonify({"code": 0, "msg": msg, "data": data})


def _err(msg, code=1):
    return jsonify({"code": code, "msg": msg, "data": None}), 400


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
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    session.clear()
    ensure_venues_file()

    if username == config.ADMIN_USER and password == config.ADMIN_PASS:
        session["admin_logged_in"] = True
        session["admin_role"] = "super"
        session["admin_username"] = username
        return _ok(build_admin_session_info())

    venue = authenticate_venue(username, password)
    if venue:
        from venue_service import is_member_active, venue_permissions

        session["admin_logged_in"] = True
        session["admin_role"] = "venue"
        session["venue_id"] = venue["id"]
        session["admin_username"] = username
        session["permissions"] = venue_permissions(venue)
        info = build_admin_session_info()
        if not is_member_active(venue):
            info["member_tip"] = "球房会员已过期，仅可查看基础数据；开通后可管理桌台、修改天梯规则、屏蔽手机端广告"
        return _ok(info)

    return _err("账号或密码错误")


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return _ok()


@app.route("/api/admin/me")
@admin_required
def admin_me():
    return _ok(build_admin_session_info())


@app.route("/api/venue/status")
def venue_status_api():
    venue_id = request.args.get("venue_id", DEFAULT_VENUE_ID)
    return _ok(mobile_venue_status(venue_id))


@app.route("/api/settings/ladder")
def public_ladder_rules():
    return _ok(get_ladder_rules())


# ---------- 微信登录 ----------
@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json() or {}
    code = data.get("code", "")
    if not code:
        return _err("缺少 code")
    openid, err = wx_code_to_openid(code)
    if not openid:
        return _err(err or "登录失败")
    try:
        user = get_or_create_user(
            openid,
            nickname=data.get("nickname", ""),
            avatar=data.get("avatar", ""),
            phone=data.get("phone", ""),
            ip=_client_ip(),
        )
    except ValueError as e:
        return _err(str(e))
    tier = get_tier(user["score"])
    users = load("users")
    rank = get_user_rank(users, user["id"])
    return _ok({
        "token": openid,
        "user": {**user, "tier": tier, "rank": rank},
    })


def _user_from_token():
    token = request.headers.get("X-Token") or request.args.get("token")
    if not token:
        return None
    users = load("users")
    return next((u for u in users if u.get("openid") == token), None)


# ---------- 天梯榜 ----------
@app.route("/api/rank/list")
def rank_list():
    process_season_and_week()
    limit = int(request.args.get("limit", 50))
    users = load("users")
    board = build_leaderboard(users, limit=limit)
    return _ok(board)


@app.route("/api/rank/challenge-targets")
def challenge_targets():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    rules = get_ladder_rules()
    rmin = rules["challenge_rank_min"]
    rmax = rules["challenge_rank_max"]
    users = load("users")
    my_rank = get_user_rank(users, user["id"])
    board = build_leaderboard(users, limit=my_rank)
    targets = []
    for item in board:
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
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    users = load("users")
    result = [
        {"id": u["id"], "nickname": u.get("nickname", "球友"), "score": u.get("score", 1000)}
        for u in users
        if u.get("status") != "banned"
    ]
    return _ok(result)


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
    from table_queue import build_table_view

    token = request.args.get("qr_token", "")
    tables = load("tables")
    t = find_by_id(tables, table_id)
    if not t:
        return _err("桌台不存在")
    expected = t.get("qr_token") or ""
    if expected and expected != (token or ""):
        return _err("二维码无效")
    user = _user_from_token()
    view = build_table_view(t, user["id"] if user else None)
    return _ok(view)


@app.route("/api/table/<table_id>/join", methods=["POST"])
def table_join(table_id):
    from table_queue import build_table_view, join_table

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    data = request.get_json(silent=True) or {}
    try:
        view = join_table(table_id, user["id"], data.get("qr_token", ""))
        _broadcast()
        return _ok(view)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/table/<table_id>/race", methods=["POST"])
def table_set_race(table_id):
    from table_queue import set_waiting_race

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    data = request.get_json(silent=True) or {}
    try:
        view = set_waiting_race(table_id, user["id"], int(data.get("race_to", 5)))
        _broadcast()
        return _ok(view)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/table/<table_id>/leave", methods=["POST"])
def table_leave(table_id):
    from table_queue import leave_table

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
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
        return _err("请先登录", 401), 401
    data = request.get_json(silent=True) or {}
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


# ---------- 对局 ----------
@app.route("/api/match/start", methods=["POST"])
def match_start():
    """兼容旧版；请使用 /api/table/<id>/start"""
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
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


@app.route("/api/match/<match_id>")
def match_detail(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    matches = load("matches")
    m = find_by_id(matches, match_id)
    if not m:
        return _err("对局不存在")
    if user["id"] not in (m.get("player1_id"), m.get("player2_id")):
        return _err("无权查看该对局", 403), 403
    users = load("users")
    p1 = find_by_id(users, m["player1_id"])
    p2 = find_by_id(users, m["player2_id"])
    from match_bonus import enrich_match_display, get_pending_for_user

    pending = get_pending_for_user(m, user["id"])
    display = enrich_match_display(m)
    return _ok({**m, "p1": p1, "p2": p2, "bonus_pending_list": pending, **display})


@app.route("/api/match/<match_id>/frame", methods=["POST"])
def match_frame(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    data = request.get_json() or {}
    action = data.get("action")
    try:
        m = record_frame(match_id, user["id"], action)
        from match_bonus import enrich_match_display, get_pending_for_user

        pending = get_pending_for_user(m, user["id"])
        users = load("users")
        p1 = find_by_id(users, m["player1_id"])
        p2 = find_by_id(users, m["player2_id"])
        display = enrich_match_display(m)
        _broadcast()
        return _ok({**m, "p1": p1, "p2": p2, "bonus_pending_list": pending, **display})
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/finish", methods=["POST"])
def match_finish(match_id):
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    matches = load("matches")
    m0 = find_by_id(matches, match_id)
    if not m0:
        return _err("对局不存在")
    if user["id"] not in (m0.get("player1_id"), m0.get("player2_id")):
        return _err("非本局玩家", 403), 403
    data = request.get_json() or {}
    completed = data.get("completed", True)
    s1, s2 = m0.get("score1", 0), m0.get("score2", 0)
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
        return _ok(m)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/bonus/request", methods=["POST"])
def match_bonus_request(match_id):
    from match_bonus import get_pending_for_user, request_bonus

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    data = request.get_json(silent=True) or {}
    try:
        item = request_bonus(match_id, user["id"], data.get("type"))
        m = find_by_id(load("matches"), match_id)
        _broadcast()
        users = load("users")
        claimer = find_by_id(users, user["id"]) or {}
        item_out = dict(item)
        item_out["claimer_name"] = claimer.get("nickname", "球友")
        return _ok({"item": item_out, "pending": get_pending_for_user(m, user["id"])})
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/bonus/confirm", methods=["POST"])
def match_bonus_confirm(match_id):
    from match_bonus import get_pending_for_user, confirm_bonus

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    data = request.get_json(silent=True) or {}
    try:
        result = confirm_bonus(match_id, user["id"], data.get("bonus_id"))
        m = result["match"]
        _broadcast()
        return _ok({
            "item": result["item"],
            "pending": get_pending_for_user(m, user["id"]),
            "applied": result["item"].get("status") == "applied",
        })
    except ValueError as e:
        return _err(str(e))


@app.route("/api/match/<match_id>/bonus/reject", methods=["POST"])
def match_bonus_reject(match_id):
    from match_bonus import get_pending_for_user, reject_bonus

    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
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
        return _err("请先登录", 401), 401
    m = find_by_id(load("matches"), match_id)
    if not m:
        return _err("对局不存在")
    if user["id"] not in (m.get("player1_id"), m.get("player2_id")):
        return _err("无权查看该对局", 403), 403
    if m.get("status") not in ("finished", "invalid"):
        return _err("对局未结束")
    summary = m.get("summary") or build_match_summary(m)
    return _ok(summary)


# ---------- 个人中心 ----------
@app.route("/api/user/profile")
def user_profile():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
    users = load("users")
    tier = get_tier(user["score"])
    rank = get_user_rank(users, user["id"])
    total = user.get("wins", 0) + user.get("losses", 0)
    win_rate = round(user.get("wins", 0) / total * 100, 1) if total else 0
    matches = [m for m in load("matches") if user["id"] in (m.get("player1_id"), m.get("player2_id"))]
    matches.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    logs = [l for l in load("score_logs") if l.get("user_id") == user["id"]][-50:]
    logs.reverse()
    return _ok({
        "user": user,
        "tier": tier,
        "rank": rank,
        "win_rate": win_rate,
        "recent_matches": matches[:20],
        "score_logs": logs,
    })


@app.route("/api/user/bind-phone", methods=["POST"])
def bind_phone():
    user = _user_from_token()
    if not user:
        return _err("请先登录", 401), 401
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
        return _err("请先登录", 401), 401
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
        return _err("请先登录", 401), 401
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
    return _ok(get_ladder_rules())


@app.route("/api/admin/settings/ladder", methods=["PUT"])
@member_permission_required("ladder_settings")
def admin_save_ladder_settings():
    data = request.get_json(silent=True) or {}
    rules = save_ladder_rules(data)
    return _ok(rules)


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
        if data.get("winner_id"):
            m = finish_match(match_id, data["winner_id"], completed=data.get("completed", True))
        else:

            def _approve(ms):
                item = find_by_id(ms, match_id)
                if not item:
                    raise ValueError("对局不存在")
                item["status"] = "approved"
                item["review_note"] = data.get("note", "")
                return ms

            try:
                mutate("matches", _approve)
            except ValueError as e:
                return _err(str(e))
            m = find_by_id(load("matches"), match_id)
            table_id = m.get("table_id") if m else None
            if table_id:
                t = find_by_id(load("tables"), table_id)
                if t and t.get("current_match_id") == match_id:
                    _release_table(table_id)
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
        def _modify(ms):
            item = find_by_id(ms, match_id)
            if not item:
                raise ValueError("对局不存在")
            if data.get("winner_id"):
                item["winner_id"] = data["winner_id"]
            item["score1"] = data.get("score1", item["score1"])
            item["score2"] = data.get("score2", item["score2"])
            item["status"] = "modified"
            item["review_note"] = data.get("note", "")
            return ms

        try:
            mutate("matches", _modify)
        except ValueError as e:
            return _err(str(e))
        m = find_by_id(load("matches"), match_id)
        table_id = m.get("table_id") if m else None
        if table_id:
            t = find_by_id(load("tables"), table_id)
            if t and t.get("current_match_id") == match_id:
                _release_table(table_id)
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

    users = filter_users_for_venue(
        load("users"), session.get("venue_id"), is_super_admin()
    )
    board = build_leaderboard(users, limit=1000, include_hidden=True)
    rank_map = {b["id"]: b["rank"] for b in board}
    for u in users:
        u["rank"] = rank_map.get(u["id"], 9999)
        u["tier"] = get_tier(u.get("score", 1000))
    return _ok(users)


@app.route("/api/admin/user/<user_id>/score", methods=["POST"])
@admin_required
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
def admin_punish(user_id):
    from admin_scope import assert_user_in_venue
    from admin_auth import is_super_admin

    try:
        assert_user_in_venue(user_id, session.get("venue_id"), is_super_admin())
    except ValueError as e:
        return _err(str(e))
    data = request.get_json() or {}
    punish_user(user_id, data.get("action", "warn"), data.get("reason", ""), data.get("public", True))
    _broadcast()
    return _ok()


@app.route("/api/admin/user/<user_id>", methods=["DELETE"])
@admin_required
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
        return _err("球房未开通会员，无法管理桌台", 403), 403
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
        tid = f"T{next_num:02d}"
        token = f"table_{tid}"
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


def _assert_table_access(table: dict):
    if is_super_admin():
        return
    if table.get("venue_id", DEFAULT_VENUE_ID) != session.get("venue_id"):
        raise ValueError("无权操作该桌台")
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
            _assert_table_access(t)
        except ValueError as e:
            return _err(str(e), 403), 403
    try:
        import qrcode
    except ImportError:
        return _err("请安装 qrcode: pip install qrcode[pil]"), 500

    from io import BytesIO

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
def admin_open_table(table_id):
    t = find_by_id(load("tables"), table_id)
    if t:
        try:
            _assert_table_access(t)
        except ValueError as e:
            return _err(str(e), 403), 403
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
        return _err(str(e), 403), 403


@app.route("/api/admin/products", methods=["GET", "POST"])
@admin_required
def admin_products():
    from admin_auth import is_super_admin

    if request.method == "GET":
        return _ok(load("products"))
    if not is_super_admin():
        return _err("仅总后台可添加或修改商品", 403), 403
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
@super_admin_required
def admin_delete_score_log(log_id):
    from services import delete_score_logs

    try:
        result = delete_score_logs([log_id])
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/logs/score/batch-delete", methods=["POST"])
@super_admin_required
def admin_batch_delete_score_logs():
    from services import delete_score_logs

    data = request.get_json(silent=True) or {}
    try:
        result = delete_score_logs(data.get("log_ids") or [])
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@app.route("/api/admin/logs/score")
@admin_required
def admin_score_logs():
    from admin_auth import is_super_admin
    from admin_scope import filter_score_logs_for_venue

    logs = filter_score_logs_for_venue(
        load("score_logs"), session.get("venue_id"), is_super_admin()
    )
    users = load("users")
    logs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    for l in logs[:1000]:
        u = find_by_id(users, l.get("user_id"))
        l["nickname"] = u.get("nickname") if u else ""
    return _ok(logs[:1000])


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
    print(f"台球天梯系统启动: http://{config.HOST}:{config.PORT}")
    print(f"管理后台: http://127.0.0.1:{config.PORT}/admin")
    print(f"投屏大屏: http://127.0.0.1:{config.PORT}/screen")
    socketio.run(app, host=config.HOST, port=config.PORT, debug=True, allow_unsafe_werkzeug=True)
