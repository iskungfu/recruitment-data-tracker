"""建表与种子数据 — 03-module-interfaces.md §13 / 02-database-erd.md §6

用法：
    python -m storage.schema            # 在 data/recruitment.db 建库 + 种子数据
    python -m storage.schema <db_path>  # 指定数据库路径
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from storage.connection import get_connection, transaction

MIGRATION_DIR = Path(__file__).parent / "migrations"
INITIAL_MIGRATION = MIGRATION_DIR / "0001_initial.sql"
DEFAULT_DB_PATH = Path("data/recruitment.db")

EXPECTED_TABLES = ("schema_version", "cities", "keywords", "snapshots", "job_snapshot")


def create_tables(conn: sqlite3.Connection) -> None:
    """执行初始迁移（DDL + 种子数据，全部 INSERT OR IGNORE，可重复执行）"""
    sql = INITIAL_MIGRATION.read_text(encoding="utf-8")
    with transaction(conn):
        conn.executescript(sql)


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    """建库入口：创建 4 表 + schema_version + 种子数据，返回 db 路径"""
    db_path = Path(db_path)
    conn = get_connection(db_path)
    try:
        create_tables(conn)
    finally:
        conn.close()
    return db_path


def verify_db(conn: sqlite3.Connection) -> dict[str, int]:
    """验收辅助：返回各表行数；缺表抛异常"""
    counts: dict[str, int] = {}
    for table in EXPECTED_TABLES:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        counts[table] = int(row["c"])
    return counts


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    db_path = Path(argv[0]) if argv else DEFAULT_DB_PATH
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        counts = verify_db(conn)
    finally:
        conn.close()
    print(f"数据库已初始化: {db_path}")
    for table, count in counts.items():
        print(f"  {table}: {count} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
