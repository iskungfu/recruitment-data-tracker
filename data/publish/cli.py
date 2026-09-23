"""发布管线 — python -m data.publish.cli

从 SQLite 读全量数据 → 调 analysis 公开函数预计算 → 输出 6 个 JSON 到 data/publish/v1/。

架构契约：06-website-architecture-v1.0.md §3.2（6 个 JSON 的 schema）。
冻结约束：不改 analysis/* 源码，仅 import 公开函数
（compute_yoy_qoq / analyze_keywords / get_quarter_of / quarter_label）。
方向归属启发式与 analysis.stats._attribute_direction 同口径——该函数为私有
不可 import，在此平行实现：关键词按长度降序、大小写不敏感、job_name 子串命中。

空库降级：库已建表但无岗位数据时仍输出 6 个合法 JSON
（数值 0 / null、列表为空、chart_specs 结构保留），format_check 全过才算成功。

用法：
    python -m data.publish.cli                          # 默认 data/recruitment.db → data/publish/v1/
    python -m data.publish.cli --db data/demo.db        # 指定库
    python -m data.publish.cli --out /tmp/v1            # 指定输出目录
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import plotly.graph_objects as go

from analysis.keywords import analyze_keywords
from analysis.stats import compute_yoy_qoq, get_quarter_of, quarter_label
from data.publish import format_check

#: 发布产物署名（manifest.generated_by）
PUBLISH_AGENT = "tracker-publish v0.1"
#: 默认数据源（core.config.Settings.db_path 同值，避免 import config 引发 yaml 依赖）
DEFAULT_DB = Path("data/recruitment.db")
DEFAULT_OUT = Path("data/publish/v1")
SALARY_UNIT_LABEL = "K/月"

#: 5 个数据集（manifest 本身不在其中），顺序即 manifest.datasets 顺序
DATASET_NAMES = (
    "summary",
    "salary_trends",
    "job_ranking",
    "edu_exp_distribution",
    "data_status",
)

#: 经验取值展示排序；未知取值按字典序接在已知之后
_EXPERIENCE_ORDER = (
    "在校/应届",
    "应届",
    "1-3年",
    "3-5年",
    "5-10年",
    "10年以上",
    "经验不限",
    "未标注",
)


# ================================================================ 基础读取


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _load_keyword_map(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """keywords 表 → [(keyword, direction)]，按关键词长度降序（长词优先命中）。"""
    rows = conn.execute("SELECT keyword, direction FROM keywords WHERE is_active = 1").fetchall()
    pairs = [(r["keyword"], r["direction"]) for r in rows]
    pairs.sort(key=lambda kd: len(kd[0]), reverse=True)
    return pairs


def _attribute_direction(job_name: str | None, keyword_map: list[tuple[str, str]]) -> str | None:
    """job_name 子串命中关键词 → 方向。与 analysis.stats._attribute_direction 同口径。"""
    name = (job_name or "").lower()
    for keyword, direction in keyword_map:
        if keyword.lower() in name:
            return direction
    return None


def _city_label(row: sqlite3.Row) -> str:
    """城市展示名；缺失兜底与 analysis.stats（P3-4 修复）同口径。"""
    return row["city_name"] or (f"city_{row['city_id']}" if row["city_id"] else "未知城市")


# ================================================================ 聚合


def _new_bucket() -> dict:
    # job_count 计全部行（含未解析薪资），薪资只计月薪且解析成功行——
    # 与 compute_yoy_qoq._add 同口径
    return {"job_count": 0, "min_sum": 0.0, "max_sum": 0.0, "salary_n": 0, "cities": {}}


def _add(bucket: dict, row: sqlite3.Row) -> None:
    bucket["job_count"] += 1
    if (
        row["salary_unit"] == "month"
        and row["salary_min"] is not None
        and row["salary_max"] is not None
    ):
        bucket["min_sum"] += row["salary_min"]
        bucket["max_sum"] += row["salary_max"]
        bucket["salary_n"] += 1
    city = _city_label(row)
    bucket["cities"][city] = bucket["cities"].get(city, 0) + 1


def _avg_min(bucket: dict) -> float | None:
    return None if bucket["salary_n"] == 0 else bucket["min_sum"] / bucket["salary_n"]


def _avg_max(bucket: dict) -> float | None:
    return None if bucket["salary_n"] == 0 else bucket["max_sum"] / bucket["salary_n"]


def _avg_mid(bucket: dict) -> float | None:
    if bucket["salary_n"] == 0:
        return None
    return (bucket["min_sum"] + bucket["max_sum"]) / (2 * bucket["salary_n"])


def _round(v: float | None, ndigits: int = 2) -> float | None:
    return None if v is None else round(v, ndigits)


def _collect(conn: sqlite3.Connection, keyword_map: list[tuple[str, str]]):
    """全量岗位 → 三维度季度桶。

    Returns:
        (overall, by_direction, by_city, current_key)
        每桶 {QuarterKey: bucket}；current_key 为最大采集日所在季度，无数据为 None。
    """
    rows = conn.execute(
        "SELECT j.job_name, j.salary_min, j.salary_max, j.salary_unit, j.city_id, "
        "       c.name AS city_name, j.education, j.experience, j.snapshot_date "
        "FROM job_snapshot j LEFT JOIN cities c ON c.id = j.city_id"
    ).fetchall()
    overall: dict[tuple[int, int], dict] = {}
    by_direction: dict[str, dict[tuple[int, int], dict]] = {}
    by_city: dict[str, dict[tuple[int, int], dict]] = {}
    quarters: set[tuple[int, int]] = set()
    for row in rows:
        key = get_quarter_of(date.fromisoformat(row["snapshot_date"]))
        quarters.add(key)
        _add(overall.setdefault(key, _new_bucket()), row)
        _add(by_city.setdefault(_city_label(row), {}).setdefault(key, _new_bucket()), row)
        direction = _attribute_direction(row["job_name"], keyword_map)
        if direction:
            _add(by_direction.setdefault(direction, {}).setdefault(key, _new_bucket()), row)
    current = max(quarters) if quarters else None
    return overall, by_direction, by_city, current


# ================================================================ 图表 spec


def _spec(chart_type: str, fig: go.Figure) -> dict:
    """Plotly Figure → {type, data, layout}（网站直接 Plotly.react(data, layout)）。"""
    payload = json.loads(fig.to_json())
    return {"type": chart_type, "data": payload["data"], "layout": payload["layout"]}


def _fig_direction_comparison(by_direction: dict, current: tuple[int, int] | None) -> go.Figure:
    """本季各方向均值薪资下限/上限分组柱状（按岗位数降序）。"""
    items = []
    if current is not None:
        for d, qs in by_direction.items():
            b = qs.get(current)
            if b:
                items.append((d, _avg_min(b), _avg_max(b), b["job_count"]))
    items.sort(key=lambda t: -t[3])
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[t[0] for t in items], y=[_round(t[1]) for t in items], name="均值下限"))
    fig.add_trace(go.Bar(x=[t[0] for t in items], y=[_round(t[2]) for t in items], name="均值上限"))
    fig.update_layout(
        barmode="group",
        height=380,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        yaxis_title="K/月",
        legend_title="薪资",
    )
    return fig


def _fig_city_comparison(by_city: dict) -> go.Figure:
    """分城市薪资趋势折线（x=季度，y=月薪中点均值）。"""
    quarters = sorted({q for qs in by_city.values() for q in qs})
    labels = [quarter_label(q) for q in quarters]
    fig = go.Figure()
    for city, qs in sorted(by_city.items()):
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=[_round(_avg_mid(qs[q])) if q in qs else None for q in quarters],
                mode="lines+markers",
                name=city,
                connectgaps=False,
            )
        )
    fig.update_layout(
        height=380,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        yaxis_title="K/月",
        legend_title="城市",
    )
    return fig


def _fig_ranking_bar(rankings: list[dict]) -> go.Figure:
    """方向岗位数排行水平条形图（第一在顶部）。"""
    items = [(r["direction"], r["job_count"]) for r in rankings][::-1]
    fig = go.Figure(go.Bar(x=[c for _, c in items], y=[d for d, _ in items], orientation="h"))
    fig.update_layout(
        height=420, margin={"l": 100, "r": 20, "t": 30, "b": 40}, xaxis_title="岗位数"
    )
    return fig


def _fig_skills_bar(top_skills: list[dict]) -> go.Figure:
    """技能高频词水平条形图（词云替代——Plotly 无原生词云，等频条形可交互）。"""
    items = [(s["skill"], s["count"]) for s in top_skills][::-1]
    fig = go.Figure(go.Bar(x=[c for _, c in items], y=[w for w, _ in items], orientation="h"))
    fig.update_layout(height=520, margin={"l": 120, "r": 20, "t": 30, "b": 40}, xaxis_title="频次")
    return fig


def _fig_edu_pie(education: dict[str, int]) -> go.Figure:
    fig = go.Figure(
        go.Pie(
            labels=list(education),
            values=list(education.values()),
            hole=0.35,
            textinfo="label+percent",
            textposition="outside",
        )
    )
    fig.update_layout(height=340, margin={"l": 20, "r": 20, "t": 30, "b": 20}, legend_title="学历")
    return fig


def _fig_exp_stacked(by_direction_exp: dict[str, dict[str, int]]) -> go.Figure:
    """经验 × 方向堆叠柱状：x=方向（按总量降序），每个经验档一条 trace。"""
    directions = sorted(by_direction_exp, key=lambda d: -sum(by_direction_exp[d].values()))
    buckets: list[str] = [
        b for b in _EXPERIENCE_ORDER if any(b in by_direction_exp[d] for d in directions)
    ]
    buckets += sorted({b for d in directions for b in by_direction_exp[d]} - set(buckets))
    fig = go.Figure()
    for bucket in buckets:
        fig.add_trace(
            go.Bar(
                x=directions,
                y=[by_direction_exp[d].get(bucket, 0) for d in directions],
                name=bucket,
            )
        )
    fig.update_layout(
        barmode="stack",
        height=380,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        yaxis_title="岗位数",
        legend_title="经验",
    )
    return fig


# ================================================================ 各数据集


def _build_summary(
    yoy: dict,
    overall: dict,
    by_direction: dict,
    by_city: dict,
    current: tuple[int, int] | None,
    latest_date: str | None,
) -> dict:
    """summary.json —— 首页 4 KPI 卡片 + 两个 Top 方向（架构 §3.2）。"""
    cur = overall.get(current, _new_bucket()) if current else _new_bucket()
    o = yoy.get("overall") or {}

    def _qoq_job(d: str) -> float | None:
        return (yoy["by_direction"].get(d) or {}).get("qoq", {}).get("job_count")

    growth_candidates = [(d, g) for d in by_direction if (g := _qoq_job(d)) is not None]
    top_growth = max(growth_candidates, key=lambda t: t[1])[0] if growth_candidates else None
    salary_candidates = [
        (d, s)
        for d, qs in by_direction.items()
        if current is not None and qs.get(current) and (s := _avg_mid(qs[current])) is not None
    ]
    top_salary = max(salary_candidates, key=lambda t: t[1])[0] if salary_candidates else None

    return {
        "kpi": {
            "total_jobs": cur["job_count"],
            "avg_salary": {
                "min": _round(_avg_min(cur)),
                "max": _round(_avg_max(cur)),
                "unit": SALARY_UNIT_LABEL,
            },
            "cities_covered": sum(
                1 for qs in by_city.values() if current is not None and qs.get(current)
            ),
            "directions_covered": sum(
                1 for qs in by_direction.values() if current is not None and qs.get(current)
            ),
            "yoy_job_growth": (o.get("yoy") or {}).get("job_count"),
            "qoq_salary_change": (o.get("qoq") or {}).get("avg_salary"),
        },
        "top_direction_by_growth": top_growth,
        "top_direction_by_salary": top_salary,
        "latest_snapshot_date": latest_date,
    }


def _build_salary_trends(
    yoy: dict, by_direction: dict, by_city: dict, current: tuple[int, int] | None
) -> dict:
    """salary_trends.json —— 方向/城市双维度季度序列 + 本季同比环比（架构 §3.2）。"""
    cur_label = quarter_label(current) if current else None

    def _series(dim_buckets: dict, yoy_dim: dict, extra_key: str) -> dict:
        out = {}
        for name, qs in sorted(dim_buckets.items()):
            series = {}
            for key in sorted(qs):
                b = qs[key]
                label = quarter_label(key)
                entry = {
                    "avg_salary_min": _round(_avg_min(b)),
                    "avg_salary_max": _round(_avg_max(b)),
                    "job_count": b["job_count"],
                }
                # 同比/环比只对当前季度有定义（compute_yoy_qoq 口径），历史季度置 None
                yoy_entry = (yoy_dim.get(name) or {}) if label == cur_label else {}
                if extra_key == "direction":
                    entry["yoy_job_count"] = (yoy_entry.get("yoy") or {}).get("job_count")
                    entry["qoq_job_count"] = (yoy_entry.get("qoq") or {}).get("job_count")
                else:
                    entry["yoy_salary"] = (yoy_entry.get("yoy") or {}).get("avg_salary")
                series[label] = entry
            out[name] = series
        return out

    return {
        "metrics": ["avg_salary_min", "avg_salary_max", "job_count"],
        "by_direction": _series(by_direction, yoy.get("by_direction") or {}, "direction"),
        "by_city": _series(by_city, yoy.get("by_city") or {}, "city"),
        "chart_specs": {
            "direction_comparison": _spec("bar", _fig_direction_comparison(by_direction, current)),
            "city_comparison": _spec("line", _fig_city_comparison(by_city)),
        },
    }


def _build_job_ranking(
    db_path: Path, yoy: dict, by_direction: dict, current: tuple[int, int] | None
) -> dict:
    """job_ranking.json —— 方向需求排行 + 技能 Top 20（架构 §3.2）。"""
    ranked = []
    if current is not None:
        for d, qs in by_direction.items():
            b = qs.get(current)
            if b:
                ranked.append((d, b))
    ranked.sort(key=lambda t: (-t[1]["job_count"], t[0]))
    total = sum(b["job_count"] for _, b in ranked)
    rankings = []
    for i, (d, b) in enumerate(ranked, 1):
        top_cities = sorted(b["cities"].items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        rankings.append(
            {
                "rank": i,
                "direction": d,
                "job_count": b["job_count"],
                "share": round(b["job_count"] / total, 4) if total else None,
                "top_cities": [name for name, _ in top_cities],
                "yoy_change": ((yoy["by_direction"].get(d) or {}).get("yoy") or {}).get(
                    "job_count"
                ),
            }
        )

    top_skills = [
        {"skill": word, "count": count} for word, count in analyze_keywords(db_path, top_n=20)
    ]
    return {
        "rankings": rankings,
        "top_skills_across_all": top_skills,
        "chart_specs": {
            "ranking_bar": _spec("barh", _fig_ranking_bar(rankings)),
            "skills_wordcloud": _spec("bar", _fig_skills_bar(top_skills)),
        },
    }


def _build_edu_exp(
    conn: sqlite3.Connection, keyword_map: list[tuple[str, str]], current: tuple[int, int] | None
) -> dict:
    """edu_exp_distribution.json —— 本季学历/经验分布（整体 + 按方向）（架构 §3.2）。"""
    education: dict[str, int] = {}
    experience: dict[str, int] = {}
    by_dir: dict[str, dict[str, dict[str, int]]] = {}
    if current is not None:
        rows = conn.execute(
            "SELECT j.job_name, j.education, j.experience, j.snapshot_date FROM job_snapshot j"
        ).fetchall()

        def _bump(dist: dict[str, int], key: str) -> None:
            dist[key] = dist.get(key, 0) + 1

        for row in rows:
            if get_quarter_of(date.fromisoformat(row["snapshot_date"])) != current:
                continue
            edu = row["education"] or "未标注"
            exp = row["experience"] or "未标注"
            _bump(education, edu)
            _bump(experience, exp)
            direction = _attribute_direction(row["job_name"], keyword_map)
            if direction:
                slot = by_dir.setdefault(direction, {"education": {}, "experience": {}})
                _bump(slot["education"], edu)
                _bump(slot["experience"], exp)

    education = dict(sorted(education.items(), key=lambda kv: -kv[1]))
    experience = dict(
        sorted(
            experience.items(),
            key=lambda kv: (
                _EXPERIENCE_ORDER.index(kv[0])
                if kv[0] in _EXPERIENCE_ORDER
                else len(_EXPERIENCE_ORDER),
                kv[0],
            ),
        )
    )
    exp_by_dir = {d: slot["experience"] for d, slot in by_dir.items()}
    return {
        "education": education,
        "experience": experience,
        "by_direction": by_dir,
        "chart_specs": {
            "edu_pie": _spec("pie", _fig_edu_pie(education)),
            "exp_bar_by_dir": _spec("bar", _fig_exp_stacked(exp_by_dir)),
        },
    }


def _build_data_status(conn: sqlite3.Connection) -> dict:
    """data_status.json —— 采集快照历史 + 质量指标 + 采集日志（架构 §3.2）。

    质量口径：
    - salary_parse_rate: salary_min/max 均非空的占比（全量）
    - jd_fulltext_rate:  jd_fulltext 非空占比（全量）
    - duplicate_rate:    1 - distinct(encrypt_job_id, snapshot_date) / 总数
                         （与 core.cleansing.dedup_jobs 的去重键同口径；
                         库内已经 importer 去重，正常应接近 0）
    """
    per_date: dict[str, dict] = {}
    for row in conn.execute(
        "SELECT j.snapshot_date AS d, j.city_id, c.name AS city_name, COUNT(*) AS n "
        "FROM job_snapshot j LEFT JOIN cities c ON c.id = j.city_id "
        "GROUP BY j.snapshot_date, j.city_id"
    ):
        slot = per_date.setdefault(row["d"], {"date": row["d"], "total_jobs": 0, "cities": {}})
        city = row["city_name"] or (f"city_{row['city_id']}" if row["city_id"] else "未知城市")
        slot["cities"][city] = slot["cities"].get(city, 0) + row["n"]
        slot["total_jobs"] += row["n"]
    snapshots = [per_date[d] for d in sorted(per_date, reverse=True)]

    q = conn.execute(
        "SELECT COUNT(*) AS total, "
        "  SUM(CASE WHEN salary_min IS NOT NULL AND salary_max IS NOT NULL "
        "      THEN 1 ELSE 0 END) AS parsed, "
        "  SUM(CASE WHEN jd_fulltext IS NOT NULL AND jd_fulltext != '' "
        "      THEN 1 ELSE 0 END) AS jd, "
        "  COUNT(DISTINCT COALESCE(encrypt_job_id, job_id, 'row-' || id) || '|' "
        "      || snapshot_date) AS distinct_keys "
        "FROM job_snapshot"
    ).fetchone()
    total = q["total"] or 0
    quality = {
        "salary_parse_rate": round((q["parsed"] or 0) / total, 4) if total else None,
        "jd_fulltext_rate": round((q["jd"] or 0) / total, 4) if total else None,
        "duplicate_rate": round(1 - (q["distinct_keys"] or 0) / total, 4) if total else None,
    }

    collection_log = [
        {
            "keyword": r["keyword"],
            "city": r["city_name"],
            "status": r["status"],
            "pages": None,  # snapshots 表无页数字段（schema 冻结不可加列）
            "jobs": r["job_count"],
        }
        for r in conn.execute(
            "SELECT keyword, city_name, status, job_count FROM snapshots ORDER BY id"
        )
    ]
    return {"snapshots": snapshots, "quality": quality, "collection_log": collection_log}


def _build_manifest(
    conn: sqlite3.Connection, yoy: dict, latest_date: str | None, quarters: list[str]
) -> dict:
    """manifest.json —— 网站首先加载的索引；filters 全部从库里动态读取（不写死）。"""
    cities = [
        r["name"] for r in conn.execute("SELECT name FROM cities WHERE is_active = 1 ORDER BY id")
    ]
    directions = [
        r["direction"]
        for r in conn.execute(
            "SELECT direction FROM keywords WHERE is_active = 1 GROUP BY direction ORDER BY MIN(id)"
        )
    ]
    return {
        "version": yoy["current_quarter"] or "empty",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": PUBLISH_AGENT,
        "data_snapshot_date": latest_date,
        "datasets": {name: f"{name}.json" for name in DATASET_NAMES},
        "filters": {"cities": cities, "directions": directions, "quarters": quarters},
    }


# ================================================================ 编排


def run(db_path: str | Path, out_dir: str | Path) -> int:
    """执行发布全流程：读库 → 生成 6 JSON → format_check。返回进程退出码。"""
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    if not db_path.exists():
        print(f"错误：数据库不存在 {db_path}（先运行采集或检查 --db 参数）", file=sys.stderr)
        return 2

    # ① 同比/环比（analysis 公开函数，三维度）
    yoy = compute_yoy_qoq(db_path)
    conn = _connect(db_path)
    try:
        keyword_map = _load_keyword_map(conn)
        # ② 全量聚合（季度 × 方向/城市）
        overall, by_direction, by_city, current = _collect(conn, keyword_map)
        latest_date = conn.execute("SELECT MAX(snapshot_date) AS d FROM job_snapshot").fetchone()[
            "d"
        ]
        quarters = sorted(
            {quarter_label(k) for qs in by_city.values() for k in qs}
            | {quarter_label(k) for k in overall}
        )

        payloads = {
            "summary": _build_summary(yoy, overall, by_direction, by_city, current, latest_date),
            "salary_trends": _build_salary_trends(yoy, by_direction, by_city, current),
            "job_ranking": _build_job_ranking(db_path, yoy, by_direction, current),
            "edu_exp_distribution": _build_edu_exp(conn, keyword_map, current),
            "data_status": _build_data_status(conn),
        }
        manifest = _build_manifest(conn, yoy, latest_date, quarters)
    finally:
        conn.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in payloads.items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    mpath = out_dir / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(mpath)

    errors = format_check.check_all(out_dir)
    if errors:
        for err in errors:
            print(f"format_check: {err}", file=sys.stderr)
        return 1
    cur = manifest["version"]
    total = payloads["summary"]["kpi"]["total_jobs"]
    print(f"发布完成：{len(written)} 个 JSON → {out_dir}（version={cur}, 本季岗位数={total}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m data.publish.cli",
        description="发布管线：SQLite → 6 个静态 JSON（网站经 jsDelivr CDN 加载）",
    )
    parser.add_argument(
        "--db", default=str(DEFAULT_DB), help=f"SQLite 数据库路径（默认 {DEFAULT_DB}）"
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"输出目录（默认 {DEFAULT_OUT}）")
    args = parser.parse_args(argv)
    return run(args.db, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
