"""数据清洗测试 — §3 / 验收清单：学历归一、公司名清理"""

from __future__ import annotations

import pytest

from core.cleansing import clean_company_name, clean_education


class TestEducation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("本科及以上", "本科"),
            ("本科以上", "本科"),
            ("硕士及以上", "硕士"),
            ("大专", "大专"),
            ("博士", "博士"),
            ("高中", "高中"),
            ("中专/中技", "中专/中技"),
            ("学历不限", None),
            ("不限", None),
            ("", None),
            (None, None),
            ("统招本科", "本科"),
        ],
    )
    def test_clean_education(self, raw, expected):
        assert clean_education(raw) == expected


class TestCompanyName:
    def test_strip_html_tags(self):
        assert clean_company_name("<b>示例科技</b>有限公司") == "示例科技有限公司"

    def test_compress_whitespace(self):
        assert clean_company_name("  示例 科技\n有限公司  ") == "示例 科技 有限公司"

    def test_truncate_at_200(self):
        long_name = "很" * 300
        assert len(clean_company_name(long_name)) == 200

    def test_empty(self):
        assert clean_company_name("") == ""
