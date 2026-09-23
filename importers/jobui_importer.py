"""职友集（jobui.com）JSON → SQLite — Week 4 步骤二

复用 boss_importer 框架（read_scraper_json / get_existing_keys / dedup_jobs /
INSERT OR IGNORE 双重去重），仅字段映射按职友集口径独立实现。

字段映射口径（组长裁决 2026-09-23，含薪资单位追裁决 (a)）：
  salary   —— 统一换算为 K 落库，与 BOSS 同表同口径（core/salary.py 冻结契约 K/月）：
              元 → ÷1000；K → ×1；万 → ×10；
              "面议" → min/max NULL；
              "XX以上" → 仅 salary_min；
              "X-Y元/天" → salary_unit='day'、min/max=NULL（低值≤200/天同此，对齐
              BOSS parse_salary 的日薪语义：日薪不折算混算）；
              其余默认 salary_unit='month'、year_multiplier=12；
              无法解析 → 保留原文、数值置空（不丢整条记录，同 BOSS importer）。
  edu      —— 原文照存，不做归一化（"本科以上"≠"本科"，不调用 clean_education）
  exp      —— 原文照存（含"不限经验"）
  company  —— 原文照存（仅做 HTML 标签/空白清理，不改写文字本身）
  city     —— JSON 的 city（cityKw）→ cities 表反查；未匹配 → city_id NULL（不丢记录）
  encrypt_job_id —— "jobui_" + jobID（jobID 为 jobui 详情页 /job/<id>/ 的数字 ID）
  platform —— "JOBUI"（core.models.PLATFORM_JOBUI）
  source_platform / source_url —— migration 0002 新列：来源域名 "www.jobui.com" /
              详情页 URL（详情页为跳转页无 JD 正文，jd_fulltext 统一 NULL）
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core.cleansing import clean_company_name, dedup_jobs
from core.exceptions import SchemaIncompatibleError
from core.models import PLATFORM_JOBUI, JobSnapshot
from core.salary import normalize_city_name
from importers.boss_importer import read_scraper_json
from storage.connection import get_connection, transaction
from storage.dao import get_existing_keys
from storage.schema import MIGRATION_DIR, apply_migration_script

log = logging.getLogger(__name__)

MIGRATION_0002 = MIGRATION_DIR / "0002_jobui_source.sql"
JOBUI_ID_PREFIX = "jobui_"
DEFAULT_SOURCE_PLATFORM = "www.jobui.com"

_INSERT_JOBUI_SQL = """
INSERT OR IGNORE INTO job_snapshot (
    job_id, job_name, salary_raw, salary_min, salary_max,
    year_multiplier, salary_unit, city_id, company_name,
    education, experience, jd_fulltext, skill_tags,
    platform, encrypt_job_id, snapshot_date, source_platform, source_url
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ── 薪资归一化（统一 K 落库，追裁决 (a)）──

# "35000-50000元" / "40000-70000"（裸数字）/ "8-15k" / "1.5-1.6万" / "150-200元/天"
_RANGE_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*(万|k|K)?\s*元?\s*(?:/\s*天)?\s*$"
)
# "8000元以上" / "8k以上" / "1.5万以上"
_ABOVE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(万|k|K)?\s*元?\s*以上\s*$")
# "200元/天" / "300/天" —— 单值日薪（P3-3：此前落入默认 month 分支）
_SINGLE_DAY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*元?\s*/\s*天\s*$")
_NEGOTIABLE = ("面议", "面谈")

_K_PER_UNIT = {"万": 10.0, "k": 1.0, "K": 1.0, None: 0.001}


@dataclass
class JobuiSalary:
    """职友集薪资解析结果——min/max 已统一换算为 K（对齐 BOSS 冻结契约 K/月）"""

    min: float | None       # K/月
    max: float | None       # K/月；日薪制为 None
    unit: str               # month / day
    year_multiplier: int | None
    raw: str


