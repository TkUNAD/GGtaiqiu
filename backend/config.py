import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

SECRET_KEY = os.environ.get("SECRET_KEY", "billiards-ladder-secret-2026")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")

# 微信小程序（上传前在环境变量或此处填写）
WECHAT_APPID = os.environ.get("WECHAT_APPID", "")
WECHAT_SECRET = os.environ.get("WECHAT_SECRET", "")

# 开发模式：无微信 AppID 时可用 code 模拟 openid（正式环境请保持 false 并配置 AppID）
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() in ("1", "true", "yes")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 5000))

INITIAL_SCORE = 1000
EXCHANGE_MIN_SCORE = 2000  # 低于此积分不可兑换
EXCHANGE_DAILY_LIMIT = 1  # 每人每日兑换次数上限
MIN_MATCH_SECONDS = 120  # 对局过短判无效
WIN_LOSE_COOLDOWN = 60
SAME_IP_MAX_ACCOUNTS = 2
DAILY_SCORE_ALERT = 200
INACTIVE_PENALTY_PER_DAY = 5
INACTIVE_DAYS_START = 7
HIDE_RANK_DAYS = 30

DAILY_RANKED_LIMIT = 2
WEEKLY_RANKED_LIMIT = 9
CHALLENGE_RANK_MIN = 1
CHALLENGE_RANK_MAX = 5

RANK_TIERS = [
    {"name": "新锐学徒", "min": 1000, "max": 1199, "stars": 5},
    {"name": "业余球手", "min": 1200, "max": 1399, "stars": 5},
    {"name": "资深球友", "min": 1400, "max": 1599, "stars": 5},
    {"name": "赛场好手", "min": 1600, "max": 1799, "stars": 5},
    {"name": "实力战将", "min": 1800, "max": 1999, "stars": 5},
    {"name": "殿堂球王", "min": 2000, "max": 99999, "stars": 5},
]
