"""HTML 报告生成 — Week 3

generate_report(db_path, city=None) → 单文件 HTML 报告路径。
模板用 string.Template（图表 HTML 作为替换值注入，模板文本自身不含 $），
Plotly.js 内嵌一次，浏览器直接打开即可，无需网络 / 服务。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from string import Template

import plotly.graph_objects as go
import plotly.io as pio

from analysis.keywords import analyze_keywords
from analysis.stats import (
    _attribute_direction,
    compute_yoy_qoq,
    get_quarter_of,
    quarter_label,
)

DEFAULT_OUTPUT = Path("report.html")

_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>招聘数据季度报告 — $scope</title>
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         margin: 0 auto; max-width: 1100px; padding: 24px; color: #1f2329; }
  h1 { font-size: 24px; } h2 { font-size: 18px; margin-top: 36px;
       border-left: 4px solid #3370ff; padding-left: 8px; }
  .meta { color: #8f959e; font-size: 13px; }
  .kpis { display: flex; gap: 16px; flex-wrap: wrap; margin: 20px 0; }
  .kpi { flex: 1; min-width: 200px; background: #f5f6f7; border-radius: 8px; padding: 16px; }
  .kpi .label { font-size: 13px; color: #8f959e; }
  .kpi .value { font-size: 26px; font-weight: 600; margin-top: 6px; }
  .kpi .sub { font-size: 12px; color: #646a73; margin-top: 4px; }
  table { border-collapse: collapse; font-size: 13px; margin: 8px 0; }
  th, td { border: 1px solid #dee0e3; padding: 6px 12px; text-align: right; }
  th { background: #f5f6f7; } td:first-child, th:first-child { text-align: left; }
</style>
</head>
<body>
<h1>招聘数据季度报告 · $current_quarter</h1>
<p class="meta">范围：$scope ｜ 生成时间：$generated_at ｜ 数据源：job_snapshot（SQLite）</p>

<div class="kpis">
  <div class="kpi"><div class="label">总岗位数（全部季度）</div>
    <div class="value">$kpi_total</div><div class="sub">本季 $kpi_quarter_count 条</div></div>
  <div class="kpi"><div class="label">本季均值月薪（K/月，中点）</div>
    <div class="value">$kpi_avg_salary</div><div class="sub">日薪/时薪岗不参与</div></div>
  <div class="kpi"><div class="label">岗位数环比（QoQ）</div>
    <div class="value">$kpi_qoq</div><div class="sub">同比 $kpi_yoy</div></div>
</div>

<h2>五城岗位数排行（本季）</h2>
$city_rank

<h2>薪资趋势（分城市，月薪中点均值 K/月）</h2>
$chart_trend

<h2>方向薪资对比（本季，均值 K/月）</h2>
$chart_direction

<h2>JD 高频词 Top 20</h2>
$chart_keywords

<h2>学历要求分布（本季）</h2>
$chart_edu

<h2>经验要求分布（本季）</h2>
$chart_exp

<h2>方向明细（同比 / 环比）</h2>
$direction_table
</body>
</html>
""")


def _fmt_pct(v: float | None) -> str:
    """百分比格式化：None → "—"，0.2 → "+20.0%" """
    if v is None:
        return "—"
    return f"{v:+.1%}"


def _fmt_salary(v: float | None) -> str:
    """薪资格式化：None → "—"，30.0 → "30.0K" """
    return "—" if v is None else f"{v:.1f}K"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _city_filter_sql(conn: sqlite3.Connection, city: str | int | None) -> tuple[str, list]:
    """与 compute_yoy_qoq 同口径的城市过滤（str=城市名，int=city_id）。"""
    if city is None:
        return "", []
    if isinstance(city, int):
        return "AND j.city_id = ?", [city]
    row = conn.execute("SELECT id FROM cities WHERE name = ?", (city,)).fetchone()
    if row is None:
        raise ValueError(f"未知城市: {city}")
    return "AND j.city_id = ?", [row["id"]]


