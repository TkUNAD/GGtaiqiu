"""MySQL 文档存储：每个 JSON 集合一行（app_collections）"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymysql

import config

_SCHEMA_READY = False


def connect():
    return pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=config.MYSQL_CONNECT_TIMEOUT,
        read_timeout=30,
        write_timeout=30,
        autocommit=False,
    )


def ensure_schema(conn=None) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_collections (
                    name VARCHAR(64) NOT NULL PRIMARY KEY,
                    data LONGTEXT NOT NULL,
                    updated_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        if own:
            conn.commit()
        _SCHEMA_READY = True
    finally:
        if own:
            conn.close()


def ping() -> Dict[str, Any]:
    conn = connect()
    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
        conn.commit()
        return {"ok": bool(row and row.get("ok") == 1)}
    finally:
        conn.close()


def collection_count(conn=None) -> int:
    own = conn is None
    if own:
        conn = connect()
    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM app_collections")
            row = cur.fetchone() or {}
        if own:
            conn.commit()
        return int(row.get("c") or 0)
    finally:
        if own:
            conn.close()


def list_collections(conn=None) -> List[str]:
    own = conn is None
    if own:
        conn = connect()
    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM app_collections ORDER BY name")
            rows = cur.fetchall() or []
        if own:
            conn.commit()
        return [r["name"] for r in rows]
    finally:
        if own:
            conn.close()


def load_collection(conn, name: str) -> Optional[Any]:
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM app_collections WHERE name=%s", (name,))
        row = cur.fetchone()
    if not row:
        return None
    return json.loads(row["data"])


def save_collection(conn, name: str, data: Any) -> None:
    ensure_schema(conn)
    payload = json.dumps(data, ensure_ascii=False)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_collections (name, data, updated_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE data=VALUES(data), updated_at=VALUES(updated_at)
            """,
            (name, payload, now),
        )


def import_collection(conn, name: str, data: Any) -> None:
    save_collection(conn, name, data)
