"""schema / 种子数据测试 — §14 验收：4 表 + schema_version + 种子行数"""

from __future__ import annotations


class TestSchema:
    def test_five_tables_exist(self, db_conn):
        tables = {
            r["name"]
            for r in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"snapshots", "keywords", "cities", "job_snapshot", "schema_version"} <= tables

    def test_seed_cities_5_rows(self, db_conn):
        rows = db_conn.execute("SELECT name FROM cities ORDER BY id").fetchall()
        assert len(rows) == 5
        assert {r["name"] for r in rows} == {"北京", "上海", "深圳", "杭州", "成都"}

    def test_seed_keywords_34_rows(self, db_conn):
        """34 行 = PRD §3.1 裁决口径（前端 3 词：前端/Vue/React，不含 JavaScript）"""
        assert db_conn.execute("SELECT COUNT(*) c FROM keywords").fetchone()["c"] == 34

    def test_job_snapshot_unique_constraint(self, db_conn):
        """UNIQUE(encrypt_job_id, snapshot_date) 约束存在"""
        indexes = db_conn.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name='job_snapshot' AND sql IS NOT NULL"
        ).fetchall()
        ddl = " ".join(r["sql"] for r in indexes).lower()
        assert "encrypt_job_id" in ddl and "unique" in ddl

    def test_ddl_has_year_multiplier_and_salary_unit(self, db_conn):
        ddl = db_conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='job_snapshot'"
        ).fetchone()["sql"].lower()
        assert "year_multiplier" in ddl
        assert "salary_unit" in ddl

    def test_create_tables_idempotent(self, db_conn):
        """迁移可重复执行（IF NOT EXISTS + INSERT OR IGNORE）"""
        from storage.schema import create_tables

        create_tables(db_conn)
        assert db_conn.execute("SELECT COUNT(*) c FROM keywords").fetchone()["c"] == 34
        assert db_conn.execute("SELECT COUNT(*) c FROM cities").fetchone()["c"] == 5
