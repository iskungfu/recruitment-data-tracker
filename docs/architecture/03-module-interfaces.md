# 模块接口定义

> 版本：v1.1 | 日期：2026-09-23 | 对应架构概览 v1.1
> v1.1 变更：采集层从 ABC 基类 API scraper 切换为 subprocess CLI wrapper + JSON importer

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

## 6. `collectors/boss_scraper.py` — boss-zhipin-scraper CLI wrapper

```python
from __future__ import annotations
import subprocess, json, shutil
from pathlib import Path
from dataclasses import dataclass
from core.config import Settings
from core.exceptions import ScraperError, ScraperTimeoutError


# ================================================================
# boss-zhipin-scraper 是外部 CLI，不是我们的代码。
# 我们的代码只做：① 组装参数 ② 调 subprocess ③ 解析 JSON 输出。
# ================================================================

@dataclass(frozen=True)
class ScraperConfig:
    """单次采集的参数 (scraper CLI flags)"""
    keyword: str
    city: str                            # boss-zhipin-scraper 城市名（如"北京"）
    max_pages: int = 3                   # ≤3 页/关键词/城市（ADR-011）
    timeout: int = 300                   # 子进程超时 300 秒
    output_dir: Path = Path("data/raw")  # JSON 落盘目录


def run_scraper(config: ScraperConfig, settings: Settings) -> Path:
    """
    启动 boss-zhipin-scraper CLI（subprocess）。

    等价命令：
      $ boss-zhipin-scraper collect \
          --keyword "后端" --city "北京" \
          --max-pages 3 --output data/raw/beijing_houduan.json

    返回：产出的 JSON 路径 Path(...)
    失败抛 ScraperError / ScraperTimeoutError。

    采集跑在**本机 Chrome CDP** 上（需要本机 Chrome + boss-zhipin-scraper 依赖）。
    """


def run_scraper_batch(
    keywords: list[str], cities: list[str], settings: Settings, max_pages: int = 3
) -> list[Path]:
    """
    多轮渐进：遍历 (keyword × city) 组合，逐次调用 run_scraper()。
    每轮之间 ≥2 分钟延迟（boss-zhipin-scraper 内部管理 CDP session 重建）。
    返回所有 JSON 路径列表。

    约束：CDP 被动捕获模式，一个 keyword×city 组合内可多页；
          不同组合之间需重建 CDP session（boss-zhipin-scraper 自动处理）。
    """


def check_scraper_installed() -> bool:
    """环境检查：boss-zhipin-scraper 是否可通过 PATH 调用"""
    return shutil.which("boss-zhipin-scraper") is not None
```

---

## 7. `importers/boss_importer.py` — JSON → SQLite UPSERT

```python
from __future__ import annotations
import json
from pathlib import Path
from datetime import date
from core.models import JobSnapshot
from core.cleansing import dedup_jobs


# ================================================================
# boss-zhipin-scraper JSON 输出字段映射（固定约定）
# ================================================================
# BOSS 字段         → JSON key (scraper 输出)     → JobSnapshot 字段
# ─────────────────────────────────────────────────────────────────
# encryptJobId      → "encrypt_job_id"             → encrypt_job_id
# jobName            → "job_name"                   → job_name
# salaryDesc         → "salary_raw"                 → salary_raw
# city               → "city"                       → normalize_city() → city_id
# brandName          → "company_name"               → company_name
# requireEdu         → "education"                  → education
# requireWorkYears   → "experience"                 → experience
# jobDescription     → "jd_fulltext"                → jd_fulltext (可空)
# skillTags          → "skill_tags" (list)          → skill_tags
# ================================================================


def read_scraper_json(json_path: Path) -> list[dict]:
    """读取 scraper 产出的 JSON 文件 → list[dict]（原始记录）"""


def parse_scraper_record(raw: dict, city_id: int, snapshot_date: date) -> JobSnapshot:
    """
    JSON 原始记录 → JobSnapshot dataclass。
    包含：salary_raw → parse_salary() 拆三字段、city → normalize_city、学历归一
    """


def import_json_to_db(
    json_path: Path,
    city_id: int,
    snapshot_date: date,
    conn,
) -> int:
    """
    1. read_scraper_json(json_path)
    2. 逐条 parse_scraper_record(→ JobSnapshot)
    3. dedup_jobs(排除已有 (encrypt_job_id, snapshot_date))
    4. insert_jobs_batch(→ SQLite，UPSERT 语义)
    返回：新插入数量
    """


def import_batch(
    json_paths: list[Path], city_lookup: dict[str, int], snapshot_date: date, conn
) -> dict[str, int]:
    """
    批量导入：遍历所有 JSON 路径，按城市分组入库。
    返回：{"total": N, "new": M, "duplicates": D}
    """


def validate_schema_compatibility(json_path: Path) -> dict[str, bool]:
    """
    schema 兼容性检查：确认 JSON 包含必填字段（encrypt_job_id, job_name, salary_raw, city），
    防止 scraper 上游输出格式变更导致静默丢字段。
    返回：{"encrypt_job_id": True, "salary_raw": True, ...}
    """
```

