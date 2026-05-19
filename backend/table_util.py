"""桌台二维码链接工具"""
from typing import Dict


def default_qr_link(table: Dict) -> str:
    tid = table.get("id", "")
    token = table.get("qr_token") or f"table_{tid}"
    return f"pages/table/table?table_id={tid}&qr_token={token}"


def enrich_table(table: Dict) -> Dict:
    t = dict(table)
    if not t.get("qr_link"):
        t["qr_link"] = default_qr_link(t)
    return t


def enrich_tables(tables: list) -> list:
    return [enrich_table(t) for t in tables]
