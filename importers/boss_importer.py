"""BOSS JSON → SQLite UPSERT — 03-module-interfaces.md §7

字段映射（以 boss-zhipin-scraper v2.2 真实输出为准，§7 假设字段名作兼容兜底）：

  真实 JSON key (scraper 输出)   §7 兼容 key          → JobSnapshot 字段
  ─────────────────────────────────────────────────────────────────────
  "encrypt_job_id"               同左 / "source_job_id" → encrypt_job_id
  "title"                        "job_name"            → job_name
  "salary"                       "salary_raw"          → salary_raw → parse_salary 拆三字段
  "location"（"城市·区·商圈"）    "city"               → normalize_city → city_id（校验用）
  "boss_name"（公司名）           "company_name"/"company" → company_name
  "tags"（"经验 | 学历"）         "education"/"degree_required"  → education（归一化）
                                  "experience"/"experience_required" → experience
  "jd"（详情文件）                "jd_fulltext"        → jd_fulltext（可空）
  "skills"（" | " 连接）          "skill_tags" (list)  → skill_tags

顶层结构兼容两种：{"jobs": [...]}（scraper 真实输出）或裸 list（W1 预研样本）。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from core.cleansing import clean_company_name, clean_education, dedup_jobs
from core.exceptions import SalaryParseError, SchemaIncompatibleError
from core.models import PLATFORM_BOSS, JobSnapshot
from core.salary import normalize_city_name, parse_salary
from storage.dao import get_existing_keys, insert_jobs_batch

log = logging.getLogger(__name__)

_SPLIT_RE = re.compile(r"\s*[|｜]\s*")

# 学历词集合（从 "经验 | 学历" 混合 tags 中识别学历段）
_DEGREE_WORDS = ("初中", "高中", "中专", "中技", "大专", "本科", "硕士", "博士", "学历不限")

# schema 兼容性必填字段：每个逻辑字段列出可接受的 JSON key（任一命中即可）
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "encrypt_job_id": ("encrypt_job_id", "source_job_id", "job_id"),
    "job_name": ("job_name", "title"),
    "salary_raw": ("salary_raw", "salary"),
    "city": ("city", "location"),
}


def read_scraper_json(json_path: Path) -> list[dict]:
    """读取 scraper 产出的 JSON 文件 → list[dict]（原始记录）。

    兼容两种顶层结构：{"total": N, "jobs": [...]} 或裸 [...]。
    """
    json_path = Path(json_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise SchemaIncompatibleError(
                f"{json_path}: 顶层为 dict 但缺少 jobs 数组（实际 keys: {sorted(data)[:10]}）"
            )
        return [j for j in jobs if isinstance(j, dict)]
    if isinstance(data, list):
        return [j for j in data if isinstance(j, dict)]
    raise SchemaIncompatibleError(f"{json_path}: 顶层结构应为 list 或含 jobs 的 dict")


def _first(raw: dict, *keys: str) -> str:
    """按优先级取第一个非空字符串字段"""
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _split_tags(raw: dict) -> tuple[str | None, str | None]:
    """从 tags/degree/experience 字段拆 (experience, education_raw)。

    scraper 真实输出 tags 为 "3-5年 | 本科"（经验 | 学历混合）；
    §7 兼容输出则直接给 education / experience 独立字段。
    """
    exp = _first(raw, "experience", "experience_required")
    edu = _first(raw, "education", "degree_required")
    mixed = _first(raw, "tags")
    if mixed and (not exp or not edu):
        for part in _SPLIT_RE.split(mixed):
            part = part.strip()
            if not part:
                continue
            if any(w in part for w in _DEGREE_WORDS) or part == "不限":
                edu = edu or part
            else:
                exp = exp or part
    return (exp or None), (edu or None)


def _parse_skills(raw: dict) -> list[str]:
    """skill_tags：兼容 list（§7）与 " | " 连接字符串（scraper 真实 skills 字段）"""
    value = raw.get("skill_tags")
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    text = _first(raw, "skills", "job_labels")
    if text:
        return [t for t in _SPLIT_RE.split(text) if t]
    return []


def parse_scraper_record(raw: dict, city_id: int, snapshot_date: date) -> JobSnapshot:
    """JSON 原始记录 → JobSnapshot dataclass。

    salary_raw → parse_salary() 拆 min/max/year_multiplier/unit；
    学历经 clean_education 归一；公司名经 clean_company_name 清理。
    薪资无法解析时记日志、保留原文、数值字段置空（不丢整条记录）。
    """
    encrypt_job_id = _first(raw, "encrypt_job_id", "source_job_id", "job_id")
    if not encrypt_job_id:
        raise SchemaIncompatibleError(f"记录缺少 encrypt_job_id: {str(raw)[:200]}")

    salary_raw = _first(raw, "salary_raw", "salary")
    salary_min = salary_max = None
    year_multiplier = None
    salary_unit = "month"
    if salary_raw:
        try:
            parsed = parse_salary(salary_raw)
            salary_min, salary_max = parsed.min, parsed.max
            year_multiplier = parsed.year_multiplier
            salary_unit = parsed.unit
        except SalaryParseError as e:
            log.warning("薪资解析失败，保留原文、数值置空: %s", e)

    experience, edu_raw = _split_tags(raw)

    return JobSnapshot(
        job_id=_first(raw, "job_id") or encrypt_job_id,
        encrypt_job_id=encrypt_job_id,
        job_name=_first(raw, "job_name", "title"),
        salary_raw=salary_raw,
        salary_min=salary_min,
        salary_max=salary_max,
        year_multiplier=year_multiplier,
        salary_unit=salary_unit,
        city_id=city_id,
        company_name=clean_company_name(_first(raw, "company_name", "company", "boss_name")),
        education=clean_education(edu_raw),
        experience=experience,
        jd_fulltext=_first(raw, "jd_fulltext", "jd") or None,
        skill_tags=_parse_skills(raw),
        platform=PLATFORM_BOSS,
        snapshot_date=snapshot_date,
    )


def validate_schema_compatibility(json_path: Path) -> dict[str, bool]:
    """schema 兼容性检查：确认 JSON 包含必填字段。

    防止 scraper 上游输出格式变更导致静默丢字段。
    返回 {"encrypt_job_id": True, "job_name": True, ...}（任一兼容 key 命中即 True）。
    空文件 / 无记录时所有字段记 False。
    """
    records = read_scraper_json(json_path)
    result = {field: False for field in _REQUIRED_KEYS}
    if not records:
        return result
    for field, keys in _REQUIRED_KEYS.items():
        result[field] = any(_first(records[0], key) for key in keys)
    return result


def import_json_to_db(
    json_path: Path,
    city_id: int,
    snapshot_date: date,
    conn,
) -> int:
    """单个 JSON 文件入库：读取 → 逐条解析 → dedup → INSERT OR IGNORE。

    入库前先做 schema 兼容性检查（不兼容抛 SchemaIncompatibleError），
    再 dedup_jobs（内存层）+ INSERT OR IGNORE（DB 约束）双重去重。
    返回：新插入数量。
    """
    compat = validate_schema_compatibility(json_path)
    missing = [field for field, ok in compat.items() if not ok]
    if missing:
        raise SchemaIncompatibleError(
            f"{json_path}: 必填字段缺失 {missing}——scraper 上游输出格式可能已变更"
        )

    records = read_scraper_json(json_path)
    jobs: list[JobSnapshot] = []
    for raw in records:
        try:
            jobs.append(parse_scraper_record(raw, city_id, snapshot_date))
        except (SchemaIncompatibleError, ValueError) as e:
            log.warning("跳过无法解析的记录: %s", e)

    existing = get_existing_keys(conn, snapshot_date)
    deduped = dedup_jobs(jobs, existing)
    inserted = insert_jobs_batch(conn, deduped)
    log.info(
        "导入 %s: 原始 %d 条 → 解析 %d 条 → 去重后 %d 条 → 新插入 %d 条",
        json_path, len(records), len(jobs), len(deduped), inserted,
    )
    return inserted


def import_batch(
    json_paths: list[Path], city_lookup: dict[str, int], snapshot_date: date, conn
) -> dict[str, int]:
    """批量导入：遍历所有 JSON 路径，按城市分组入库。

    city_lookup: {归一化城市名: city_id}，城市从每条 JSON 的首记录 location/city 推断。
    返回：{"total": N, "new": M, "duplicates": D}
    """
    total = new = 0
    for path in json_paths:
        records = read_scraper_json(path)
        if not records:
            log.warning("空文件，跳过: %s", path)
            continue
        city_text = _first(records[0], "city", "location")
        city_name = normalize_city_name(city_text)
        city_id = city_lookup.get(city_name)
        if city_id is None:
            log.error("未收录的城市 %r（文件 %s），跳过", city_name, path)
            continue
        total += len(records)
        new += import_json_to_db(path, city_id, snapshot_date, conn)
    return {"total": total, "new": new, "duplicates": total - new}