def _quarterly_salary_by_city(
    conn: sqlite3.Connection, city: str | int | None
) -> dict[str, dict[str, float]]:
    """{城市: {季度标签: 月薪中点均值}}，日薪/时薪不参与。"""
    where, params = _city_filter_sql(conn, city)
    rows = conn.execute(
        "SELECT c.name AS city_name, j.salary_min, j.salary_max, j.snapshot_date "
        "FROM job_snapshot j JOIN cities c ON c.id = j.city_id "
        "WHERE j.salary_unit = 'month' AND j.salary_min IS NOT NULL "
        f"AND j.salary_max IS NOT NULL {where}",
        params,
    ).fetchall()
    agg: dict[str, dict[tuple[int, int], list[float]]] = {}
    for r in rows:
        key = get_quarter_of(datetime.strptime(r["snapshot_date"], "%Y-%m-%d").date())
        agg.setdefault(r["city_name"], {}).setdefault(key, []).append(
            (r["salary_min"] + r["salary_max"]) / 2
        )
    return {
        city_name: {quarter_label(k): sum(v) / len(v) for k, v in sorted(qs.items())}
        for city_name, qs in sorted(agg.items())
    }


def _direction_salary_current(
    conn: sqlite3.Connection, city: str | int | None, current_key: tuple[int, int]
) -> list[tuple[str, float, float]]:
    """本季各方向 (direction, avg_salary_min, avg_salary_max)，启发式归属。"""
    where, params = _city_filter_sql(conn, city)
    rows = conn.execute(
        "SELECT j.job_name, j.salary_min, j.salary_max, j.snapshot_date "
        "FROM job_snapshot j WHERE j.salary_unit = 'month' "
        f"AND j.salary_min IS NOT NULL AND j.salary_max IS NOT NULL {where}",
        params,
    ).fetchall()
    keyword_map = sorted(
        (
            (r["keyword"], r["direction"])
            for r in conn.execute(
                "SELECT keyword, direction FROM keywords WHERE is_active = 1"
            ).fetchall()
        ),
        key=lambda kd: len(kd[0]),
        reverse=True,
    )
    agg: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        key = get_quarter_of(datetime.strptime(r["snapshot_date"], "%Y-%m-%d").date())
        if key != current_key:
            continue
        direction = _attribute_direction(r["job_name"], keyword_map)
        if direction:
            agg.setdefault(direction, []).append((r["salary_min"], r["salary_max"]))
    return [
        (d, sum(p[0] for p in pairs) / len(pairs), sum(p[1] for p in pairs) / len(pairs))
        for d, pairs in sorted(agg.items())
    ]


def _distribution_current(
    conn: sqlite3.Connection, column: str, city: str | int | None,
    current_key: tuple[int, int],
) -> dict[str, int]:
    """本季某字段（education / experience）取值分布；NULL → 未标注。"""
    assert column in ("education", "experience")  # 防注入：只允许白名单列
    where, params = _city_filter_sql(conn, city)
    rows = conn.execute(
        f"SELECT j.{column} AS v, j.snapshot_date FROM job_snapshot j WHERE 1=1 {where}",
        params,
    ).fetchall()
    dist: dict[str, int] = {}
    for r in rows:
        key = get_quarter_of(datetime.strptime(r["snapshot_date"], "%Y-%m-%d").date())
        if key != current_key:
            continue
        dist[r["v"] or "未标注"] = dist.get(r["v"] or "未标注", 0) + 1
    return dict(sorted(dist.items(), key=lambda kv: -kv[1]))


