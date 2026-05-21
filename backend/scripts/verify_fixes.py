"""验证 P0/P1 修复：对局结算、兑换退款、每日限额"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import EXCHANGE_DAILY_LIMIT, EXCHANGE_MIN_SCORE, INITIAL_SCORE
from db import find_by_id, load, mutate, new_id, save
from services import (
    cancel_pending_exchanges_for_users,
    exchange_product,
    finish_match,
    start_match,
)


def test_winner_validation():
    mid = new_id("M")
    p1, p2 = new_id("u"), new_id("u")
    matches = load("matches")
    matches.append({
        "id": mid,
        "table_id": "T01",
        "player1_id": p1,
        "player2_id": p2,
        "race_to": 5,
        "score1": 3,
        "score2": 1,
        "match_type": "casual",
        "ranked_valid": True,
        "status": "playing",
        "started_at": "2020-01-01T00:00:00",
        "ended_at": None,
        "winner_id": None,
        "completed": False,
        "half_points": False,
        "last_action_at": {},
        "bonuses": [],
        "bonus_pending": [],
    })
    save("matches", matches)
    users = load("users")
    for uid in (p1, p2):
        if not find_by_id(users, uid):
            users.append({
                "id": uid,
                "nickname": "t",
                "score": INITIAL_SCORE,
                "status": "active",
                "wins": 0,
                "losses": 0,
                "openid": f"o_{uid}",
            })
    save("users", users)
    try:
        finish_match(mid, new_id("u"), completed=True)
        assert False, "应拒绝非法胜者"
    except ValueError as e:
        assert "胜者" in str(e)
    print("ok winner validation")


def test_idempotent_finish():
    matches = load("matches")
    playing = [m for m in matches if m.get("status") == "playing"]
    if not playing:
        print("skip idempotent (no playing match)")
        return
    m = playing[0]
    mid = m["id"]

    def _ensure_score(ms):
        item = find_by_id(ms, mid)
        if item and item.get("score1", 0) == item.get("score2", 0):
            item["score1"] = 5
            item["score2"] = 2
        return ms

    mutate("matches", _ensure_score)
    m = find_by_id(load("matches"), mid)
    w = m["player1_id"] if m.get("score1", 0) > m.get("score2", 0) else m["player2_id"]
    s_before = find_by_id(load("users"), w)["score"]
    finish_match(mid, w, completed=True)
    s1 = find_by_id(load("users"), w)["score"]
    finish_match(m["id"], w, completed=True)
    s2 = find_by_id(load("users"), w)["score"]
    assert s1 == s2, "重复 finish 不应重复加分"
    print("ok idempotent finish", s_before, "->", s2)


def test_ranked_start_match():
    tid = new_id("T")
    p1, p2 = new_id("u"), new_id("u")
    tables = load("tables")
    tables.append({
        "id": tid,
        "name": "排位测试桌",
        "venue_id": "default",
        "opened": True,
        "opened_at": "2020-01-01T00:00:00",
        "waiting_players": [],
        "current_match_id": None,
        "qr_token": "qr",
    })
    save("tables", tables)
    users = load("users")
    for uid in (p1, p2):
        if not find_by_id(users, uid):
            users.append({
                "id": uid,
                "nickname": "t",
                "score": 2000,
                "status": "active",
                "wins": 0,
                "losses": 0,
                "openid": f"o_{uid}",
            })
    save("users", users)
    m = start_match(tid, p1, p2, 5, "ranked")
    assert m.get("match_type") in ("ranked", "casual")

    def _clean_tables(ts):
        return [x for x in ts if x.get("id") != tid]

    mutate("tables", _clean_tables)

    def _clean_matches(ms):
        return [x for x in ms if x.get("id") != m["id"]]

    mutate("matches", _clean_matches)
    print("ok ranked start_match", m.get("match_type"))


def test_table_closes_on_finish():
    tid = new_id("T")
    p1, p2 = new_id("u"), new_id("u")
    tables = load("tables")
    tables.append({
        "id": tid,
        "name": "关台测试桌",
        "venue_id": "default",
        "opened": True,
        "opened_at": "2020-01-01T00:00:00",
        "opened_by_scan": True,
        "waiting_players": [],
        "current_match_id": None,
        "qr_token": "qt",
    })
    save("tables", tables)
    users = load("users")
    for uid in (p1, p2):
        if not find_by_id(users, uid):
            users.append({
                "id": uid,
                "nickname": "t",
                "score": INITIAL_SCORE,
                "status": "active",
                "wins": 0,
                "losses": 0,
                "openid": f"o_{uid}",
            })
    save("users", users)
    m = start_match(tid, p1, p2, 5, "casual")

    def _score(ms):
        item = find_by_id(ms, m["id"])
        if item:
            item["score1"] = 5
            item["score2"] = 3
        return ms

    mutate("matches", _score)
    finish_match(m["id"], p1, completed=True)
    t = find_by_id(load("tables"), tid)
    assert not t.get("opened"), "对局结束后桌台应关台"
    assert not t.get("current_match_id"), "应释放当前对局"
    assert not (t.get("waiting_players") or []), "应清空等候区"

    def _clean_tables(ts):
        return [x for x in ts if x.get("id") != tid]

    mutate("tables", _clean_tables)

    def _clean_matches(ms):
        return [x for x in ms if x.get("id") != m["id"]]

    mutate("matches", _clean_matches)
    print("ok table closes on finish")


def test_exchange_refund_on_cancel():
    uid = new_id("U")
    pid = new_id("P")
    users = load("users")
    users.append({
        "id": uid,
        "openid": f"o_{uid}",
        "nickname": "兑换测试",
        "score": 2500,
        "status": "active",
        "wins": 0,
        "losses": 0,
    })
    save("users", users)

    products = load("products")
    products.append({
        "id": pid,
        "name": "测试商品",
        "type": "实物",
        "points": 100,
        "stock": 10,
        "enabled": True,
        "desc": "",
    })
    save("products", products)

    exchange_product(uid, pid)
    score_after = find_by_id(load("users"), uid)["score"]
    assert score_after == 2500 - 100

    cancel_pending_exchanges_for_users([uid], "测试退款")
    score_refund = find_by_id(load("users"), uid)["score"]
    assert score_refund == 2500, f"待审核取消应退分，实际 {score_refund}"

  # cleanup
    def _clean_ex(exs):
        return [e for e in exs if e.get("user_id") != uid]

    mutate("exchanges", _clean_ex)

    def _clean_u(us):
        return [u for u in us if u.get("id") != uid]

    mutate("users", _clean_u)

    def _clean_p(ps):
        return [p for p in ps if p.get("id") != pid]

    mutate("products", _clean_p)
    print("ok exchange refund on cancel")


def test_exchange_daily_limit():
    uid = new_id("U")
    pid = new_id("P")
    users = load("users")
    users.append({
        "id": uid,
        "openid": f"o_{uid}",
        "nickname": "限额测试",
        "score": EXCHANGE_MIN_SCORE + 500,
        "status": "active",
        "wins": 0,
        "losses": 0,
    })
    save("users", users)

    products = load("products")
    products.append({
        "id": pid,
        "name": "限额商品",
        "type": "实物",
        "points": 50,
        "stock": 10,
        "enabled": True,
        "desc": "",
    })
    save("products", products)

    exchange_product(uid, pid)
    try:
        exchange_product(uid, pid)
        assert False, "应拒绝超出每日兑换次数"
    except ValueError as e:
        assert "上限" in str(e) or str(EXCHANGE_DAILY_LIMIT) in str(e)

    def _clean_ex(exs):
        return [e for e in exs if e.get("user_id") != uid]

    mutate("exchanges", _clean_ex)
    cancel_pending_exchanges_for_users([uid], "测试清理")

    def _clean_u(us):
        return [u for u in us if u.get("id") != uid]

    mutate("users", _clean_u)

    def _clean_p(ps):
        return [p for p in ps if p.get("id") != pid]

    mutate("products", _clean_p)
    print("ok exchange daily limit")


def test_jwt_issue_verify():
    from auth_tokens import issue_tokens, verify_access_token

    users = load("users")
    if not users:
        print("skip jwt (no users)")
        return
    u = users[0]
    bundle = issue_tokens(u)
    uid = verify_access_token(bundle["access_token"])
    assert uid == u["id"], "JWT sub 应为用户 id"
    print("ok jwt issue/verify")


def test_delete_playing_match_rejected():
    from services import delete_matches

    mid = new_id("M")
    p1, p2 = new_id("u"), new_id("u")
    matches = load("matches")
    matches.append({
        "id": mid,
        "table_id": "T01",
        "player1_id": p1,
        "player2_id": p2,
        "status": "playing",
        "score1": 0,
        "score2": 0,
    })
    save("matches", matches)
    try:
        delete_matches([mid], venue_id=None, is_super=True)
        assert False, "应拒绝删除进行中"
    except ValueError as e:
        assert "进行中" in str(e)
    matches = load("matches")
    save("matches", [m for m in matches if m.get("id") != mid])
    print("ok delete playing rejected")


if __name__ == "__main__":
    test_winner_validation()
    test_idempotent_finish()
    test_ranked_start_match()
    test_table_closes_on_finish()
    test_exchange_refund_on_cancel()
    test_exchange_daily_limit()
    test_jwt_issue_verify()
    test_delete_playing_match_rejected()
    print("all checks passed")
