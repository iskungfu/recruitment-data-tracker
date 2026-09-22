"""统计分析 — 03-module-interfaces.md §9

Week 2 范围：季度归属 + 同比/环比计算（验收清单要求）。
Week 3 范围（本文件暂不实现）：aggregate_by_direction、词频统计。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from core.models import DirectionStats


def get_quarter_start(year: int, quarter: int) -> date:
    """返回季度起始日：Q1=1/1, Q2=4/1, Q3=7/1, Q4=10/1"""
    if not 1 <= quarter <= 4:
        raise ValueError(f"quarter 必须在 1-4: {quarter}")
    return date(year, (quarter - 1) * 3 + 1, 1)


def get_quarter_of(day: date) -> tuple[int, int]:
    """返回 (year, quarter)。采集日即归属季度（如 2026-07-01 采 → 2026Q3）。"""
    return day.year, (day.month - 1) // 3 + 1


def _ratio(current: float | None, base: float | None) -> float | None:
    """current / base - 1；分母为 NULL 或 0 → NULL"""
    if current is None or base is None or base == 0:
        return None
    return current / base - 1


def calculate_yoy_qoq(
    current: DirectionStats,
    one_year_ago: DirectionStats | None,
    one_quarter_ago: DirectionStats | None,
) -> DirectionStats:
    """计算同比 / 环比。

    同比 = current / one_year_ago - 1
    环比 = current / one_quarter_ago - 1
    分母为 NULL 或 0 → 结果 NULL（首两个季度无同比，PRD 已接受）。
    """

    def _avg_salary(s: DirectionStats | None) -> float | None:
        if s is None or s.avg_salary_min is None or s.avg_salary_max is None:
            return None
        return (s.avg_salary_min + s.avg_salary_max) / 2

    cur_avg = _avg_salary(current)
    return replace(
        current,
        yoy_job_count=_ratio(current.job_count, one_year_ago.job_count if one_year_ago else None),
        yoy_avg_salary=_ratio(cur_avg, _avg_salary(one_year_ago)),
        qoq_job_count=_ratio(
            current.job_count, one_quarter_ago.job_count if one_quarter_ago else None
        ),
        qoq_avg_salary=_ratio(cur_avg, _avg_salary(one_quarter_ago)),
    )