def _city_rank_current(
    conn: sqlite3.Connection, current_key: tuple[int, int]
) -> list[tuple[str, int]]:
    """本季各城市岗位数排行（报告固定展示五城，不受 city 过滤影响）。"""
    rows = conn.execute(
        "SELECT c.name AS city_name, j.snapshot_date "
        "FROM job_snapshot j JOIN cities c ON c.id = j.city_id"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        key = get_quarter_of(datetime.strptime(r["snapshot_date"], "%Y-%m-%d").date())
        if key == current_key:
            counts[r["city_name"]] = counts.get(r["city_name"], 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _total_count(conn: sqlite3.Connection, city: str | int | None) -> int:
    where, params = _city_filter_sql(conn, city)
    return conn.execute(
        f"SELECT COUNT(*) c FROM job_snapshot j WHERE 1=1 {where}", params
    ).fetchone()["c"]


def _fig_trend(series: dict[str, dict[str, float]]) -> go.Figure:
    """薪资趋势折线：x=季度，y=均值月薪中点，每城一条线。"""
    fig = go.Figure()
    quarters = sorted({q for qs in series.values() for q in qs})
    for city_name, qs in series.items():
        fig.add_trace(
            go.Scatter(x=quarters, y=[qs.get(q) for q in quarters],
                       mode="lines+markers", name=city_name, connectgaps=False)
        )
    fig.update_layout(height=380, margin=dict(l=40, r=20, t=30, b=40),
                      yaxis_title="K/月", legend_title="城市")
    return fig


def _fig_direction(data: list[tuple[str, float, float]]) -> go.Figure:
    """方向薪资分组柱状：每方向 avg_min / avg_max 两根。"""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[d for d, _, _ in data], y=[lo for _, lo, _ in data],
                         name="均值下限"))
    fig.add_trace(go.Bar(x=[d for d, _, _ in data], y=[hi for _, _, hi in data],
                         name="均值上限"))
    fig.update_layout(barmode="group", height=380,
                      margin=dict(l=40, r=20, t=30, b=40), yaxis_title="K/月")
    return fig


def _fig_keywords(pairs: list[tuple[str, int]]) -> go.Figure:
    """高频词水平条形图（Top 20，高频在上）。"""
    top = pairs[:20][::-1]
    fig = go.Figure(go.Bar(x=[c for _, c in top], y=[w for w, _ in top],
                           orientation="h"))
    fig.update_layout(height=520, margin=dict(l=120, r=20, t=30, b=40))
    return fig


def _fig_pie(dist: dict[str, int], title: str) -> go.Figure:
    """学历/经验分布饼图。labels=取值名，values=频次（dict.values()，勿传键列表）。"""
    fig = go.Figure(
        go.Pie(labels=list(dist), values=list(dist.values()), hole=0.35,
               textinfo="label+percent", textposition="outside")
    )
    fig.update_layout(height=340, margin=dict(l=20, r=20, t=30, b=20),
                      legend_title=title)
    return fig


def _city_rank_html(rank: list[tuple[str, int]]) -> str:
    if not rank:
        return "<p class='meta'>本季暂无数据</p>"
    rows = "".join(
        f"<tr><td>{i}</td><td>{name}</td><td>{count}</td></tr>"
        for i, (name, count) in enumerate(rank, 1)
    )
    return f"<table><tr><th>#</th><th>城市</th><th>岗位数</th></tr>{rows}</table>"


def _direction_table_html(by_direction: dict) -> str:
    if not by_direction:
        return "<p class='meta'>本季暂无可归属方向的岗位</p>"
    rows = "".join(
        f"<tr><td>{d}</td><td>{r['job_count']}</td>"
        f"<td>{_fmt_salary(r['avg_salary'])}</td>"
        f"<td>{_fmt_pct(r['qoq']['job_count'])}</td>"
        f"<td>{_fmt_pct(r['yoy']['job_count'])}</td>"
        f"<td>{_fmt_pct(r['qoq']['avg_salary'])}</td>"
        f"<td>{_fmt_pct(r['yoy']['avg_salary'])}</td></tr>"
        for d, r in by_direction.items()
    )
    return (
        "<table><tr><th>方向</th><th>本季岗位数</th><th>均值月薪</th>"
        "<th>岗位数环比</th><th>岗位数同比</th><th>薪资环比</th><th>薪资同比</th></tr>"
        f"{rows}</table>"
    )


