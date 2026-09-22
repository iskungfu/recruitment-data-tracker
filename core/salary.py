"""薪资解析与城市归一 — 03-module-interfaces.md §2

支持：
  - 月薪制: "30-60K" / "30-60K·15薪" / "15-30K·14薪"
  - 日薪制: "500-550元/天"（min/max 置 NULL，不折算混算 — 见 ERD §3）
  - 时薪制: "100-150元/时"（同上）
解析失败抛 SalaryParseError，原文保留在 raw 字段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.exceptions import SalaryParseError
from core.models import SALARY_UNIT_DAY, SALARY_UNIT_HOUR, SALARY_UNIT_MONTH, City

# "30-60K" / "30-60K·15薪" / "15.5-30K · 14 薪"
_MONTH_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*[Kk]"
    r"(?:\s*[·\-]?\s*(\d{1,2})\s*薪)?\s*$"
)
# "500-550元/天" / "500-550/天"
_DAY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:元)?\s*/\s*天\s*$")
# "100-150元/时" / "100-150/小时"
_HOUR_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:元)?\s*/\s*(?:时|小时)\s*$"
)


@dataclass
class ParsedSalary:
    min: float | None       # K/月
    max: float | None       # K/月
    year_multiplier: int | None
    unit: str               # month/day/hour
    raw: str


def parse_salary(raw: str) -> ParsedSalary:
    """解析薪资原文 → ParsedSalary。

    月薪制拆出 min/max（K/月）与 year_multiplier（"·15薪"→15，未标注为 None）；
    日薪/时薪制只标 unit，min/max 置 None（原文保留在 raw，不折算混算）。
    """
    if not raw or not raw.strip():
        raise SalaryParseError(raw or "", "空薪资字符串")
    text = raw.strip()

    m = _MONTH_RE.match(text)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        multiplier = int(m.group(3)) if m.group(3) else None
        return ParsedSalary(
            min=low, max=high, year_multiplier=multiplier,
            unit=SALARY_UNIT_MONTH, raw=raw,
        )

    if _DAY_RE.match(text):
        return ParsedSalary(
            min=None, max=None, year_multiplier=None,
            unit=SALARY_UNIT_DAY, raw=raw,
        )

    if _HOUR_RE.match(text):
        return ParsedSalary(
            min=None, max=None, year_multiplier=None,
            unit=SALARY_UNIT_HOUR, raw=raw,
        )

    raise SalaryParseError(raw, "不支持的薪资格式")


def normalize_city_name(raw: str) -> str:
    """城市名文本归一化："上海市"→"上海"，"北京"→"北京"。"""
    if not raw:
        return ""
    name = raw.strip()
    # scraper 真实输出 location 为 "城市·区·商圈"，取第一段
    name = name.split("·")[0].strip()
    for suffix in ("市", "省"):
        if name.endswith(suffix) and len(name) > 1:
            name = name[: -len(suffix)]
    return name


def normalize_city(raw: str, city_lookup: dict[str, City]) -> City:
    """城市名归一化并查表："上海市" → City("上海")。未收录抛 ValueError。"""
    name = normalize_city_name(raw)
    if name in city_lookup:
        return city_lookup[name]
    raise ValueError(f"未收录的城市: {raw!r}（归一化为 {name!r}）")
