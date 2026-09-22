"""同比 / 环比计算测试 — §9：分母 NULL / 0 → NULL"""

from __future__ import annotations

from datetime import date

import pytest

from analysis.stats import calculate_yoy_qoq
from core.models import DirectionStats


def _stats(job_count: int, salary_min: float | None, salary_max: float | None,
           day: date = date(2026, 9, 23)) -> DirectionStats:
    return DirectionStats(
        direction="后端", snapshot_date=day, city_name="北京",
        job_count=job_count, avg_salary_min=salary_min, avg_salary_max=salary_max,
        avg_year_multiplier=None,
        yoy_job_count=None, yoy_avg_salary=None,
        qoq_job_count=None, qoq_avg_salary=None,
    )


class TestYoyQoq:
    def test_normal_ratios(self):
        cur = _stats(120, 20.0, 30.0)
        year_ago = _stats(100, 16.0, 24.0, date(2025, 9, 23))
        quarter_ago = _stats(110, 18.0, 26.0, date(2026, 6, 30))
        r = calculate_yoy_qoq(cur, year_ago, quarter_ago)
        assert r.yoy_job_count == pytest.approx(0.2)          # 120/100 - 1
        assert r.qoq_job_count == pytest.approx(120 / 110 - 1)
        assert r.yoy_avg_salary == pytest.approx(25.0 / 20.0 - 1)
        assert r.qoq_avg_salary == pytest.approx(25.0 / 22.0 - 1)

    def test_first_year_yoy_is_null(self):
        """首个采集年无同比（PRD 已接受）"""
        r = calculate_yoy_qoq(_stats(100, 20.0, 30.0), None, None)
        assert r.yoy_job_count is None
        assert r.yoy_avg_salary is None

    def test_first_two_quarters_qoq_is_null(self):
        """首两个季度无环比"""
        cur = _stats(100, 20.0, 30.0)
        r = calculate_yoy_qoq(cur, _stats(90, 18.0, 28.0, date(2025, 9, 23)), None)
        assert r.qoq_job_count is None
        assert r.qoq_avg_salary is None

    def test_zero_denominator_is_null(self):
        cur = _stats(100, 20.0, 30.0)
        zero_base = _stats(0, 20.0, 30.0, date(2025, 9, 23))
        r = calculate_yoy_qoq(cur, zero_base, zero_base)
        assert r.yoy_job_count is None
        assert r.qoq_job_count is None

    def test_null_salary_denominator_is_null(self):
        """基期日薪占多数 → avg_salary NULL → 薪资同比 NULL"""
        cur = _stats(100, 20.0, 30.0)
        base = _stats(80, None, None, date(2025, 9, 23))
        r = calculate_yoy_qoq(cur, base, None)
        assert r.yoy_avg_salary is None
        assert r.yoy_job_count == pytest.approx(0.25)
