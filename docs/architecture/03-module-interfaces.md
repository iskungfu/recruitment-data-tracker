# 模块接口定义

> 版本：v1.0 | 日期：2026-09-22 | 对应架构概览 §2 各模块
> 本文档是 Week 1-5 各阶段代码实现的契约基线，研发工程师可直接对照编写。

---

## 1. 共享数据模型（`core/models.py`）

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional


# ================================================================
# 平台来源
# ================================================================
PLATFORM_BOSS   = "BOSS"
PLATFORM_JOBUI  = "JOBUI"

# 薪资单位
SALARY_UNIT_MONTH = "month"   # K/月
SALARY_UNIT_DAY   = "day"     # 元/天
SALARY_UNIT_HOUR  = "hour"    # 元/时


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
    city_id: int
    company_name: str
    education: Optional[str] = None   # 已归一化
    experience: Optional[str] = None
    jd_fulltext: Optional[str] = None # 列表页可能为空
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
```

---

## 2. `core/salary.py` — 薪资解析

```python
from dataclasses import dataclass

@dataclass
class ParsedSalary:
    min: float | None       # K/月
    max: float | None       # K/月
    year_multiplier: int | None
    unit: str               # month/day/hour
    raw: str


def parse_salary(raw: str) -> ParsedSalary:
    """
    解析薪资原文，支持：
      - 月薪制: "30-60K" / "30-60K·15薪" / "15-30K·14薪"
      - 日薪制: "500-550元/天"
      - 时薪制: "100-150元/时"

    解析失败抛 SalaryParseError，原文保留在 raw 字段。
    """


def normalize_city(raw: str, city_lookup: dict[str, City]) -> City:
    """城市名归一化: "上海市" -> City("上海")"""
```

---

## 3. `core/cleansing.py` — 数据清洗

```python
def clean_education(raw: str | None) -> str | None:
    """学历归一化: "本科及以上" -> "本科", "大专" -> "大专", "硕士" -> "硕士" """


def clean_company_name(raw: str) -> str:
    """公司名清理: 去前后空白 + 去 HTML 标签 + 长度截断"""


def dedup_jobs(
    jobs: list[JobSnapshot], existing_keys: set[tuple[str, date]]
) -> list[JobSnapshot]:
    """
    内存层去重（与 DB UNIQUE 约束双重保障）。
    返回去重后的 jobs 列表。
    """
```

---

## 4. `storage/connection.py` — 数据库连接

```python
def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """
    单例连接，自动开启：
      - PRAGMA journal_mode = WAL
      - PRAGMA foreign_keys = ON
      - PRAGMA busy_timeout = 5000
    返回的 connection 自带 row_factory = sqlite3.Row
    """


@contextmanager
def transaction(conn: sqlite3.Connection):
    """上下文管理器: 自动 commit / rollback"""
```

---

## 5. `storage/dao.py` — 数据访问对象

```python
def insert_snapshot_meta(snap: Snapshot) -> int:
    """插入 snapshots 表元信息，返回新 ID"""

def update_snapshot_status(snap_id: int, status: str, error: str | None = None): ...

def get_existing_keys(conn, snapshot_date: date) -> set[tuple[str, date]]:
    """查询当天的 (encrypt_job_id, snapshot_date) 集合，用于去重预判"""

def insert_jobs_batch(conn, jobs: list[JobSnapshot]) -> int:
    """批量 INSERT OR IGNORE，返回新插入数量"""

def get_jobs_by_snapshot(conn, snapshot_date: date) -> list[JobSnapshot]: ...

def get_jobs_by_date_range(conn, start: date, end: date) -> list[JobSnapshot]: ...

def get_jobs_by_city_and_date(conn, city_id: int, date: date) -> list[JobSnapshot]: ...

def get_snapshot_stats(conn, snapshot_date: date) -> dict:
    """健康检查用：返回每城每方向记录数、空值率"""

def get_direction_stats_for_quarter(
    conn, direction: str, year: int, quarter: int
) -> DirectionStats: ...
```

---

## 6. `collectors/base.py` — 采集器抽象基类

```python
from abc import ABC, abstractmethod

class CollectorBase(ABC):
    """所有平台采集器的统一接口"""

    platform: str = ""  # 子类必填，如 "BOSS"

    def __init__(self, config: Settings, logger: Logger):
        self.config = config
        self.logger = logger

    @abstractmethod
    def fetch_page(self, keyword: str, city: City, page: int) -> list[dict]:
        """
        抓取一页原始数据（不解析）。
        失败抛 FetchError（网络） 或 AntiCrawlError（被封）。
        必须实现：12-22 秒随机延迟、UA 轮换、Cookie 注入。
        """

    @abstractmethod
    def parse_page(self, raw: list[dict], city: City, snapshot_date: date) -> list[JobSnapshot]:
        """原始数据 → JobSnapshot 列表"""

    def run_for_keyword_city(
        self, keyword: Keyword, city: City, snapshot_date: date, max_pages: int = 10
    ) -> list[JobSnapshot]:
        """
        模板方法：抓取 + 解析 + 去重 + 入库。
        子类一般无需重写（仅当需要特殊处理时）。
        """
```

---

## 7. `collectors/boss.py` — BOSS 直聘实现

```python
class BossCollector(CollectorBase):
    platform = "BOSS"

    def fetch_page(self, keyword: str, city: City, page: int) -> list[dict]:
            # 调用 BOSS 搜索 API（参考 boss-zhipin-scraper）
            # 注入 wt2 cookie + UA
            # 检测 code=32 → 抛 AccountBannedError
            # 返回 list[dict]（encryptJobId, jobName, salaryDesc, ...）

    def parse_page(self, raw: list[dict], city: City, snapshot_date: date) -> list[JobSnapshot]:
            # 逐条解析：
            #   salaryDesc → parse_salary()
            #   city → normalize_city() → city.id
            #   学历归一 → clean_education()
            #   skillTags → list[str]
            # 返回 list[JobSnapshot]
