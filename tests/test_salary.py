"""薪资解析测试 — §2 / 验收清单：月薪 / 日薪 / 14薪 / 失败路径"""

from __future__ import annotations

import pytest

from core.exceptions import SalaryParseError
from core.salary import normalize_city, normalize_city_name, parse_salary


class TestMonthlySalary:
    def test_plain_monthly(self):
        r = parse_salary("30-60K")
        assert (r.min, r.max) == (30.0, 60.0)
        assert r.year_multiplier is None
        assert r.unit == "month"
        assert r.raw == "30-60K"

    def test_monthly_with_year_multiplier_15(self):
        r = parse_salary("30-60K·15薪")
        assert (r.min, r.max) == (30.0, 60.0)
        assert r.year_multiplier == 15
        assert r.unit == "month"

    def test_monthly_with_year_multiplier_14(self):
        r = parse_salary("15-30K·14薪")
        assert (r.min, r.max) == (15.0, 30.0)
        assert r.year_multiplier == 14

    def test_monthly_dash_separator(self):
        r = parse_salary("20-25K-13薪")
        assert r.year_multiplier == 13

    def test_lowercase_k_and_spaces(self):
        r = parse_salary(" 15.5-30k ")
        assert (r.min, r.max) == (15.5, 30.0)


class TestDailyAndHourly:
    """日薪/时薪：只标 unit，min/max 置 None，不折算混算（ERD §3）"""

    def test_daily(self):
        r = parse_salary("500-550元/天")
        assert r.unit == "day"
        assert r.min is None and r.max is None
        assert r.raw == "500-550元/天"

    def test_daily_without_yuan(self):
        r = parse_salary("400-450/天")
        assert r.unit == "day"
        assert r.min is None

    def test_hourly(self):
        r = parse_salary("100-150元/时")
        assert r.unit == "hour"
        assert r.min is None and r.max is None

    def test_hourly_full_word(self):
        r = parse_salary("100-150/小时")
        assert r.unit == "hour"


class TestParseFailure:
    @pytest.mark.parametrize("bad", ["", "   ", "面议", "30K-60K", "30-60", "abc", "30-60万"])
    def test_invalid_raises(self, bad):
        with pytest.raises(SalaryParseError):
            parse_salary(bad)

    def test_error_keeps_raw(self):
        with pytest.raises(SalaryParseError) as exc_info:
            parse_salary("面议")
        assert exc_info.value.raw == "面议"


class TestCityNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("上海市", "上海"),
            ("北京", "北京"),
            ("深圳市", "深圳"),
            ("北京·朝阳区·望京", "北京"),
            ("杭州·西湖区", "杭州"),
            ("", ""),
        ],
    )
    def test_normalize_city_name(self, raw, expected):
        assert normalize_city_name(raw) == expected

    def test_normalize_city_lookup(self, city_lookup):
        city = normalize_city("上海市", city_lookup)
        assert city.name == "上海"

    def test_normalize_city_unknown_raises(self, city_lookup):
        with pytest.raises(ValueError):
            normalize_city("拉萨", city_lookup)
