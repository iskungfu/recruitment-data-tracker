"""去重测试 — 验收清单：dedup_jobs + DB UNIQUE 双重去重"""

from __future__ import annotations

from datetime import date

from core.cleansing import dedup_jobs
from core.models import JobSnapshot

DATE = date(2026, 9, 23)


def _job(encrypt_id: str, day: date = DATE) -> JobSnapshot:
    return JobSnapshot(
        job_id=encrypt_id,
        encrypt_job_id=encrypt_id,
        job_name="测试岗位",
        salary_raw="10-20K",
        salary_min=10.0,
        salary_max=20.0,
        year_multiplier=None,
        snapshot_date=day,
    )


class TestDedupJobs:
    def test_removes_db_existing(self):
        jobs = [_job("a"), _job("b")]
        existing = {("a", DATE)}
        result = dedup_jobs(jobs, existing)
        assert [j.encrypt_job_id for j in result] == ["b"]

    def test_removes_intra_batch_duplicates(self):
        jobs = [_job("a"), _job("a"), _job("b")]
        result = dedup_jobs(jobs, set())
        assert [j.encrypt_job_id for j in result] == ["a", "b"]

    def test_same_id_different_date_kept(self):
        other = date(2026, 6, 30)
        jobs = [_job("a", DATE), _job("a", other)]
        result = dedup_jobs(jobs, set())
        assert len(result) == 2

    def test_empty_input(self):
        assert dedup_jobs([], set()) == []


class TestDbUniqueConstraint:
    """第二层：INSERT OR IGNORE + UNIQUE(encrypt_job_id, snapshot_date)"""

    def test_reimport_same_file_yields_zero(self, db_conn, sample_scraper_json):
        from importers.boss_importer import import_json_to_db

        first = import_json_to_db(sample_scraper_json, city_id=1, snapshot_date=DATE, conn=db_conn)
        assert first == 3
        second = import_json_to_db(sample_scraper_json, city_id=1, snapshot_date=DATE, conn=db_conn)
        assert second == 0