---

## 8. 异常体系（`core/exceptions.py`）追加

```python
class ScraperError(TrackerError):
    """boss-zhipin-scraper CLI 执行失败（非零退出码 / 输出为空）"""

class ScraperTimeoutError(ScraperError):
    """scraper 子进程超时（>300s 无响应）"""

class SchemaIncompatibleError(TrackerError):
    """scraper JSON 输出字段不兼容——上游输出格式变更"""
```

---

## 9. `analysis/stats.py` — 统计分析

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

## 10. `analysis/wordfreq.py` — JD 分词与词频

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

## 11. `reporting/renderer.py` — HTML 报告渲染

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

## 12. 异常体系（`core/exceptions.py` — 更新后完整列表）

```python
class TrackerError(Exception): """基类"""

class ConfigError(TrackerError): """配置错误（YAML 格式、缺失字段）"""

class SalaryParseError(TrackerError):
    """薪资解析失败，raw 字段保留原文"""

class SourceNotConfiguredError(TrackerError):
    """平台城市编码未配置（如 TODO_W2_BOSS_BEIJING 未替换）"""

class DBConstraintError(TrackerError):
    """UNIQUE 约束冲突（理论上 dedup 已处理，仅 debug 出现）"""

# ── 采集层新增（v1.1）──
class ScraperError(TrackerError):
    """boss-zhipin-scraper CLI 执行失败（非零退出码 / 输出为空）"""

class ScraperTimeoutError(ScraperError):
    """scraper 子进程超时（>300s 无响应）"""

class SchemaIncompatibleError(TrackerError):
    """scraper JSON 输出字段不兼容——上游输出格式变更"""

# ── 旧 API scraper 异常已移除（v1.1）──
# FetchError, AntiCrawlError, AccountBannedError
# boss-zhipin-scraper 内部处理反爬逻辑，我们不直调 BOSS API
```

---

## 13. 分阶段交付接口矩阵

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
| `collectors/boss_scraper.py` | ✅ | | | | |
| `importers/boss_importer.py` | ✅ | | | | |
| `collectors/jobui.py` | | ✅ | | | |
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

## 14. 研发验收清单（W1 收口自测）

- [ ] `python -c "from core.models import JobSnapshot, DirectionStats"` 导入无报错
- [ ] `python -c "from storage.dao import insert_jobs_batch"` 导入无报错
- [ ] `python -m storage.schema` 创建 sqlite 文件成功，4 张表 + schema_version 全部存在
- [ ] 种子数据查询：`SELECT * FROM cities` 返回 5 行；`SELECT * FROM keywords` 返回 35 行
- [ ] `python -c "from collectors.boss_scraper import check_scraper_installed; print(check_scraper_installed())"` 导入无报错，环境检查返回 bool
- [ ] `python -c "from importers.boss_importer import import_json_to_db"` 导入无报错
- [ ] `pytest tests/` 单元测试 ≥ 5 个通过（薪资解析、城市归一、学历归一、同比计算、季度归属）