def parse_jobui_salary(raw: str | None) -> JobuiSalary:
    """职友集薪资原文 → JobuiSalary（K 口径）。

    "面议" → min/max None + month + year_multiplier=12（默认口径，同其余记录）；
    解析失败 → 保留原文、数值置空（不抛异常，不丢整条记录）。
    """
    default = JobuiSalary(min=None, max=None, unit="month", year_multiplier=12, raw=raw or "")
    text = (raw or "").strip()
    if not text or any(word in text for word in _NEGOTIABLE):
        return default

    m = _RANGE_RE.match(text)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        suffix = m.group(3)
        if text.endswith("天") or "/天" in text:          # 日薪：不折算混算（对齐 BOSS 语义）
            return JobuiSalary(min=None, max=None, unit="day", year_multiplier=None, raw=raw)
        factor = _K_PER_UNIT[suffix]
        return JobuiSalary(
            min=round(low * factor, 2), max=round(high * factor, 2),
            unit="month", year_multiplier=12, raw=raw,
        )

    m = _ABOVE_RE.match(text)
    if m:
        value, suffix = float(m.group(1)), m.group(2)
        return JobuiSalary(
            min=round(value * _K_PER_UNIT[suffix], 2), max=None,
            unit="month", year_multiplier=12, raw=raw,
        )

    # P3-3 修复：单值日薪 "200元/天" 此前落入默认 month 分支；
    # 对齐区间日薪语义——unit='day'、min/max 不折算（数值置空）
    if _SINGLE_DAY_RE.match(text):
        return JobuiSalary(min=None, max=None, unit="day", year_multiplier=None, raw=raw)

    log.warning("职友集薪资无法解析，保留原文、数值置空: %r", raw)
    return default


@dataclass(frozen=True)
class JobuiJobSnapshot(JobSnapshot):
    """JobSnapshot + 来源站两列（migration 0002）"""

    source_platform: str | None = None
    source_url: str | None = None

    def to_db_tuple(self) -> tuple:
        base = super().to_db_tuple()
        return (*base, self.source_platform, self.source_url)


