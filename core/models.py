"""共享数据模型 — 03-module-interfaces.md §1"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

# ================================================================
# 平台来源
# ================================================================
PLATFORM_BOSS = "BOSS"
PLATFORM_JOBUI = "JOBUI"

# 薪资单位
SALARY_UNIT_MONTH = "month"  # K/月
SALARY_UNIT_DAY = "day"      # 元/天
SALARY_UNIT_HOUR = "hour"    # 元/时


@dataclass(frozen=True)
class City:
    id: int
    name: str                 # 归一化："上海"，非"上海市"
    province: str
    boss_city_code: Optional[str] = None
    jobui_slug: Optional[str] = None


@dataclass(frozen=True)
class Keyword:
    id: int
    direction: str            # 12 方向之一
    keyword: str              # "Vue" / "Java" / "数字IC" 等
    platform: str = PLATFORM_BOSS


@dataclass(frozen=True)
class Snapshot:
    id: int
    snapshot_date: date       # 采集日期
    keyword_id: int
    city_id: int
    status: str               # pending / running / done / failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    job_count: int = 0
    error_log: Optional[str] = None


@dataclass(frozen=True)
class JobSnapshot:
    """原始岗位快照 — 采集层产出，未入库"""

    job_id: str                       # 平台原始 job_id
    encrypt_job_id: str               # 去重键
    job_name: str
    salary_raw: str                   # "30-60K·15薪"
    salary_min: Optional[float]       # K/月；日薪为 NULL
    salary_max: Optional[float]       # K/月；日薪为 NULL
    year_multiplier: Optional[int]    # 15 / 14 / NULL
    salary_unit: str = SALARY_UNIT_MONTH
    city_id: int = 0
    company_name: str = ""
    education: Optional[str] = None   # 已归一化
    experience: Optional[str] = None
    jd_fulltext: Optional[str] = None  # 列表页可能为空
    skill_tags: list[str] = field(default_factory=list)
    platform: str = PLATFORM_BOSS
    snapshot_date: date = field(default_factory=date.today)

    def to_db_tuple(self) -> tuple:
        """转 DB INSERT 用的位置参数元组"""
        return (
            self.job_id,
            self.job_name,
            self.salary_raw,
            self.salary_min,
            self.salary_max,
            self.year_multiplier,
            self.salary_unit,
            self.city_id,
            self.company_name,
            self.education,
            self.experience,
            self.jd_fulltext,
            json.dumps(self.skill_tags, ensure_ascii=False),
            self.platform,
            self.encrypt_job_id,
            self.snapshot_date.isoformat(),
        )


@dataclass(frozen=True)
class DirectionStats:
    """聚合结果：某方向在某季度的统计 — 分析层产出"""

    direction: str
    snapshot_date: date
    city_name: str
    job_count: int
    avg_salary_min: Optional[float]
    avg_salary_max: Optional[float]
    avg_year_multiplier: Optional[float]
    yoy_job_count: Optional[float]       # 同比，未知为 NULL
    yoy_avg_salary: Optional[float]
    qoq_job_count: Optional[float]       # 环比
    qoq_avg_salary: Optional[float]
