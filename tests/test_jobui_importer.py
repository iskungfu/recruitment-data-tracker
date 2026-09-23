"""职友集 importer 测试 — 薪资换算 K（裁决口径）/ 原文照存 / 来源列写入 /
城市 NULL 容错 / 迁移幂等 / CLI 入口

薪资五类口径（组长裁决 2026-09-23，追裁决 (a) 统一 K 落库）：
  元区间 "35000-50000元" → 35.0/50.0 K；K 区间 "8-15k" → 8.0/15.0 K；
  "面议" → min/max NULL；"8000元以上" → 仅 salary_min=8.0 K；
  "150-200元/天"（低值≤200）→ unit='day' + min/max NULL。
"""

from __future__ import annotations

import json

import pytest

from importers.jobui_importer import (
    ensure_source_columns,
    import_batch,
    import_json_to_db,
    main,
    parse_jobui_record,
    parse_jobui_salary,
)
from storage.schema import apply_pending_migrations
from tests.conftest import SNAPSHOT_DATE

DATE = SNAPSHOT_DATE


def _job(salary: str, **overrides) -> dict:
    raw = {
        "job_id": "900000099",
        "title": "后端开发",
        "salary": salary,
        "experience": "3-5年",
        "education": "本科以上",
        "company_name": "中科软科技股份有限公司",
        "detail_url": "https://www.jobui.com/job/900000099/",
        "add_date": "1天前",
    }
    raw.update(overrides)
    return raw


def _write_json(tmp_path, jobs, city="北京", name="jobui_jobs_北京_后端.json"):
    payload = {
        "platform": "JOBUI", "source_platform": "www.jobui.com",
        "keyword": "后端", "city": city, "total": len(jobs), "jobs": jobs,
    }
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestParseJobuiSalary:
    """薪资归一化 —— 裁决口径五类情况各一条 + 真实样本补充格式"""

    def test_yuan_range_divides_1000(self):
        s = parse_jobui_salary("35000-50000元")
        assert (s.min, s.max) == (35.0, 50.0)
        assert s.unit == "month"
        assert s.year_multiplier == 12

    def test_k_range_multiplies_1(self):
        s = parse_jobui_salary("8-15k")
        assert (s.min, s.max) == (8.0, 15.0)
        assert s.unit == "month"
        assert s.year_multiplier == 12

    def test_negotiable_to_null(self):
        s = parse_jobui_salary("面议")
        assert s.min is None and s.max is None
        assert s.unit == "month"

    def test_above_only_min(self):
        s = parse_jobui_salary("8000元以上")
        assert s.min == 8.0
        assert s.max is None
        assert s.unit == "month"

    def test_day_salary_low_le_200(self):
        """低值 ≤200 元/天 → unit='day'、min/max NULL（对齐 BOSS 日薪语义）"""
        s = parse_jobui_salary("150-200元/天")
        assert s.unit == "day"
        assert s.min is None and s.max is None
        assert s.year_multiplier is None

    @pytest.mark.parametrize("raw,expected", [
        ("40000-70000", (40.0, 70.0)),   # 裸数字（真实样本 13 条为此格式）→ 元 ÷1000
        ("1.5-1.6万", (15.0, 16.0)),      # 万 → ×10 K
        ("1.2-1.5万", (12.0, 15.0)),
        ("15-25K", (15.0, 25.0)),         # 大写 K
        ("1.5万以上", (15.0, None)),       # 万以上 → 仅 min
        ("8k以上", (8.0, None)),          # k以上 → 仅 min
    ])
    def test_real_sample_variants(self, raw, expected):
        s = parse_jobui_salary(raw)
        assert (s.min, s.max) == expected
        assert s.unit == "month"

    def test_unparseable_keeps_raw_and_record(self):
        s = parse_jobui_salary("薪资丰厚")
        assert s.min is None and s.max is None
        assert s.raw == "薪资丰厚"
        assert s.unit == "month"  # 不丢整条记录

    def test_single_value_day_salary(self):
        """P3-3 回归：单值日薪 "200元/天" 不再落入默认 month 分支。

        对齐区间日薪语义：unit='day'、min/max 不折算（置空）。
        """
        s = parse_jobui_salary("200元/天")
        assert s.unit == "day"
        assert s.min is None and s.max is None
        assert s.year_multiplier is None
        assert s.raw == "200元/天"

    @pytest.mark.parametrize("raw", ["300/天", "150.5元/天"])
    def test_single_day_variants(self, raw):
        """P3-3 回归：省略"元"与小数写法同口径"""
        assert parse_jobui_salary(raw).unit == "day"


