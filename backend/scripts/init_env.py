"""生成或补全项目根目录 .env 中的 SECRET_KEY / JWT_SECRET / ADMIN_PASS"""
import os
import re
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(ROOT, ".env")

REQUIRED_KEYS = ("SECRET_KEY", "JWT_SECRET", "ADMIN_USER", "ADMIN_PASS")
DEFAULTS = {
    "SECRET_KEY": "billiards-ladder-secret-2026",
    "JWT_SECRET": "billiards-jwt-secret-change-me",
}
PLACEHOLDER_PATTERNS = (
    re.compile(r"请替换", re.I),
    re.compile(r"change-me", re.I),
    re.compile(r"your_", re.I),
)


def _parse_env(path: str) -> dict:
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def _needs_replace(key: str, val: str) -> bool:
    if not val:
        return True
    if key in DEFAULTS and val == DEFAULTS[key]:
        return True
    if key == "ADMIN_PASS" and val:
        return False
    for pat in PLACEHOLDER_PATTERNS:
        if pat.search(val):
            return True
    return False


def _generate(key: str) -> str:
    if key == "ADMIN_USER":
        return "admin"
    if key == "ADMIN_PASS":
        return secrets.token_urlsafe(12)
    return secrets.token_urlsafe(32)


def main() -> int:
    existing = _parse_env(ENV_PATH)
    updates = {}
    for key in REQUIRED_KEYS:
        val = existing.get(key, "")
        if _needs_replace(key, val):
            updates[key] = _generate(key)

    if not updates and os.path.isfile(ENV_PATH):
        print(f".env OK: {ENV_PATH}")
        return 0

    lines = []
    if os.path.isfile(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    present = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                present.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in present:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f"{key}={val}\n")

    if not os.path.isfile(ENV_PATH):
        new_lines = [
            "# Auto-generated security settings\n",
            *[f"{k}={v}\n" for k, v in updates.items()],
            "DEV_MODE=false\n",
            "FLASK_DEBUG=false\n",
            "PUBLIC_URL=https://ggtaiqiu.com\n",
            "CORS_ORIGINS=https://ggtaiqiu.com,http://127.0.0.1:5000,http://localhost:5000\n",
        ]

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Updated {ENV_PATH}")
    if "ADMIN_PASS" in updates:
        print(f"  ADMIN_USER={updates.get('ADMIN_USER', existing.get('ADMIN_USER', 'admin'))}")
        print(f"  ADMIN_PASS={updates['ADMIN_PASS']}")
        print("  Save the password above; it will not be shown again.")
    else:
        print("  Added/updated:", ", ".join(updates.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
