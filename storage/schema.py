"""建表与种子数据 — 03-module-interfaces.md §13 / 02-database-erd.md §6

用法：
    python -m storage.schema            # 在 data/recruitment.db 建库 + 种子数据
    python -m storage.schema <db_path>  # 指定数据库路径
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from storage.connection import get_connection, transaction

MIGRATION_DIR = Path(__file__).parent / "migrations"
INITIAL_MIGRATION = MIGRATION_DIR / "0001_initial.sql"
DEFAULT_DB_PATH = Path("data/recruitment.db")

EXPECTED_TABLES = ("schema_version", "cities", "keywords", "snapshots", "job_snapshot")

_VERSION_RE = re.compile(r"^(\d+)_")


def create_tables(conn: sqlite3.Connection) -> None:
    """执行初始迁移（DDL + 种子数据，全部 INSERT OR IGNORE，可重复执行），
    再按版本号补执行后续迁移（0002+）"""
    sql = INITIAL_MIGRATION.read_text(encoding="utf-8")
    with transaction(conn):
        conn.executescript(sql)
    apply_pending_migrations(conn)


#: 匹配迁移语句里的 ALTER TABLE ... ADD COLUMN <列名>（幂等检查用）
_ADD_COLUMN_RE = re.compile(
    r"^ALTER\s+TABLE\s+(?P<table>\"[^\"]+\"|\w+)\s+ADD\s+COLUMN\s+(?P<column>\"[^\"]+\"|\w+)",
    re.IGNORECASE,
)


def _migration_statements(sql: str) -> list[str]:
    """迁移 SQL → 语句列表（按分号拆分，跳过整行 -- 注释）。

    本仓库迁移为简单风格：整行注释 + 分号结尾语句，无内联注释 / 触发器，
    拆分规则与之一一对应。
    """
    stmts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                stmts.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        stmts.append(tail)
    return stmts


def apply_migration_script(conn: sqlite3.Connection, sql: str) -> None:
    """逐语句执行一段迁移 SQL，幂等且不留半迁移状态（P3-5 修复）。

    - ALTER ADD COLUMN 语句执行前先 PRAGMA table_info 检查，列已存在 → 跳过
      （关闭「两条 ALTER 之间中断 → 重跑报 duplicate column」的半迁移窗口）；
    - 整段包在事务里：任一语句失败整体回滚，不会留下列已加、版本未记的中间态。
    """
    with transaction(conn):
        for stmt in _migration_statements(sql):
            m = _ADD_COLUMN_RE.match(stmt)
            if m:
                table = m.group("table").strip('"')
                column = m.group("column").strip('"')
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column in existing:
                    continue
            conn.execute(stmt)


def apply_pending_migrations(conn: sqlite3.Connection) -> None:
    """按版本号顺序执行 0001 之后的迁移。

    schema_version 表记录已应用版本，重复执行自动跳过（幂等）。
    0001 为初始建表（含自身版本记录），不走本函数。
    实际执行交给 apply_migration_script（列存在跳过 + 事务包裹）。
    """
    applied = {int(row[0]) for row in conn.execute("SELECT version FROM schema_version")}
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        m = _VERSION_RE.match(path.name)
        if not m:
            continue
        version = int(m.group(1))
        if version <= 1 or version in applied:
            continue
        apply_migration_script(conn, path.read_text(encoding="utf-8"))


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
