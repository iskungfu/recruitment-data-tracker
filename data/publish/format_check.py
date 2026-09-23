"""发布 JSON 的 schema 校验 — 06-website-architecture-v1.0.md §3.2

校验项：
- 6 个文件齐备且可解析；manifest.datasets 与目录内实际 JSON 一一对应；
- 各文件必填字段存在；
- 数值字段类型正确（int / float，null 仅在 schema 允许处）；
- chart_specs 非空且每个 spec 含 data（数组）+ layout（对象）。

用法：
    python -m data.publish.format_check [目录]     # 默认 data/publish/v1
退出码：0 = 全部通过；1 = 存在错误（逐条打印到 stderr）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_DIR = Path("data/publish/v1")

#: 5 个数据集名（manifest 本身除外）
DATASET_NAMES = (
    "summary",
    "salary_trends",
    "job_ranking",
    "edu_exp_distribution",
    "data_status",
)

#: 各数据集必须包含的 chart_specs 键
CHART_SPEC_KEYS = {
    "salary_trends": ("direction_comparison", "city_comparison"),
    "job_ranking": ("ranking_bar", "skills_wordcloud"),
    "edu_exp_distribution": ("edu_pie", "exp_bar_by_dir"),
}


# ---------------------------------------------------------------- 类型辅助


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _num_or_none(v) -> bool:
    return v is None or _is_num(v)


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


# ---------------------------------------------------------------- 各文件校验


def _check_manifest(obj: dict) -> list[str]:
    errors = []
    if not isinstance(obj.get("version"), str) or not obj["version"]:
        errors.append("manifest.version: 缺失或非字符串")
    if not isinstance(obj.get("generated_at"), str):
        errors.append("manifest.generated_at: 缺失或非字符串")
    filters = obj.get("filters")
    if not isinstance(filters, dict):
        errors.append("manifest.filters: 缺失或不是对象")
    else:
        for key in ("cities", "directions", "quarters"):
            if not _is_str_list(filters.get(key)):
                errors.append(f"manifest.filters.{key}: 必须是字符串数组")
    return errors


def _check_summary(obj: dict) -> list[str]:
    errors = []
    kpi = obj.get("kpi")
    if not isinstance(kpi, dict):
        return ["summary.kpi: 缺失或不是对象"]
    if not _is_int(kpi.get("total_jobs")):
        errors.append("summary.kpi.total_jobs: 必须是整数")
    avg = kpi.get("avg_salary")
    if not isinstance(avg, dict):
        errors.append("summary.kpi.avg_salary: 缺失或不是对象")
    else:
        for key in ("min", "max"):
            if not _num_or_none(avg.get(key)):
                errors.append(f"summary.kpi.avg_salary.{key}: 必须是数值或 null")
        if not isinstance(avg.get("unit"), str):
            errors.append("summary.kpi.avg_salary.unit: 缺失或非字符串")
    for key in ("cities_covered", "directions_covered"):
        if not _is_int(kpi.get(key)):
            errors.append(f"summary.kpi.{key}: 必须是整数")
    for key in ("yoy_job_growth", "qoq_salary_change"):
        if not _num_or_none(kpi.get(key)):
            errors.append(f"summary.kpi.{key}: 必须是数值或 null")
    for key in ("top_direction_by_growth", "top_direction_by_salary"):
        if obj.get(key) is not None and not isinstance(obj[key], str):
            errors.append(f"summary.{key}: 必须是字符串或 null")
    if obj.get("latest_snapshot_date") is not None and not isinstance(
        obj["latest_snapshot_date"], str
    ):
        errors.append("summary.latest_snapshot_date: 必须是字符串或 null")
    return errors


def _check_trend_series(obj: dict, dim: str, name: str) -> list[str]:
    errors = []
    series = obj.get(dim)
    if not isinstance(series, dict):
        return [f"{name}.{dim}: 缺失或不是对象"]
    for bucket, quarters in series.items():
        if not isinstance(quarters, dict):
            errors.append(f"{name}.{dim}.{bucket}: 不是对象")
            continue
        for qlabel, entry in quarters.items():
            ctx = f"{name}.{dim}.{bucket}.{qlabel}"
            if not isinstance(entry, dict):
                errors.append(f"{ctx}: 不是对象")
                continue
            for key in ("avg_salary_min", "avg_salary_max"):
                if not _num_or_none(entry.get(key)):
                    errors.append(f"{ctx}.{key}: 必须是数值或 null")
            if not _is_int(entry.get("job_count")):
                errors.append(f"{ctx}.job_count: 必须是整数")
    return errors


def _check_salary_trends(obj: dict) -> list[str]:
    errors = []
    if not _is_str_list(obj.get("metrics")):
        errors.append("salary_trends.metrics: 必须是字符串数组")
    errors += _check_trend_series(obj, "by_direction", "salary_trends")
    errors += _check_trend_series(obj, "by_city", "salary_trends")
    return errors


def _check_job_ranking(obj: dict) -> list[str]:
    errors = []
    rankings = obj.get("rankings")
    if not isinstance(rankings, list):
        errors.append("job_ranking.rankings: 必须是数组")
    else:
        for i, r in enumerate(rankings):
            ctx = f"job_ranking.rankings[{i}]"
            if not isinstance(r, dict):
                errors.append(f"{ctx}: 不是对象")
                continue
            if not _is_int(r.get("rank")):
                errors.append(f"{ctx}.rank: 必须是整数")
            if not isinstance(r.get("direction"), str):
                errors.append(f"{ctx}.direction: 必须是字符串")
            if not _is_int(r.get("job_count")):
                errors.append(f"{ctx}.job_count: 必须是整数")
            if not _num_or_none(r.get("share")):
                errors.append(f"{ctx}.share: 必须是数值或 null")
            if not _is_str_list(r.get("top_cities")):
                errors.append(f"{ctx}.top_cities: 必须是字符串数组")
    skills = obj.get("top_skills_across_all")
    if not isinstance(skills, list):
        errors.append("job_ranking.top_skills_across_all: 必须是数组")
    else:
        for i, s in enumerate(skills):
            ctx = f"job_ranking.top_skills_across_all[{i}]"
            if not isinstance(s, dict) or not isinstance(s.get("skill"), str):
                errors.append(f"{ctx}.skill: 必须是字符串")
            elif not _is_int(s.get("count")):
                errors.append(f"{ctx}.count: 必须是整数")
    return errors


def _check_str_int_map(v, ctx: str) -> list[str]:
    if not isinstance(v, dict):
        return [f"{ctx}: 必须是对象"]
    return [
        f"{ctx}.{k}: 必须是整数"
        for k, val in v.items()
        if not (isinstance(k, str) and _is_int(val))
    ]


def _check_edu_exp(obj: dict) -> list[str]:
    errors = _check_str_int_map(obj.get("education"), "edu_exp_distribution.education")
    errors += _check_str_int_map(obj.get("experience"), "edu_exp_distribution.experience")
    by_dir = obj.get("by_direction")
    if not isinstance(by_dir, dict):
        errors.append("edu_exp_distribution.by_direction: 缺失或不是对象")
    else:
        for d, slot in by_dir.items():
            if not isinstance(slot, dict):
                errors.append(f"edu_exp_distribution.by_direction.{d}: 不是对象")
                continue
            errors += _check_str_int_map(
                slot.get("education"), f"edu_exp_distribution.by_direction.{d}.education"
            )
            errors += _check_str_int_map(
                slot.get("experience"), f"edu_exp_distribution.by_direction.{d}.experience"
            )
    return errors


def _check_data_status(obj: dict) -> list[str]:
    errors = []
    snapshots = obj.get("snapshots")
    if not isinstance(snapshots, list):
        errors.append("data_status.snapshots: 必须是数组")
    else:
        for i, s in enumerate(snapshots):
            ctx = f"data_status.snapshots[{i}]"
            if not isinstance(s, dict) or not isinstance(s.get("date"), str):
                errors.append(f"{ctx}.date: 必须是字符串")
                continue
            if not _is_int(s.get("total_jobs")):
                errors.append(f"{ctx}.total_jobs: 必须是整数")
            errors += _check_str_int_map(s.get("cities"), f"{ctx}.cities")
    quality = obj.get("quality")
    if not isinstance(quality, dict):
        errors.append("data_status.quality: 缺失或不是对象")
    else:
        for key in ("salary_parse_rate", "jd_fulltext_rate", "duplicate_rate"):
            if not _num_or_none(quality.get(key)):
                errors.append(f"data_status.quality.{key}: 必须是数值或 null")
    if not isinstance(obj.get("collection_log"), list):
        errors.append("data_status.collection_log: 必须是数组")
    return errors


def _check_chart_specs(name: str, obj: dict) -> list[str]:
    errors = []
    specs = obj.get("chart_specs")
    if not isinstance(specs, dict) or not specs:
        return [f"{name}.chart_specs: 缺失或为空"]
    for key in CHART_SPEC_KEYS[name]:
        spec = specs.get(key)
        ctx = f"{name}.chart_specs.{key}"
        if not isinstance(spec, dict):
            errors.append(f"{ctx}: 缺失或不是对象")
            continue
        if not isinstance(spec.get("type"), str):
            errors.append(f"{ctx}.type: 缺失或非字符串")
        if not isinstance(spec.get("data"), list):
            errors.append(f"{ctx}.data: 必须是数组")
        if not isinstance(spec.get("layout"), dict):
            errors.append(f"{ctx}.layout: 必须是对象")
    return errors


_FILE_CHECKS = {
    "summary": _check_summary,
    "salary_trends": _check_salary_trends,
    "job_ranking": _check_job_ranking,
    "edu_exp_distribution": _check_edu_exp,
    "data_status": _check_data_status,
}


# ---------------------------------------------------------------- 入口


def _load_json(path: Path, ctx: str, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{ctx}: 读取或解析失败（{exc}）")
        return None


def check_all(directory: str | Path) -> list[str]:
    """校验目录下 6 个发布 JSON，返回错误列表（空 = 全部通过）。"""
    directory = Path(directory)
    errors: list[str] = []
    mpath = directory / "manifest.json"
    if not mpath.exists():
        return [f"manifest.json 不存在于 {directory}"]
    manifest = _load_json(mpath, "manifest.json", errors)

    payloads: dict[str, dict] = {}
    if isinstance(manifest, dict):
        datasets = manifest.get("datasets")
        if not isinstance(datasets, dict) or set(datasets) != set(DATASET_NAMES):
            errors.append(f"manifest.datasets: 键集合必须等于 {sorted(DATASET_NAMES)}")
        else:
            for name, fname in datasets.items():
                if fname != f"{name}.json":
                    errors.append(f"manifest.datasets.{name}: 应为 {name}.json，实际 {fname}")
                fpath = directory / str(fname)
                if not fpath.exists():
                    errors.append(f"{fname}: 文件不存在")
                    continue
                obj = _load_json(fpath, str(fname), errors)
                if isinstance(obj, dict):
                    payloads[name] = obj
            # 一一对应：目录内除 manifest.json 外的 *.json 必须全部在 datasets 登记
            on_disk = {p.name for p in directory.glob("*.json")} - {"manifest.json"}
            extra = on_disk - set(datasets.values())
            if extra:
                errors.append(f"目录内存在未登记的 JSON 文件: {sorted(extra)}")
        errors += _check_manifest(manifest)

    for name, obj in payloads.items():
        errors += _FILE_CHECKS[name](obj)
        if name in CHART_SPEC_KEYS:
            errors += _check_chart_specs(name, obj)
    return errors


def main(argv: list[str] | None = None) -> int:
    directory = Path(argv[0]) if argv else DEFAULT_DIR
    errors = check_all(directory)
    if errors:
        for err in errors:
            print(f"format_check: {err}", file=sys.stderr)
        return 1
    print(f"format_check: {directory} 下 6 个 JSON 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
