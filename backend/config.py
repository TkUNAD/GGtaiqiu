import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ROOT_DIR = os.path.dirname(BASE_DIR)

# 与 miniprogram/project.config.json 中 appid 保持一致
DEFAULT_WECHAT_APPID = "wx4056ce1b5ca29798"


def _load_dotenv():
    """从项目根目录或 backend 目录加载 .env（空值可被文件覆盖）"""
    for base in (ROOT_DIR, BASE_DIR):
        path = os.path.join(base, ".env")
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if not key:
                    continue
                cur = os.environ.get(key, "")
                if key not in os.environ or not str(cur).strip():
                    os.environ[key] = val


_PLACEHOLDER_SECRETS = frozenset({
    "",
    "your_app_secret_here",
    "在此填写你的AppSecret",
})


def _read_wechat_secret_from_file():
    """从 wechat.secret.txt 读取 AppSecret（优先级最高）"""
    for base in (ROOT_DIR, BASE_DIR):
        path = os.path.join(base, "wechat.secret.txt")
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if line not in _PLACEHOLDER_SECRETS:
                        return line
    return ""


def _load_wechat_secret_file():
    secret = _read_wechat_secret_from_file()
    if secret:
        os.environ["WECHAT_SECRET"] = secret


_load_dotenv()
_load_wechat_secret_file()

try:
    from config_local import WECHAT_SECRET as _LOCAL_WX_SECRET  # noqa: F401
    if _LOCAL_WX_SECRET and str(_LOCAL_WX_SECRET).strip():
        os.environ["WECHAT_SECRET"] = str(_LOCAL_WX_SECRET).strip()
except ImportError:
    pass

DEFAULT_SECRET_KEY = "billiards-ladder-secret-2026"
DEFAULT_JWT_SECRET = "billiards-jwt-secret-change-me"
SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)
JWT_SECRET = os.environ.get("JWT_SECRET", SECRET_KEY if SECRET_KEY != DEFAULT_SECRET_KEY else DEFAULT_JWT_SECRET)
JWT_ACCESS_EXPIRE_SECONDS = int(os.environ.get("JWT_ACCESS_EXPIRE_SECONDS", 7200))
JWT_REFRESH_EXPIRE_SECONDS = int(os.environ.get("JWT_REFRESH_EXPIRE_SECONDS", 2592000))
ADMIN_USER = os.environ.get("ADMIN_USER", "cca10")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
PUBLIC_URL = (os.environ.get("PUBLIC_URL", "https://ggtaiqiu.com") or "https://ggtaiqiu.com").rstrip("/")
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        f"{PUBLIC_URL},http://127.0.0.1:5000,http://localhost:5000",
    ).split(",")
    if o.strip()
]

# 微信小程序 AppID / AppSecret（用 code 换 openid 必填；头像昵称由前端传入，不在后端拉取）
WECHAT_APPID = os.environ.get("WECHAT_APPID", DEFAULT_WECHAT_APPID) or DEFAULT_WECHAT_APPID
# 最终以 wechat.secret.txt 为准，避免 .env 空值或重复粘贴导致读不到
WECHAT_SECRET = _read_wechat_secret_from_file() or (os.environ.get("WECHAT_SECRET", "") or "").strip()
if WECHAT_SECRET:
    os.environ["WECHAT_SECRET"] = WECHAT_SECRET

# 开发模式：无微信 AppID 时可用 code 模拟 openid（正式环境请保持 false 并配置 AppID）
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() in ("1", "true", "yes")

# 小程序码版本：release / trial / develop；留空则按 release→trial→develop 依次尝试
WX_QR_ENV_VERSION = (os.environ.get("WX_QR_ENV_VERSION", "") or "").strip().lower()

# 微信云托管容器（Dockerfile 中 WX_CLOUD_RUN=1）；未配齐密钥时先 WARN 避免启动即退出
WX_CLOUD_RUN = os.environ.get("WX_CLOUD_RUN", "").lower() in ("1", "true", "yes")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 5000))


def _parse_mysql_address(addr: str):
    host, port = "", 3306
    raw = (addr or "").strip()
    if not raw:
        return host, port
    if ":" in raw:
        host, port_s = raw.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            port = 3306
    else:
        host = raw
    return host.strip(), port


_mysql_host = os.environ.get("MYSQL_HOST", "").strip()
_mysql_port = int(os.environ.get("MYSQL_PORT", "3306") or 3306)
if not _mysql_host:
    _addr_host, _addr_port = _parse_mysql_address(os.environ.get("MYSQL_ADDRESS", ""))
    if _addr_host:
        _mysql_host = _addr_host
        _mysql_port = _addr_port

