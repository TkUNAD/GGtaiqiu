"""桌台二维码链接工具"""
from typing import Dict, Optional, Tuple

from wx_miniprogram_qr import MAX_SCENE_LEN


def default_qr_link(table: Dict) -> str:
    tid = table.get("id", "")
    token = table.get("qr_token") or f"table_{tid}"
    return f"pages/table/table?table_id={tid}&qr_token={token}"


def table_qr_scene(table: Dict) -> str:
    """微信小程序码 scene：T01:token（最长 32 字符）"""
    tid = (table.get("id") or "").strip()
    token = (table.get("qr_token") or f"table_{tid}").strip()
    scene = f"{tid}:{token}"
    if len(scene) > MAX_SCENE_LEN:
        raise ValueError(
            f"桌台 {tid} 的二维码 scene 超过 {MAX_SCENE_LEN} 字符，请在后台缩短 Token"
        )
    return scene


def parse_table_qr_scene(scene: str) -> Optional[Tuple[str, str]]:
    raw = (scene or "").strip()
    if not raw or ":" not in raw:
        return None
    tid, token = raw.split(":", 1)
    if not tid or not token:
        return None
    return tid, token


def enrich_table(table: Dict) -> Dict:
    t = dict(table)
    if not t.get("qr_link"):
        t["qr_link"] = default_qr_link(t)
    return t


def enrich_tables(tables: list) -> list:
    return [enrich_table(t) for t in tables]
