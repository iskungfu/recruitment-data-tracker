"""季度归属测试 — §9 / 验收清单：季度边界"""

from __future__ import annotations

from datetime import date

import pytest

from analysis.stats import get_quarter_of, get_quarter_start


class TestGetQuarterOf:
    @pytest.mark.parametrize(
        "day,expected",
        [
            (date(2026, 1, 1), (2026, 1)),
            (date(2026, 3, 31), (2026, 1)),
            (date(2026, 4, 1), (2026, 2)),    # 边界：Q1/Q2
            (date(2026, 6, 30), (2026, 2)),
            (date(2026, 7, 1), (2026, 3)),    # 边界：Q2/Q3
            (date(2026, 9, 23), (2026, 3)),
            (date(2026, 10, 1), (2026, 4)),   # 边界：Q3/Q4
            (date(2026, 12, 31), (2026, 4)),
        ],
    )
    def test_boundaries(self, day, expected):
        assert get_quarter_of(day) == expected


class TestGetQuarterStart:
    @pytest.mark.parametrize(
        "year,quarter,expected",
        [
            (2026, 1, date(2026, 1, 1)),
            (2026, 2, date(2026, 4, 1)),
            (2026, 3, date(2026, 7, 1)),
            (2026, 4, date(2026, 10, 1)),
        ],
    )
    def test_starts(self, year, quarter, expected):
        assert get_quarter_start(year, quarter) == expected

    def test_invalid_quarter(self):
        with pytest.raises(ValueError):
            get_quarter_start(2026, 5)
