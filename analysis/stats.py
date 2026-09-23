"""统计分析 — 03-module-interfaces.md §9

Week 2 范围：季度归属 + 同比/环比计算（dataclass 层，calculate_yoy_qoq）。
Week 3 范围：DB 层 compute_yoy_qoq（overall / by_city / by_direction 三维度）。
Week 4 步骤三：by_platform 平台拆分子结构 + total_unique_jobs 跨平台去重 KPI。
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

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


# ================================================================
# Week 3：DB 层同比/环比（compute_yoy_qoq）
# ================================================================

#: 维度指标聚合结构：{quarter_key: {"job_count": int, "salary_sum": float, "salary_n": int}}
QuarterKey = tuple[int, int]


def _shift_quarter(year: int, quarter: int, delta: int) -> QuarterKey:
    """季度平移：delta=-1 上一季度，-4 去年同期。"""
    idx = (year * 4 + (quarter - 1)) + delta
    return idx // 4, idx % 4 + 1


def quarter_label(key: QuarterKey) -> str:
    """(2026, 3) → "2026Q3" """
    return f"{key[0]}Q{key[1]}"


def _attribute_direction(
    job_name: str, keyword_map: list[tuple[str, str]]
) -> str | None:
    """按关键词把岗位名归到方向（启发式）。

    背景：job_snapshot 表无 keyword/direction 列（schema 归 storage/，W3 不可改），
    snapshots 表同日同城可挂多个关键词、无法逐岗位归属。因此用
    「job_name 包含关键词」匹配：关键词按长度降序、大小写不敏感，
    命中即取其 direction；全部未命中返回 None（计入 unattributed）。
    """
    name = job_name.lower()
    for keyword, direction in keyword_map:
        if keyword.lower() in name:
            return direction
    return None


def _avg_salary_mid(agg: dict) -> float | None:
    """聚合桶 → 月薪中点均值；无月薪岗位 → None（日薪/时薪不参与，不折算混算）"""
    if agg["salary_n"] == 0:
        return None
    return agg["salary_sum"] / agg["salary_n"]


def _dimension_result(
    buckets: dict[QuarterKey, dict], current: QuarterKey
) -> dict:
    """单桶 → {current_quarter, job_count, avg_salary, qoq, yoy}"""
    cur = buckets.get(current, {"job_count": 0, "salary_sum": 0.0, "salary_n": 0})
    prev = buckets.get(_shift_quarter(*current, -1))
    year_ago = buckets.get(_shift_quarter(*current, -4))

    def _count(b: dict | None) -> int | None:
        return None if b is None else b["job_count"]

    cur_avg = _avg_salary_mid(cur)
    return {
        "current_quarter": quarter_label(current),
        "job_count": cur["job_count"],
        "avg_salary": cur_avg,
        "qoq": {
            "job_count": _ratio(cur["job_count"], _count(prev)),
            "avg_salary": _ratio(cur_avg, None if prev is None else _avg_salary_mid(prev)),
        },
        "yoy": {
            "job_count": _ratio(cur["job_count"], _count(year_ago)),
            "avg_salary": _ratio(cur_avg, None if year_ago is None else _avg_salary_mid(year_ago)),
        },
    }


def compute_yoy_qoq(db_path: str | Path, city: str | int | None = None) -> dict:
    """从 SQLite 计算同比/环比，三维度：overall / by_city / by_direction。

    Args:
        db_path: SQLite 数据库路径。
        city: 可选城市过滤——str 按城市名（cities.name）、int 按 city_id。

    Returns:
        {
          "current_quarter": "2026Q3",           # 数据内最大采集日所在季度；无数据为 None
          "overall":  {...qoq/yoy...},
          "by_city":  {"北京": {...}, ...},
          "by_direction": {"后端": {...}, ...},   # 启发式关键词归属，见 _attribute_direction
          "unattributed": N,                      # 未归到任何方向的岗位数
        }
        每个维度桶：{"current_quarter", "job_count", "avg_salary",
                     "qoq": {"job_count", "avg_salary"},
                     "yoy": {"job_count", "avg_salary"},
                     "by_platform": {"boss": {"job_count", "avg_salary"},
                                     "jobui": {...}}}   # Week 4 步骤三 P2
        overall 额外带 total_unique_jobs：本季跨平台唯一岗位数
        （job_name+company_name+city_id 归一 sha1 哈希去重，仅报告层口径）。
        by_platform 只含有数据的平台，报告层对缺失平台按 0 / None 兜底。
        分母缺失或为 0 → 对应百分比为 None。avg_salary 只计月薪岗
        （salary_unit='month'），取 (salary_min+salary_max)/2 的均值。

    Raises:
        FileNotFoundError: db_path 不存在时抛出（不静默创建空库文件）。
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 城市过滤
        where, params = "", []
        if city is not None:
            if isinstance(city, int):
                where, params = "WHERE j.city_id = ?", [city]
            else:
                row = conn.execute(
                    "SELECT id FROM cities WHERE name = ?", (city,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"未知城市: {city}")
                where, params = "WHERE j.city_id = ?", [row["id"]]

        rows = conn.execute(
            f"SELECT j.city_id, c.name AS city_name, j.job_name, j.company_name, "
            f"       j.platform, j.salary_min, j.salary_max, j.salary_unit, "
            f"       j.snapshot_date "
            f"FROM job_snapshot j LEFT JOIN cities c ON c.id = j.city_id {where}",
            params,
        ).fetchall()

        keyword_map = [
            (r["keyword"], r["direction"])
            for r in conn.execute(
                "SELECT keyword, direction FROM keywords WHERE is_active = 1"
            ).fetchall()
        ]
    finally:
        conn.close()

    keyword_map.sort(key=lambda kd: len(kd[0]), reverse=True)

    def _new_bucket() -> dict:
        return {"job_count": 0, "salary_sum": 0.0, "salary_n": 0}

    def _add(buckets: dict[QuarterKey, dict], key: QuarterKey, row: sqlite3.Row) -> None:
        b = buckets.setdefault(key, _new_bucket())
        b["job_count"] += 1
        if row["salary_unit"] == "month" and row["salary_min"] is not None \
                and row["salary_max"] is not None:
            b["salary_sum"] += (row["salary_min"] + row["salary_max"]) / 2
            b["salary_n"] += 1

    overall: dict[QuarterKey, dict] = {}
    by_city: dict[str, dict[QuarterKey, dict]] = {}
    by_direction: dict[str, dict[QuarterKey, dict]] = {}
    # P2 平台拆分（Week 4 步骤三）：每维度再按平台平行聚合，
    # 供 by_platform 子结构输出（"BOSS"→"boss"、"JOBUI"→"jobui"）
    overall_pf: dict[str, dict[QuarterKey, dict]] = {}
    by_city_pf: dict[str, dict[str, dict[QuarterKey, dict]]] = {}
    by_direction_pf: dict[str, dict[str, dict[QuarterKey, dict]]] = {}
    unattributed = 0

    def _platform_key(platform: str | None) -> str:
        return (platform or "boss").strip().lower()

    for row in rows:
        day = date.fromisoformat(row["snapshot_date"])
        key = get_quarter_of(day)
        pf = _platform_key(row["platform"])
        _add(overall, key, row)
        _add(overall_pf.setdefault(pf, {}), key, row)
        # P3-4 修复：city_name 与 city_id 同时缺失时不再产出字面桶 "city_None"
        city_name = row["city_name"] or (
            f"city_{row['city_id']}" if row["city_id"] else "未知城市"
        )
        _add(by_city.setdefault(city_name, {}), key, row)
        _add(by_city_pf.setdefault(city_name, {}).setdefault(pf, {}), key, row)
        direction = _attribute_direction(row["job_name"], keyword_map)
        if direction is None:
            unattributed += 1
        else:
            _add(by_direction.setdefault(direction, {}), key, row)
            _add(by_direction_pf.setdefault(direction, {}).setdefault(pf, {}), key, row)

    if not overall:
        return {
            "current_quarter": None,
            "overall": None,
            "by_city": {},
            "by_direction": {},
            "unattributed": 0,
        }

    current = max(overall.keys())

    def _pf_stats(pfs: dict[str, dict[QuarterKey, dict]]) -> dict[str, dict]:
        """平台桶 → 本季 {平台: {"job_count", "avg_salary"}}（按平台名排序）。

        平台在该维度无数据（如纯 BOSS 库里的 jobui）不出现在结果里，
        由报告层按 0 / None 兜底展示。
        """
        stats: dict[str, dict] = {}
        for p, b in sorted(pfs.items()):
            cur = b.get(current, {"job_count": 0, "salary_sum": 0.0, "salary_n": 0})
            stats[p] = {
                "job_count": cur["job_count"],
                "avg_salary": _avg_salary_mid(cur),
            }
        return stats

    def _norm(v) -> str:
        # P3 修复（2026-09-23）：大小写/首尾空白归一——"Python后端" 与
        # "python后端" 计为同一岗位（保守方向：只并同义变体，不误并不同岗）
        return "" if v is None else str(v).strip().casefold()

    # P2 跨平台去重 KPI：job_name+company_name+city_id 归一哈希（sha1）去重，
    # 仅作报告层统计口径，不落库（组长裁决 2026-09-23）
    total_unique_jobs = len({
        hashlib.sha1(
            f"{_norm(r['job_name'])}|{_norm(r['company_name'])}|{_norm(r['city_id'])}".encode()
        ).hexdigest()
        for r in rows
        if get_quarter_of(date.fromisoformat(r["snapshot_date"])) == current
    })

    return {
        "current_quarter": quarter_label(current),
        "overall": {
            **_dimension_result(overall, current),
            "total_unique_jobs": total_unique_jobs,
            "by_platform": _pf_stats(overall_pf),
        },
        "by_city": {
            name: {
                **_dimension_result(b, current),
                "by_platform": _pf_stats(by_city_pf.get(name, {})),
            }
            for name, b in sorted(by_city.items())
        },
        "by_direction": {
            d: {
                **_dimension_result(b, current),
                "by_platform": _pf_stats(by_direction_pf.get(d, {})),
            }
            for d, b in sorted(by_direction.items())
        },
        "unattributed": unattributed,
    }
