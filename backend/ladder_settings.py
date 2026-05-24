"""天梯基础规则：总后台默认 + 球房覆盖；六段位积分与可配置段位名称"""
from copy import deepcopy
from typing import Any, Dict, List, Optional

from config import RANK_TIERS
from db import find_by_id, load, mutate


def default_tier_definitions() -> List[Dict]:
    return [
        {"name": t["name"], "min": t["min"], "max": t["max"]}
        for t in RANK_TIERS
    ]


DEFAULT_POINT_RULES = {
    "max_ranked_tier_gap": 1,
    "same_winner_base": 20,
    "same_winner_per_frame": 2,
    "same_loser_base": 15,
    "same_loser_per_frame": 2,
    "low_win_winner_base": 25,
    "low_win_winner_per_frame": 3,
    "low_win_loser_base": 15,
    "low_win_loser_per_frame": 3,
    "high_win_winner_base": 15,
    "high_win_winner_per_frame": 2,
    "high_win_loser_base": 10,
    "high_win_loser_per_frame": 2,
    "casual_winner_bonus": 5,
}

DEFAULT_LADDER_RULES = {
    "challenge_rank_min": 1,
    "challenge_rank_max": 5,
    "beyond_rank_daily_bonus_only": True,
    "daily_ranked_limit": 2,
    "weekly_ranked_limit": 9,
    "ranked_over_limit_to_casual": True,
    "daily_bonus_valid_match": 5,
    "daily_bonus_break_run": 20,
    "daily_bonus_clearance": 15,
    "daily_bonus_hour_open": 8,
    "bonus_review_threshold": 2,
    "cheat_penalty_points": 200,
    "cheat_scroll_times": 3,
    "match_idle_alert_seconds": 600,
    "match_idle_prompt_seconds": 60,
    "match_end_request_seconds": 60,
    "tier_definitions": default_tier_definitions(),
    "point_rules": deepcopy(DEFAULT_POINT_RULES),
    "rule_description": "",
}


def _merge_point_rules(raw: Dict) -> Dict:
    pr = deepcopy(DEFAULT_POINT_RULES)
    if raw:
        for k in DEFAULT_POINT_RULES:
            if k in raw and raw[k] is not None:
                pr[k] = int(raw[k]) if isinstance(raw[k], (int, float)) else raw[k]
    return pr


def _merge_tier_definitions(raw: Optional[List]) -> List[Dict]:
    base = default_tier_definitions()
    if not raw or not isinstance(raw, list):
        return base
    merged = []
    for i, default in enumerate(base):
        item = deepcopy(default)
        if i < len(raw) and isinstance(raw[i], dict):
            src = raw[i]
            if src.get("name"):
                item["name"] = str(src["name"]).strip()
            if src.get("min") is not None:
                item["min"] = int(src["min"])
            if src.get("max") is not None:
                item["max"] = int(src["max"])
        merged.append(item)
    return merged


def _merge_rules(raw: Dict) -> Dict:
    rules = deepcopy(DEFAULT_LADDER_RULES)
    if not raw:
        rules["point_rules"] = _merge_point_rules({})
        rules["tier_definitions"] = default_tier_definitions()
        return rules
    for key in DEFAULT_LADDER_RULES:
        if key in ("point_rules", "tier_definitions"):
            continue
        if key in raw and raw[key] is not None:
            val = raw[key]
            if key.endswith("_limit") or key.startswith("challenge_rank"):
                rules[key] = int(val)
            elif key.startswith("daily_bonus") or key in (
                "bonus_review_threshold",
                "cheat_penalty_points",
                "cheat_scroll_times",
                "match_idle_alert_seconds",
                "match_idle_prompt_seconds",
                "match_end_request_seconds",
            ):
                rules[key] = int(val)
            elif key in ("beyond_rank_daily_bonus_only", "ranked_over_limit_to_casual"):
                rules[key] = bool(val)
            elif key == "rule_description":
                rules[key] = str(val) if val is not None else ""
            else:
                rules[key] = val
    rules["point_rules"] = _merge_point_rules(raw.get("point_rules") or {})
    rules["tier_definitions"] = _merge_tier_definitions(raw.get("tier_definitions"))
    return rules


