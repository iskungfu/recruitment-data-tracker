"""importer 测试 — §7：parse_scraper_record / validate_schema_compatibility /
import_json_to_db / import_batch"""

from __future__ import annotations

import json
from datetime import date

import pytest

from core.exceptions import SchemaIncompatibleError
from importers.boss_importer import (
    import_batch,
    import_json_to_db,
    parse_scraper_record,
    read_scraper_json,
    validate_schema_compatibility,
)

DATE = date(2026, 9, 23)


class TestParseScraperRecord:
    def test_monthly_15xin(self, sample_scraper_json):
        records = read_scraper_json(sample_scraper_json)
        job = parse_scraper_record(records[0], city_id=1, snapshot_date=DATE)
        assert job.encrypt_job_id == "sample-encrypt-0001"
        assert job.job_name == "后端开发工程师"
        assert job.salary_raw == "30-60K·15薪"
        assert (job.salary_min, job.salary_max) == (30.0, 60.0)
        assert job.year_multiplier == 15
        assert job.salary_unit == "month"
        assert job.education == "本科"
        assert job.experience == "3-5年"
        assert job.company_name == "示例科技有限公司"
        assert job.skill_tags == ["Java", "Spring"]
        assert job.platform == "BOSS"
        assert job.snapshot_date == DATE

    def test_daily_salary_null_min_max(self, sample_scraper_json):
        records = read_scraper_json(sample_scraper_json)
        job = parse_scraper_record(records[2], city_id=1, snapshot_date=DATE)
        assert job.salary_unit == "day"
        assert job.salary_min is None and job.salary_max is None
        assert job.year_multiplier is None
        assert job.salary_raw == "500-550元/天"
        assert job.education is None  # "学历不限" → None

    def test_bad_salary_keeps_record(self):
        """薪资解析失败不丢整条记录：原文保留，数值置空"""
        raw = {
            "title": "岗位",
            "salary": "面议",
            "location": "北京·朝阳区",
            "encrypt_job_id": "x1",
        }
        job = parse_scraper_record(raw, city_id=1, snapshot_date=DATE)
        assert job.salary_raw == "面议"
        assert job.salary_min is None
        assert job.salary_unit == "month"

    def test_missing_encrypt_id_raises(self):
        with pytest.raises(SchemaIncompatibleError):
            parse_scraper_record({"title": "无 ID"}, city_id=1, snapshot_date=DATE)

    def test_w1_preresearch_format(self):
        """W1 预研样本格式（裸字段）也能解析"""
        raw = {
            "job_name": "后端开发工程师",
            "salary_raw": "25-35K·14薪",
            "city": "北京",
            "company": "某公司",
            "degree_required": "本科及以上",
            "experience_required": "3-5年",
            "source_job_id": "w1-0001",
            "skill_tags": ["Java", "MySQL"],
        }
        job = parse_scraper_record(raw, city_id=1, snapshot_date=DATE)
        assert job.encrypt_job_id == "w1-0001"
        assert job.year_multiplier == 14
        assert job.education == "本科"
        assert job.experience == "3-5年"
        assert job.skill_tags == ["Java", "MySQL"]


class TestValidateSchemaCompatibility:
    def test_real_format_passes(self, sample_scraper_json):
        compat = validate_schema_compatibility(sample_scraper_json)
        assert all(compat.values())

    def test_missing_fields_detected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"jobs": [{"foo": 1}]}), encoding="utf-8")
        compat = validate_schema_compatibility(bad)
        assert compat["encrypt_job_id"] is False
        assert compat["salary_raw"] is False

    def test_import_incompatible_raises(self, tmp_path, db_conn):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"jobs": [{"foo": 1}]}), encoding="utf-8")
        with pytest.raises(SchemaIncompatibleError):
            import_json_to_db(bad, city_id=1, snapshot_date=DATE, conn=db_conn)


class TestImportJsonToDb:
    def test_end_to_end_insert_count(self, db_conn, sample_scraper_json):
        new = import_json_to_db(sample_scraper_json, city_id=1, snapshot_date=DATE, conn=db_conn)
        assert new == 3
        rows = db_conn.execute(
            "SELECT job_name, salary_min, salary_max, year_multiplier, salary_unit, "
            "city_id, company_name, education, experience FROM job_snapshot ORDER BY encrypt_job_id"
        ).fetchall()
        assert len(rows) == 3
        r0 = rows[0]
        assert r0["job_name"] == "后端开发工程师"
        assert (r0["salary_min"], r0["salary_max"]) == (30.0, 60.0)
        assert r0["year_multiplier"] == 15
        assert r0["salary_unit"] == "month"
        assert r0["city_id"] == 1
        assert r0["education"] == "本科"

    def test_import_batch_by_city_lookup(self, db_conn, sample_scraper_json, city_id_lookup):
        result = import_batch([sample_scraper_json], city_id_lookup, DATE, db_conn)
        assert result == {"total": 3, "new": 3, "duplicates": 0}