```

---

## 8. `analysis/stats.py` — 统计分析

```python
def calculate_yoy_qoq(
    current: DirectionStats,
    one_year_ago: DirectionStats | None,
    one_quarter_ago: DirectionStats | None,
) -> DirectionStats:
    """
    同比 = current / one_year_ago - 1
    环比 = current / one_quarter_ago - 1
    分母为 NULL 或 0 → 结果 NULL
    """

def aggregate_by_direction(
    conn, snapshot_date: date, direction: str
) -> DirectionStats: ...

def get_quarter_start(year: int, quarter: int) -> date:
    """返回季度起始日：Q1=1/1, Q2=4/1, Q3=7/1, Q4=10/1"""

def get_quarter_of(date: date) -> tuple[int, int]:
    """返回 (year, quarter)"""
```

---

## 9. `analysis/wordfreq.py` — JD 分词与词频

```python
STOPWORDS = {"的", "了", "和", "是", "在", "熟悉", "熟练掌握", "掌握", "了解"}

SYNONYMS = {
    "vue.js": "vue", "vue3": "vue", "vue2": "vue",
    "react.js": "react", "reactjs": "react",
    "python3": "python",
    # ... 持续维护
}

def segment_jd(jd_text: str) -> list[str]:
    """
    jieba 分词 → 过滤停用词 → 同义词替换 → 长度 ≥ 2 字符
    """

def top_keywords_for_direction(
    jd_texts: list[str], top_n: int = 20
) -> list[tuple[str, int]]:
    """返回 [(word, count), ...] 按频次降序"""
```

---

## 10. `reporting/renderer.py` — HTML 报告渲染

```python
def render_quarterly_report(
    stats: list[DirectionStats],
    wordfreq_by_direction: dict[str, list[tuple[str, int]]],
    snapshot_date: date,
    output_path: Path,
) -> Path:
    """
    渲染 HTML 单文件报告。
    章节：1. 市场总览 2. 方向细分表 3. Top 20 技能 4. 薪资趋势 5. 岗位数量 6. 结论建议

    Plotly 图表通过 figure.to_html(include_plotlyjs="inline") 嵌入。
    Jinja2 模板：reporting/templates/report.html.j2

    返回 output_path。
    """
```

---

## 11. 异常体系（`core/exceptions.py`）

```python
class TrackerError(Exception): """基类"""

class ConfigError(TrackerError): """配置错误（YAML 格式、缺失字段）"""

class SalaryParseError(TrackerError):
    """薪资解析失败，raw 字段保留原文"""

class FetchError(TrackerError): """HTTP 请求失败（非反爬）"""

class AntiCrawlError(TrackerError):
    """反爬触发：被封 IP / code=32 账号封禁 / 滑块"""

class AccountBannedError(AntiCrawlError):
    """BOSS code=32 账号临时封禁 → 应触发健康检查"""

class SourceNotConfiguredError(TrackerError):
    """平台城市编码未配置（如 TODO_W2_BOSS_BEIJING 未替换）"""

class DBConstraintError(TrackerError):
    """UNIQUE 约束冲突（理论上 dedup 已处理，仅 debug 出现）"""
```

---

## 12. 分阶段交付接口矩阵

| 接口 | W1 写 | W2 写 | W3 写 | W4 写 | W5 写 |
|------|------|------|------|------|------|
| `core/models.py` 全部 dataclass | ✅ | | | | |
| `core/salary.py` | ✅ | | | | |
| `core/cleansing.py` | ✅ | | | | |
| `core/dedup.py` | ✅ | | | | |
| `core/exceptions.py` | ✅ | | | | |
| `core/config.py` | ✅ | | | | |
| `storage/connection.py` | ✅ | | | | |
| `storage/schema.py` | ✅ | | | | |
| `storage/migrations/0001.sql` | ✅ | | | | |
| `storage/dao.py` | ✅ | | | | |
| `collectors/base.py` | ✅ | | | | |
| `collectors/boss.py` | | ✅ | | | |
| `collectors/jobui.py` | | ✅ | | | |
| `utils/anti_crawl.py` | ✅ | | | | |
| `utils/logger.py` | ✅ | | | | |
| `utils/http.py` | ✅ | | | | |
| `analysis/stats.py` | | | ✅ | | |
| `analysis/wordfreq.py` | | | ✅ | | |
| `reporting/renderer.py` | | | | ✅ | |
| `reporting/templates/*.j2` | | | | ✅ | |
| `cli/collect.py` | | ✅ | | | |
| `cli/report.py` | | | | ✅ | |
| `cli/health.py` | | | | | ✅ |
| `cli/migrate.py` | ✅ | | | | |

---

## 13. 研发验收清单（W1 收口自测）

- [ ] `python -c "from core.models import JobSnapshot, DirectionStats"` 导入无报错
- [ ] `python -c "from storage.dao import insert_jobs_batch"` 导入无报错
- [ ] `python -m storage.schema` 创建 sqlite 文件成功，4 张表 + schema_version 全部存在
- [ ] 种子数据查询：`SELECT * FROM cities` 返回 5 行；`SELECT * FROM keywords` 返回 35 行
- [ ] `python -c "from collectors.base import CollectorBase"` 导入无报错
- [ ] `pytest tests/` 单元测试 ≥ 5 个通过（薪资解析、城市归一、学历归一、同比计算、季度归属）