def _to_divs(figs: list[go.Figure]) -> list[str]:
    """Plotly 图 → HTML div；plotly.js 只在第一张图内嵌一次。"""
    divs = []
    for i, fig in enumerate(figs):
        divs.append(
            pio.to_html(fig, full_html=False, include_plotlyjs=(i == 0))
        )
    return divs


def generate_report(
    db_path: str | Path,
    city: str | int | None = None,
    output_path: str | Path = DEFAULT_OUTPUT,
) -> str:
    """生成单文件 HTML 季度报告，返回输出路径字符串。

    内容：KPI 卡片（总岗位数 / 五城排行 / 本季均值月薪）、薪资趋势折线
    （分城市）、方向薪资分组柱状、JD 高频词条形图、学历/经验分布饼图、
    方向同比环比明细表。city 过滤口径与 compute_yoy_qoq 一致；
    日薪/时薪岗位不参与所有薪资均值。
    """
    yoy = compute_yoy_qoq(db_path, city)
    conn = _connect(db_path)
    try:
        total = _total_count(conn, city)
        if yoy["current_quarter"] is None:
            current_key = None
        else:
            current_key = (
                int(yoy["current_quarter"][:4]),
                int(yoy["current_quarter"][-1]),
            )
        trend = _quarterly_salary_by_city(conn, city)
        rank = _city_rank_current(conn, current_key) if current_key else []
        direction_salary = (
            _direction_salary_current(conn, city, current_key) if current_key else []
        )
        edu = _distribution_current(conn, "education", city, current_key) if current_key else {}
        exp = _distribution_current(conn, "experience", city, current_key) if current_key else {}
    finally:
        conn.close()

    keywords = analyze_keywords(db_path, top_n=50)
    if keywords:
        figs = [
            _fig_trend(trend),
            _fig_direction(direction_salary),
            _fig_keywords(keywords),
            _fig_pie(edu, "学历"),
            _fig_pie(exp, "经验"),
        ]
        chart_trend, chart_direction, chart_keywords, chart_edu, chart_exp = _to_divs(figs)
    else:
        # 无 JD 全文（列表页采集未回填详情时 jd_fulltext 为空）→ 高频词区占位
        chart_trend, chart_direction, chart_edu, chart_exp = _to_divs(
            [_fig_trend(trend), _fig_direction(direction_salary),
             _fig_pie(edu, "学历"), _fig_pie(exp, "经验")]
        )
        chart_keywords = (
            "<p class='meta'>暂无 JD 全文数据（job_snapshot.jd_fulltext 为空），"
            "无法统计高频词。JD 正文由采集层两阶段回填。</p>"
        )

    overall = yoy["overall"]
    scope = "全部城市" if city is None else f"城市过滤：{city}"
    html = _TEMPLATE.substitute(
        scope=scope,
        current_quarter=yoy["current_quarter"] or "暂无数据",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        kpi_total=total,
        kpi_quarter_count=overall["job_count"] if overall else 0,
        kpi_avg_salary=_fmt_salary(overall["avg_salary"]) if overall else "—",
        kpi_qoq=_fmt_pct(overall["qoq"]["job_count"]) if overall else "—",
        kpi_yoy=_fmt_pct(overall["yoy"]["job_count"]) if overall else "—",
        city_rank=_city_rank_html(rank),
        chart_trend=chart_trend,
        chart_direction=chart_direction,
        chart_keywords=chart_keywords,
        chart_edu=chart_edu,
        chart_exp=chart_exp,
        direction_table=_direction_table_html(yoy["by_direction"]),
    )
    out = Path(output_path)
    out.write_text(html, encoding="utf-8")
    return str(out)


def main() -> None:
    """CLI：python -m analysis.report [db_path] [output]"""
    import sys

    db = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/recruitment.db")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    path = generate_report(db, output_path=out)
    size = Path(path).stat().st_size
    print(f"报告已生成: {path} ({size} bytes)")


if __name__ == "__main__":
    main()
