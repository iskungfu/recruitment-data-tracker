"""数据访问对象 — 03-module-interfaces.md §5"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from core.models import DirectionStats, JobSnapshot, Snapshot
from storage.connection import transaction

_INSERT_JOBS_SQL = """
INSERT OR IGNORE INTO job_snapshot (
    job_id, job_name, salary_raw, salary_min, salary_max,
    year_multiplier, salary_unit, city_id, company_name,
    education, experience, jd_fulltext, skill_tags,
    platform, encrypt_job_id, snapshot_date
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def insert_snapshot_meta(conn: sqlite3.Connection, snap: Snapshot) -> int:
    """插入 snapshots 表元信息，返回新 ID"""
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO snapshots (
                snapshot_date, keyword_id, city_id, city_name, keyword,
                status, started_at, completed_at, job_count, error_log
            ) VALUES (
                ?, ?, ?,
                (SELECT name FROM cities WHERE id = ?),
                (SELECT keyword FROM keywords WHERE id = ?),
                ?, ?, ?, ?, ?
            )
            """,
            (
                snap.snapshot_date.isoformat(),
                snap.keyword_id,
                snap.city_id,
                snap.city_id,
                snap.keyword_id,
                snap.status,
                snap.started_at.isoformat(sep=" ") if snap.started_at else None,
                snap.completed_at.isoformat(sep=" ") if snap.completed_at else None,
                snap.job_count,
                snap.error_log,
            ),
        )
    return int(cur.lastrowid)


def update_snapshot_status(
    conn: sqlite3.Connection, snap_id: int, status: str, error: str | None = None
) -> None:
    """更新采集任务状态；done/failed 时写 completed_at"""
    completed = datetime.now().isoformat(sep=" ") if status in ("done", "failed") else None
    with transaction(conn):
        conn.execute(
            """
            UPDATE snapshots
               SET status = ?, error_log = COALESCE(?, error_log),
                   completed_at = COALESCE(?, completed_at)
             WHERE id = ?
            """,
            (status, error, completed, snap_id),
        )


def get_existing_keys(conn: sqlite3.Connection, snapshot_date: date) -> set[tuple[str, date]]:
    """查询当天的 (encrypt_job_id, snapshot_date) 集合，用于去重预判"""
    rows = conn.execute(
        "SELECT encrypt_job_id, snapshot_date FROM job_snapshot WHERE snapshot_date = ?",
        (snapshot_date.isoformat(),),
    ).fetchall()
    return {(row["encrypt_job_id"], date.fromisoformat(row["snapshot_date"])) for row in rows}


def insert_jobs_batch(conn: sqlite3.Connection, jobs: list[JobSnapshot]) -> int:
    """批量 INSERT OR IGNORE（UPSERT 语义：重复键跳过），返回新插入数量"""
    if not jobs:
        return 0
    before = conn.total_changes
    with transaction(conn):
        conn.executemany(_INSERT_JOBS_SQL, [job.to_db_tuple() for job in jobs])
    return conn.total_changes - before


def get_jobs_by_snapshot(conn: sqlite3.Connection, snapshot_date: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM job_snapshot WHERE snapshot_date = ? ORDER BY id",
        (snapshot_date.isoformat(),),
    ).fetchall()


def get_jobs_by_date_range(
    conn: sqlite3.Connection, start: date, end: date
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM job_snapshot WHERE snapshot_date BETWEEN ? AND ? ORDER BY id",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def get_jobs_by_city_and_date(
    conn: sqlite3.Connection, city_id: int, day: date
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM job_snapshot WHERE city_id = ? AND snapshot_date = ? ORDER BY id",
        (city_id, day.isoformat()),
    ).fetchall()


def get_snapshot_stats(conn: sqlite3.Connection, snapshot_date: date) -> dict:
    """健康检查用：返回当天每城记录数与关键字段空值率"""
    rows = conn.execute(
        """
        SELECT c.name AS city, COUNT(*) AS n,
               SUM(CASE WHEN j.salary_min IS NULL THEN 1 ELSE 0 END) AS null_salary,
               SUM(CASE WHEN j.jd_fulltext IS NULL THEN 1 ELSE 0 END) AS null_jd
          FROM job_snapshot j
          LEFT JOIN cities c ON c.id = j.city_id
         WHERE j.snapshot_date = ?
         GROUP BY j.city_id
        """,
        (snapshot_date.isoformat(),),
    ).fetchall()
    by_city = {
        row["city"]: {
            "count": row["n"],
            "null_salary_rate": row["null_salary"] / row["n"] if row["n"] else 0.0,
            "null_jd_rate": row["null_jd"] / row["n"] if row["n"] else 0.0,
        }
        for row in rows
    }
    total = sum(v["count"] for v in by_city.values())
    return {"snapshot_date": snapshot_date.isoformat(), "total": total, "by_city": by_city}


def get_direction_stats_for_quarter(
    conn: sqlite3.Connection, direction: str, year: int, quarter: int
) -> DirectionStats:
    """某方向某季度的聚合统计 — Week 3 分析层实现。

    注意：job_snapshot 不直接存 keyword/direction，方向归属需经 snapshots
    表 (snapshot_date, city_id) 关联，而同日同城可能有多个关键词的采集任务，
    归属口径需在 Week 3 与 ADR 对齐后实现，本函数暂为占位。
    """
    raise NotImplementedError("方向季度聚合属 Week 3 范围（analysis/stats.py）")