def ensure_source_columns(conn) -> None:
    """确保 job_snapshot 已有 source_platform / source_url 列（migration 0002）。

    幂等且自愈（P3-5 修复）：列与版本记录任一缺失时重放迁移——
    ALTER 前逐列 PRAGMA 检查、已存在跳过（半迁移中断的库直接补齐，
    列被删的旧库补列），版本记录 INSERT OR IGNORE（列齐但版本未记的库补记录）。
    旧库（0002 应用前初始化的 DB）首次经本 importer 入库时自动补列。
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(job_snapshot)")}
    recorded = {int(r[0]) for r in conn.execute("SELECT version FROM schema_version")}
    if {"source_platform", "source_url"} <= cols and 2 in recorded:
        return
    apply_migration_script(conn, MIGRATION_0002.read_text(encoding="utf-8"))


def parse_jobui_record(raw: dict, city_id: int | None, snapshot_date: date) -> JobuiJobSnapshot:
    """职友集 JSON 单条记录 → JobuiJobSnapshot。

    encrypt_job_id = "jobui_" + jobID；edu/exp/company 原文照存；
    jd_fulltext 统一 None（详情页为跳转页，无 JD 正文——recon 结论）；
    source_platform / source_url 见模块 docstring。
    """
    job_id = str(raw.get("job_id") or "").strip()
    if not job_id:
        # 兜底：从详情页 URL 提取数字 ID
        detail_url = str(raw.get("detail_url") or "")
        m = re.search(r"/job/(\d+)/", detail_url)
        if not m:
            raise SchemaIncompatibleError(f"记录缺少 job_id: {str(raw)[:200]}")
        job_id = m.group(1)

    salary = parse_jobui_salary(raw.get("salary"))

    return JobuiJobSnapshot(
        job_id=job_id,
        encrypt_job_id=JOBUI_ID_PREFIX + job_id,
        job_name=str(raw.get("title") or "").strip(),
        salary_raw=salary.raw,
        salary_min=salary.min,
        salary_max=salary.max,
        year_multiplier=salary.year_multiplier,
        salary_unit=salary.unit,
        city_id=city_id,
        company_name=clean_company_name(str(raw.get("company_name") or "")),
        education=(str(raw["education"]).strip() or None) if raw.get("education") else None,
        experience=(str(raw["experience"]).strip() or None) if raw.get("experience") else None,
        jd_fulltext=None,
        skill_tags=[],
        platform=PLATFORM_JOBUI,
        snapshot_date=snapshot_date,
        source_platform=str(raw.get("source_platform") or DEFAULT_SOURCE_PLATFORM),
        source_url=(str(raw["detail_url"]).strip() or None) if raw.get("detail_url") else None,
    )


def import_json_to_db(
    json_path: Path,
    city_id: int | None,
    snapshot_date: date,
    conn,
) -> tuple[int, int]:
    """单个职友集 JSON 入库：读取 → 逐条解析 → dedup → INSERT OR IGNORE。

    入库前自动执行 ensure_source_columns()（旧库自动补列）。
    返回：(新插入数量, 解析成功条数)。

    P3-2 修复：解析成功条数与插入数分开返回——重复数应为
    parsed_total - inserted，不能把解析失败条目算进重复（混计口径错误）。
    """
    ensure_source_columns(conn)
    records = read_scraper_json(json_path)
    jobs: list[JobSnapshot] = []
    for raw in records:
        try:
            jobs.append(parse_jobui_record(raw, city_id, snapshot_date))
        except (SchemaIncompatibleError, ValueError) as e:
            log.warning("跳过无法解析的职友集记录: %s", e)
    parsed_total = len(jobs)

    existing = get_existing_keys(conn, snapshot_date)
    deduped = dedup_jobs(jobs, existing)
    before = conn.total_changes
    with transaction(conn):
        conn.executemany(_INSERT_JOBUI_SQL, [job.to_db_tuple() for job in deduped])
    inserted = conn.total_changes - before
    log.info(
        "导入职友集 %s: 原始 %d 条 → 解析 %d 条 → 去重后 %d 条 → 新插入 %d 条",
        json_path, len(records), parsed_total, len(deduped), inserted,
    )
    return inserted, parsed_total


def import_batch(
    json_paths: list[Path], city_lookup: dict[str, int], snapshot_date: date, conn
) -> dict[str, int]:
    """批量导入：遍历 JSON 路径，按每份文件首条记录的 city 反查 city_id。

    职友集口径（裁决）：城市未匹配 → city_id 置 NULL 照常入库（不丢记录，
    区别于 BOSS importer 的跳过整份文件）。
    返回：{"total": N, "new": M, "duplicates": D, "unknown_city": U}

    P3-2 修复：duplicates = 解析成功总数 - 新插入数，
    不把解析失败条目混进重复计数。
    """
    total = new = parsed_total = unknown_city_files = 0
    for path in json_paths:
        records = read_scraper_json(path)
        if not records:
            log.warning("空文件，跳过: %s", path)
            continue
        # 城市（cityKw）记录在 JSON 顶层，不在岗位记录里——单独读顶层字段
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        city_text = str(payload.get("city") or "") if isinstance(payload, dict) else ""
        city_name = normalize_city_name(city_text)
        city_id = city_lookup.get(city_name)
        if city_id is None:
            log.warning("未收录的城市 %r（文件 %s），city_id 置 NULL 照常入库", city_name, path)
            unknown_city_files += 1
        total += len(records)
        inserted, parsed = import_json_to_db(path, city_id, snapshot_date, conn)
        new += inserted
        parsed_total += parsed
    return {
        "total": total, "new": new, "duplicates": parsed_total - new,
        "unknown_city": unknown_city_files,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI：python -m importers.jobui_importer <json...> [--db path] [--date YYYY-MM-DD]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m importers.jobui_importer",
        description="职友集采集 JSON 批量入库（含 source_platform/source_url 列）",
    )
    parser.add_argument("json_paths", nargs="+", type=Path, help="jobui_jobs_*.json 文件路径")
    parser.add_argument("--db", type=Path, default=Path("data/recruitment.db"),
                        help="SQLite 数据库路径（默认 data/recruitment.db）")
    parser.add_argument("--date", type=str, default=date.today().isoformat(),
                        help="快照日期 YYYY-MM-DD（默认今天）")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"错误: 数据库文件不存在: {args.db}（先运行 python -m storage.schema）",
              file=sys.stderr)
        return 1
    snapshot_date = date.fromisoformat(args.date)

    conn = get_connection(args.db)
    try:
        city_lookup = {
            row["name"]: int(row["id"]) for row in conn.execute("SELECT id, name FROM cities")
        }
        result = import_batch(args.json_paths, city_lookup, snapshot_date, conn)
    finally:
        conn.close()

    print(f"职友集导入完成: 原始 {result['total']} 条，新插入 {result['new']} 条，"
          f"重复 {result['duplicates']} 条，未匹配城市文件 {result['unknown_city']} 份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