MYSQL_HOST = _mysql_host
MYSQL_PORT = _mysql_port
MYSQL_USER = (
    os.environ.get("MYSQL_USER") or os.environ.get("MYSQL_USERNAME") or ""
).strip()
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "").strip()
MYSQL_CONNECT_TIMEOUT = int(os.environ.get("MYSQL_CONNECT_TIMEOUT", "10"))
_use_mysql_env = os.environ.get("USE_MYSQL", "").lower() in ("1", "true", "yes")
USE_MYSQL = _use_mysql_env or bool(MYSQL_HOST and MYSQL_USER and MYSQL_DATABASE)

INITIAL_SCORE = 1000
EXCHANGE_MIN_SCORE = 2000  # 低于此积分不可兑换
EXCHANGE_DAILY_LIMIT = 1  # 每人每日兑换次数上限
MIN_MATCH_SECONDS = 120  # 对局过短判无效
MATCH_IDLE_ALERT_SECONDS = 600  # 双方无操作 10 分钟后弹出提醒
MATCH_IDLE_PROMPT_SECONDS = 60  # 提醒框 1 分钟无操作自动结束
MATCH_END_REQUEST_SECONDS = 60  # 结束请求对方 1 分钟无操作自动结束
PERMANENT_BAN_VIOLATION_COUNT = 3  # 恶意刷分/作弊达此次数永久封禁
# 炸清/接清申报、本局胜/负 共用操作冷却（秒）
MATCH_ACTION_COOLDOWN = 20
# 60 秒内达到此次数的炸清/接清/胜/负操作触发积分审核冻结
SCORE_REVIEW_WINDOW_SEC = 60
SCORE_REVIEW_ACTION_THRESHOLD = 2
# 后台审核超时自动通过（小时）
REVIEW_AUTO_APPROVE_HOURS = 24
WIN_LOSE_COOLDOWN = MATCH_ACTION_COOLDOWN
# 备战区心跳超时：停留在备战页时轮询续期；断线/关小程序后最长保留（秒）
TABLE_WAITING_PRESENCE_SEC = 120
# 切到后台后客户端延迟离场（与占坑时长一致，秒）
TABLE_WAITING_BACKGROUND_SEC = 60
# SAME_IP_MAX_ACCOUNTS 已停用，见 anti_cheat.check_ip_limit
SAME_IP_MAX_ACCOUNTS = 0
DAILY_SCORE_ALERT = 200
INACTIVE_PENALTY_PER_DAY = 5
INACTIVE_DAYS_START = 7
HIDE_RANK_DAYS = 30

DAILY_RANKED_LIMIT = 2
WEEKLY_RANKED_LIMIT = 9
CHALLENGE_RANK_MIN = 1
CHALLENGE_RANK_MAX = 5

def validate_production_secrets() -> None:
    """非开发模式时禁止使用默认密钥"""
    if DEV_MODE:
        return
    problems = []
    if SECRET_KEY == DEFAULT_SECRET_KEY:
        problems.append("SECRET_KEY 仍为默认值")
    if JWT_SECRET in (DEFAULT_JWT_SECRET, DEFAULT_SECRET_KEY):
        problems.append("JWT_SECRET 仍为默认值")
    if problems:
        msg = "生产环境安全配置未就绪: " + "; ".join(problems) + "。请在云托管「服务设置」配置环境变量。"
        if WX_CLOUD_RUN:
            print(f"WARN [WX_CLOUD_RUN]: {msg}")
            print("WARN: 请尽快设置 SECRET_KEY、JWT_SECRET、WECHAT_SECRET 后重新发布。")
            return
        raise RuntimeError(msg + " 请配置 .env 或环境变量。")
    if ADMIN_PASS == "admin123":
        print("WARN: ADMIN_PASS 仍为默认 admin123，生产环境建议在后台修改为强密码。")
    try:
        from db import load as _load_tables
        from venue_service import ensure_table_qr_tokens

        tables = _load_tables("tables")
        weak = [
            t.get("id")
            for t in tables
            if not (t.get("qr_token") or "").strip()
            or str(t.get("qr_token", "")).startswith(("table_", "table_T"))
        ]
        if weak:
            ensure_table_qr_tokens()
            print(
                f"WARN: 已自动轮换 {len(weak)} 张桌台的弱 qr_token，请重新打印球台二维码。"
            )
    except Exception as e:
        print(f"WARN: qr_token 检查跳过: {e}")


RANK_TIERS = [
    {"name": "新锐学徒", "min": 1000, "max": 1199, "stars": 5},
    {"name": "业余球手", "min": 1200, "max": 1399, "stars": 5},
    {"name": "资深球友", "min": 1400, "max": 1599, "stars": 5},
    {"name": "赛场好手", "min": 1600, "max": 1799, "stars": 5},
    {"name": "实力战将", "min": 1800, "max": 1999, "stars": 5},
    {"name": "殿堂球王", "min": 2000, "max": 99999, "stars": 5},
]
