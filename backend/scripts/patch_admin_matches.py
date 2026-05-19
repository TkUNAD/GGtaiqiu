import re
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "app.py"
text = p.read_text(encoding="utf-8")
pattern = re.compile(
    r"def admin_matches\(\):\s+"
    r"matches = load\(\"matches\"\)\s+"
    r"users = load\(\"users\"\)\s+"
    r"matches\.sort\(key=lambda x: x\.get\(\"started_at\", \"\"\), reverse=True\)\s+"
    r"result = \[\]\s+"
    r"for m in matches\[:500\]:\s+"
    r"p1 = find_by_id\(users, m\[\"player1_id\"\]\)\s+"
    r"p2 = find_by_id\(users, m\[\"player2_id\"\]\)\s+"
    r"result\.append\(\{\*\*m, \"p1_name\": p1\.get\(\"nickname\"\) if p1 else \"\", \"p2_name\": p2\.get\(\"nickname\"\) if p2 else \"\"\}\)\s+"
    r"return _ok\(result\)",
    re.MULTILINE,
)
new = """def admin_matches():
    from match_bonus import enrich_match_for_admin

    matches = load("matches")
    matches.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return _ok([enrich_match_for_admin(m) for m in matches[:500]])"""
m = pattern.search(text)
if not m:
    raise SystemExit("pattern not found")
p.write_text(text[: m.start()] + new + text[m.end() :], encoding="utf-8")
print("patched")