class TestParseJobuiRecord:
    """edu/exp 原文照存 + encrypt 前缀 + 来源站字段 + jd 统一 NULL"""

    def test_edu_kept_verbatim(self):
        job = parse_jobui_record(_job("8-15k"), city_id=1, snapshot_date=DATE)
        assert job.education == "本科以上"       # 不归一化为"本科"（裁决：原文照存）

    def test_exp_kept_verbatim(self):
        job = parse_jobui_record(
            _job("8-15k", experience="不限经验"), city_id=1, snapshot_date=DATE
        )
        assert job.experience == "不限经验"

    def test_encrypt_job_id_prefix(self):
        job = parse_jobui_record(_job("8-15k"), city_id=1, snapshot_date=DATE)
        assert job.encrypt_job_id == "jobui_900000099"
        assert job.platform == "JOBUI"
        assert job.jd_fulltext is None           # 详情页为跳转页，统一 NULL

    def test_source_fields(self):
        job = parse_jobui_record(_job("8-15k"), city_id=1, snapshot_date=DATE)
        assert job.source_platform == "www.jobui.com"
        assert job.source_url == "https://www.jobui.com/job/900000099/"

    def test_job_id_fallback_from_detail_url(self):
        raw = _job("8-15k")
        raw.pop("job_id")
        job = parse_jobui_record(raw, city_id=1, snapshot_date=DATE)
        assert job.encrypt_job_id == "jobui_900000099"


class TestEnsureSourceColumns:
    def test_create_tables_applies_migration_0002(self, db_conn):
        """新库经 create_tables 初始化即含两列，schema_version 记录版本 2"""
        cols = {r["name"] for r in db_conn.execute("PRAGMA table_info(job_snapshot)")}
        assert {"source_platform", "source_url"} <= cols
        versions = {r["version"] for r in db_conn.execute("SELECT version FROM schema_version")}
        assert 2 in versions

    def test_legacy_db_auto_migrates(self, db_conn):
        """0002 之前的旧库（列被删）首次导入时自动补列"""
        db_conn.execute("ALTER TABLE job_snapshot DROP COLUMN source_platform")
        db_conn.execute("ALTER TABLE job_snapshot DROP COLUMN source_url")
        ensure_source_columns(db_conn)
        cols = {r["name"] for r in db_conn.execute("PRAGMA table_info(job_snapshot)")}
        assert {"source_platform", "source_url"} <= cols

    def test_idempotent(self, db_conn):
        ensure_source_columns(db_conn)  # 已有列，直接返回，不重复 ALTER
        ensure_source_columns(db_conn)
        cols = {r["name"] for r in db_conn.execute("PRAGMA table_info(job_snapshot)")}
        assert {"source_platform", "source_url"} <= cols

    def test_half_migrated_db_recovers_via_apply_pending(self, db_conn):
        """P3-5 回归：两条 ALTER 之间中断（第一列已加、版本未记）→
        重跑 apply_pending_migrations 不再报 duplicate column，且补齐缺口。"""
        db_conn.execute("ALTER TABLE job_snapshot DROP COLUMN source_platform")
        db_conn.execute("ALTER TABLE job_snapshot DROP COLUMN source_url")
        db_conn.execute("DELETE FROM schema_version WHERE version = 2")
        # 模拟半迁移：第一条 ALTER 成功后进程中断（版本未记、source_url 未加）
        db_conn.execute("ALTER TABLE job_snapshot ADD COLUMN source_platform TEXT")
        db_conn.commit()

        apply_pending_migrations(db_conn)  # 旧实现此处抛 duplicate column name

        cols = {r["name"] for r in db_conn.execute("PRAGMA table_info(job_snapshot)")}
        assert "source_url" in cols
        versions = {r["version"] for r in db_conn.execute("SELECT version FROM schema_version")}
        assert 2 in versions

    def test_half_migrated_healed_by_ensure_source_columns(self, db_conn):
        """P3-5 回归：importer 侧自愈——列在但版本未记时重放迁移（跳过已有列）"""
        db_conn.execute("ALTER TABLE job_snapshot DROP COLUMN source_url")
        db_conn.execute("DELETE FROM schema_version WHERE version = 2")
        db_conn.commit()

        ensure_source_columns(db_conn)

        cols = {r["name"] for r in db_conn.execute("PRAGMA table_info(job_snapshot)")}
        assert "source_url" in cols
        versions = {r["version"] for r in db_conn.execute("SELECT version FROM schema_version")}
        assert 2 in versions


class TestImportCountsP3:
    """P3-2 回归：duplicates = 解析成功总数 - 新插入数，不混入解析失败条目"""

    def test_duplicates_exclude_parse_failures(self, db_conn, tmp_path, city_id_lookup):
        bad = _job("8-15k")
        bad.pop("job_id")
        bad.pop("detail_url")          # 无 job_id 且无 detail_url → 解析失败跳过
        path = _write_json(
            tmp_path,
            [_job("8-15k"), _job("20-30k", job_id="900000100"), bad],
        )
        result = import_batch([path], city_id_lookup, DATE, db_conn)
        assert result["total"] == 3            # 原始 3 条
        assert result["new"] == 2              # 可解析的 2 条全部新插入
        assert result["duplicates"] == 0       # 解析失败不计入重复（旧口径会算成 1）

        result2 = import_batch([path], city_id_lookup, DATE, db_conn)
        assert result2["new"] == 0
        assert result2["duplicates"] == 2       # 重复只含可解析的 2 条
        assert result2["total"] == 3


