"""数据清洗 — 03-module-interfaces.md §3"""

from __future__ import annotations

import re
from datetime import date

from core.models import JobSnapshot

_EDU_CANONICAL = {"博士", "硕士", "本科", "大专", "高中", "中专/中技", "中技", "中专", "初中及以下"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_COMPANY_MAX_LEN = 200


def clean_education(raw: str | None) -> str | None:
    """学历归一化: "本科及以上" -> "本科", "学历不限"/"不限" -> None"""
    if not raw:
        return None
    text = raw.strip()
    if not text or text in ("不限", "学历不限"):
        return None
    # "本科及以上" / "本科以上" -> "本科"
    text = re.sub(r"及以上$|以上$", "", text)
    if text in _EDU_CANONICAL:
        return text
    # 模糊包含（如 "统招本科"）
    for canon in ("博士", "硕士", "本科", "大专", "高中", "中专", "中技", "初中"):
        if canon in text:
            return "中专/中技" if canon in ("中专", "中技") else canon
    return text


def clean_company_name(raw: str) -> str:
    """公司名清理: 去前后空白 + 去 HTML 标签 + 长度截断"""
    if not raw:
        return ""
    text = _HTML_TAG_RE.sub("", raw)
    text = " ".join(text.split())  # 压缩所有空白（含换行/全角空格序列）
    return text[:_COMPANY_MAX_LEN]


def dedup_jobs(
    jobs: list[JobSnapshot], existing_keys: set[tuple[str, date]]
) -> list[JobSnapshot]:
    """内存层去重（与 DB UNIQUE 约束双重保障）。

    剔除两类：
      1. (encrypt_job_id, snapshot_date) 已在库中的记录
      2. 本批次内部的重复记录（保留首次出现）
    返回去重后的 jobs 列表。
    """
    seen: set[tuple[str, date]] = set()
    result: list[JobSnapshot] = []
    for job in jobs:
        key = (job.encrypt_job_id, job.snapshot_date)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result
