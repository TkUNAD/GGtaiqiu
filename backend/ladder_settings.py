"""天梯基础规则：后台可配置，业务逻辑统一从此读取"""
from typing import Any, Dict

from db import load, mutate, save

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
}


def _merge_rules(raw: Dict) -> Dict:
    rules = dict(DEFAULT_LADDER_RULES)
    if raw:
        rules.update({k: raw[k] for k in DEFAULT_LADDER_RULES if k in raw})
    return rules


def get_ladder_rules() -> Dict:
    settings = load("settings")
    return _merge_rules(settings.get("ladder_rules"))


def save_ladder_rules(updates: Dict) -> Dict:
    def _fn(settings):
        current = _merge_rules(settings.get("ladder_rules"))
        for key in DEFAULT_LADDER_RULES:
            if key in updates and updates[key] is not None:
                val = updates[key]
                if key.endswith("_limit") or key.startswith("challenge_rank"):
                    current[key] = int(val)
                elif key.startswith("daily_bonus") or key in (
                    "bonus_review_threshold",
                    "cheat_penalty_points",
                    "cheat_scroll_times",
                ):
                    current[key] = int(val)
                elif key == "beyond_rank_daily_bonus_only" or key == "ranked_over_limit_to_casual":
                    current[key] = bool(val)
                else:
                    current[key] = val
        settings["ladder_rules"] = current
        return settings

    mutate("settings", _fn)
    return get_ladder_rules()


def get_daily_bonus_map() -> Dict[str, int]:
    r = get_ladder_rules()
    return {
        "hour_open": r["daily_bonus_hour_open"],
        "valid_match": r["daily_bonus_valid_match"],
        "break_run": r["daily_bonus_break_run"],
        "clearance": r["daily_bonus_clearance"],
        "break_50": 15,
        "century": 50,
    }