def build_rule_description(rules: Dict) -> str:
    custom = (rules.get("rule_description") or "").strip()
    if custom:
        return custom
    pr = rules.get("point_rules") or DEFAULT_POINT_RULES
    tiers = rules.get("tier_definitions") or default_tier_definitions()
    tier_line = " → ".join(f"{i + 1}.{t['name']}" for i, t in enumerate(tiers))
    max_gap = int(pr.get("max_ranked_tier_gap", 1))
    lines = [
        "【六段位】" + tier_line,
        "",
        "【排位赛·同段位】胜者 = 基础分 + 局分差×每分加成；败者 = 基础分 + 局分差×每分扣分。",
        f"· 胜者 +{pr.get('same_winner_base')} + 局分差×{pr.get('same_winner_per_frame')}；"
        f"败者 -{pr.get('same_loser_base')} - 局分差×{pr.get('same_loser_per_frame')}",
        "  例：抢5 比分5:3，局分差2 → 胜者+20+4=24，败者-15-4=19（抢7同理）。",
        "",
        "【排位赛·相差1个段位】",
        f"· 低段位胜：+{pr.get('low_win_winner_base')}+局分差×{pr.get('low_win_winner_per_frame')}；"
        f"高段位负：-{pr.get('low_win_loser_base')}-局分差×{pr.get('low_win_loser_per_frame')}",
        f"· 高段位胜：+{pr.get('high_win_winner_base')}+局分差×{pr.get('high_win_winner_per_frame')}；"
        f"低段位负：-{pr.get('high_win_loser_base')}-局分差×{pr.get('high_win_loser_per_frame')}",
        "  例：抢5 比分5:3，局分差2 → 高段胜+15+4=19/低段负-10-4=-14；"
        "  低段胜+25+4=29/高段负-15-4=-19。",
        "",
        f"【段位差≥{max_gap + 1}级】不能打积分赛，仅休闲赛（胜者+{pr.get('casual_winner_bonus')}）。",
        "【炸清/接清】在比赛结束时另行加分（见日常规则）。",
        "【提前结束】上述排位加减分减半。",
        "",
        f"【挑战】可挑战高 {rules.get('challenge_rank_min')}～{rules.get('challenge_rank_max')} 名；"
        f"每日排位 {rules.get('daily_ranked_limit')} 场、每周 {rules.get('weekly_ranked_limit')} 场。",
        "",
        f"【日常】有效局+{rules.get('daily_bonus_valid_match')}；炸清+{rules.get('daily_bonus_break_run')}；"
        f"接清+{rules.get('daily_bonus_clearance')}；开台+{rules.get('daily_bonus_hour_open')}/小时。",
        "",
        f"【闲置】双方无操作 {int(rules.get('match_idle_alert_seconds', 600) // 60)} 分钟后提醒；"
        f"提醒后 {int(rules.get('match_idle_prompt_seconds', 60) // 60)} 分钟内仍无操作则自动结束对局。",
    ]
    return "\n".join(lines)


def get_global_ladder_rules() -> Dict:
    settings = load("settings")
    return _merge_rules(settings.get("ladder_rules"))


def get_ladder_rules(venue_id: Optional[str] = None) -> Dict:
    return get_effective_ladder_rules(venue_id)


def get_effective_ladder_rules(venue_id: Optional[str] = None) -> Dict:
    if venue_id:
        from venue_service import get_venue

        v = get_venue(venue_id)
        if v and v.get("ladder_rules"):
            return _merge_rules(v["ladder_rules"])
    return get_global_ladder_rules()


def save_global_ladder_rules(updates: Dict) -> Dict:
    merged = _merge_rules({**get_global_ladder_rules(), **updates})
    if "point_rules" in updates:
        merged["point_rules"] = _merge_point_rules(updates.get("point_rules"))
    if "tier_definitions" in updates:
        merged["tier_definitions"] = _merge_tier_definitions(updates.get("tier_definitions"))

    def _fn(settings):
        settings["ladder_rules"] = merged
        return settings

    mutate("settings", _fn)
    return get_global_ladder_rules()


def save_ladder_rules(updates: Dict) -> Dict:
    return save_global_ladder_rules(updates)


def save_venue_ladder_rules(venue_id: str, updates: Dict) -> Dict:
    v = find_by_id(load("venues"), venue_id)
    if not v:
        raise ValueError("球房不存在")
    base = _merge_rules(v.get("ladder_rules") or get_global_ladder_rules())
    merged = _merge_rules({**base, **updates})
    if "point_rules" in updates:
        merged["point_rules"] = _merge_point_rules(
            {**(merged.get("point_rules") or {}), **(updates.get("point_rules") or {})}
        )
    if "tier_definitions" in updates:
        merged["tier_definitions"] = _merge_tier_definitions(updates.get("tier_definitions"))

    def _fn(venues):
        v = find_by_id(venues, venue_id)
        if not v:
            raise ValueError("球房不存在")
        v["ladder_rules"] = merged
        from db import now_iso

        v["updated_at"] = now_iso()
        return venues

    mutate("venues", _fn)
    return get_effective_ladder_rules(venue_id)


def sync_venue_ladder_from_global(venue_id: str) -> Dict:
    global_rules = get_global_ladder_rules()

    def _fn(venues):
        v = find_by_id(venues, venue_id)
        if not v:
            raise ValueError("球房不存在")
        v["ladder_rules"] = deepcopy(global_rules)
        from db import now_iso

        v["updated_at"] = now_iso()
        return venues

    mutate("venues", _fn)
    return get_effective_ladder_rules(venue_id)


def get_daily_bonus_map(rules: Optional[Dict] = None) -> Dict[str, int]:
    r = rules or get_global_ladder_rules()
    return {
        "hour_open": r["daily_bonus_hour_open"],
        "valid_match": r["daily_bonus_valid_match"],
        "break_run": r["daily_bonus_break_run"],
        "clearance": r["daily_bonus_clearance"],
        "break_50": 15,
        "century": 50,
    }


def ladder_rules_payload(venue_id: Optional[str] = None) -> Dict[str, Any]:
    rules = get_effective_ladder_rules(venue_id)
    global_rules = get_global_ladder_rules()
    has_custom = False
    if venue_id:
        from venue_service import get_venue

        v = get_venue(venue_id)
        has_custom = bool(v and v.get("ladder_rules"))
    return {
        "rules": rules,
        "global_rules": global_rules,
        "has_custom_rules": has_custom,
        "description": build_rule_description(rules),
        "global_description": build_rule_description(global_rules),
    }