class TestImportJsonToDb:
    def test_end_to_end_source_columns_written(self, db_conn, tmp_path):
        """端到端：入库后 source_platform/source_url 列可读，薪资为 K 口径"""
        path = _write_json(tmp_path, [_job("35000-50000元")])
        new, parsed = import_json_to_db(path, city_id=1, snapshot_date=DATE, conn=db_conn)
        assert new == 1
        assert parsed == 1
        row = db_conn.execute(
            "SELECT * FROM job_snapshot WHERE encrypt_job_id = 'jobui_900000099'"
        ).fetchone()
        assert row is not None
        assert (row["salary_min"], row["salary_max"]) == (35.0, 50.0)
        assert row["platform"] == "JOBUI"
        assert row["source_platform"] == "www.jobui.com"
        assert row["source_url"] == "https://www.jobui.com/job/900000099/"
        assert row["jd_fulltext"] is None
        assert row["year_multiplier"] == 12

    def test_salary_units_mixed_in_same_table(self, db_conn, tmp_path):
        """与 BOSS 同表不同来源：K 口径一致，day 行 min/max NULL——跨平台对比前提"""
        boss_row = {
            "title": "BOSS 后端", "salary": "30-60K", "location": "北京·朝阳区",
            "tags": "3-5年 | 本科", "boss_name": "BOSS 公司",
            "encrypt_job_id": "boss-x1", "skills": "",
        }
        boss_payload = {"keyword": "后端", "city": "北京", "total": 1, "jobs": [boss_row]}
        boss_path = tmp_path / "boss_jobs_北京_后端.json"
        boss_path.write_text(json.dumps(boss_payload, ensure_ascii=False), encoding="utf-8")
        from importers.boss_importer import import_json_to_db as boss_import

        assert boss_import(boss_path, city_id=1, snapshot_date=DATE, conn=db_conn) == 1

        jobui_path = _write_json(tmp_path, [_job("8-15k")])
        assert import_json_to_db(jobui_path, city_id=1, snapshot_date=DATE, conn=db_conn) == (1, 1)

        rows = db_conn.execute(
            "SELECT platform, salary_min, salary_max FROM job_snapshot ORDER BY platform"
        ).fetchall()
        assert [dict(r) for r in rows] == [
            {"platform": "BOSS", "salary_min": 30.0, "salary_max": 60.0},
            {"platform": "JOBUI", "salary_min": 8.0, "salary_max": 15.0},
        ]

    def test_unknown_city_inserts_null_city_id(self, db_conn, tmp_path, city_id_lookup):
        """裁决口径：城市未匹配 → city_id NULL 照常入库（不丢记录）"""
        path = _write_json(tmp_path, [_job("8-15k")], city="乌鲁木齐")
        result = import_batch([path], city_id_lookup, DATE, db_conn)
        assert result["new"] == 1
        assert result["unknown_city"] == 1
        row = db_conn.execute(
            "SELECT city_id, encrypt_job_id FROM job_snapshot"
        ).fetchone()
        assert row["city_id"] is None
        assert row["encrypt_job_id"] == "jobui_900000099"

    def test_import_batch_known_city(self, db_conn, tmp_path, city_id_lookup):
        path = _write_json(tmp_path, [_job("8-15k"), _job("20-30k", job_id="900000100")])
        result = import_batch([path], city_id_lookup, DATE, db_conn)
        assert result == {"total": 2, "new": 2, "duplicates": 0, "unknown_city": 0}

    def test_reimport_same_day_dedups(self, db_conn, tmp_path):
        path = _write_json(tmp_path, [_job("8-15k")])
        assert import_json_to_db(path, city_id=1, snapshot_date=DATE, conn=db_conn) == (1, 1)
        assert import_json_to_db(path, city_id=1, snapshot_date=DATE, conn=db_conn) == (0, 1)


class TestCliMain:
    def test_cli_end_to_end(self, db_conn_fixture_path, tmp_path):
        """python -m importers.jobui_importer 可用：入库 + 退出码 0"""
        db_path, = db_conn_fixture_path,
        path = _write_json(tmp_path, [_job("8-15k")])
        rc = main([str(path), "--db", str(db_path), "--date", "2026-09-23"])
        assert rc == 0
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM job_snapshot").fetchone()
            assert row["encrypt_job_id"] == "jobui_900000099"
            assert row["source_platform"] == "www.jobui.com"
        finally:
            conn.close()

    def test_cli_missing_db_friendly_error(self, tmp_path, capsys):
        """缺失 DB → 友好报错退出码 1，不静默建库（对齐 P2 修复口径）"""
        path = _write_json(tmp_path, [_job("8-15k")])
        rc = main([str(path), "--db", str(tmp_path / "no_such.db")])
        assert rc == 1
        assert "不存在" in capsys.readouterr().err


@pytest.fixture()
def db_conn_fixture_path(tmp_path):
    """真实文件 DB（CLI main 自开连接，需落盘路径）"""
    from storage.schema import init_db

    return init_db(tmp_path / "cli_test.db")
