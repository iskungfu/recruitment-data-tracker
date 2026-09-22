"""数据库连接 — 03-module-interfaces.md §4"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """创建连接，自动开启 WAL / 外键 / busy_timeout，row_factory = sqlite3.Row"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """上下文管理器: 自动 commit / rollback"""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
