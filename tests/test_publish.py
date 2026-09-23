"""发布管线测试 — data/publish/cli.py + format_check.py

数据基线（三个季度，与 tests/test_analysis.py 同风格）：
- 2025Q3（去年同期）: 2 条 — 北京 Java 25K(20-30)、上海 前端 35K(30-40)
- 2026Q2（上季度）  : 2 条 — 北京 Java 30K(25-35)、北京 前端 40K(35-45)
- 2026Q3（本季）    : 4 条 — 北京 Java 45K(30-60)、北京 Python 15K(10-20)、
                              上海 数字IC 50K(40-60)、成都 杂项 日薪(NULL)

本季方向归属（关键词长词优先、大小写不敏感）：
- Java后端工程师 / Python后端工程师 → 后端（2 条）
- 数字IC设计工程师 → IC设计（1 条）
- 杂项实习岗位 → 未归属（不计入方向聚合）
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from data.publish import format_check
from data.publish.cli import main as publish_main
from storage.schema import create_tables

JOBS = [
    # (encrypt_job_id, job_name, salary_raw, min, max, unit, city_id, edu, exp, jd, date)
    ("y1", "Java开发工程师", "20-30K", 20.0, 30.0, "month", 1, "本科", "3-5年", None, "2025-09-23"),
    ("y2", "前端工程师", "30-40K", 30.0, 40.0, "month", 2, "本科", "1-3年", None, "2025-09-23"),
    ("q1", "Java高级开发", "25-35K", 25.0, 35.0, "month", 1, "本科", "3-5年", None, "2026-06-30"),
    (
        "q2",
        "前端资深工程师",
        "35-45K",
        35.0,
        45.0,
        "month",
        1,
        "硕士",
        "5-10年",
        None,
        "2026-06-30",
    ),
    (
        "c1",
        "Java后端工程师",
        "30-60K·15薪",
        30.0,
        60.0,
        "month",
        1,
        "本科",
        "3-5年",
        "负责后端系统开发，熟悉 Java 和 MySQL，掌握 Spring 框架与分布式架构",
        "2026-09-23",
    ),
    (
        "c2",
        "Python后端工程师",
        "10-20K",
        10.0,
        20.0,
        "month",
        1,
        "本科",
        "1-3年",
        "使用 Python 进行后端开发，熟悉 MySQL 数据库与接口设计",
        "2026-09-23",
    ),
    (
        "c3",
        "数字IC设计工程师",
        "40-60K",
        40.0,
        60.0,
        "month",
        2,
        "硕士",
        "3-5年",
        "负责数字IC设计与验证，熟悉 Verilog 与芯片设计流程",
        "2026-09-23",
    ),
    (
        "c4",
        "杂项实习岗位",
        "500-550元/天",
        None,
        None,
        "day",
        5,
        None,
        "经验不限",
        "协助团队完成日常工作",
        "2026-09-23",
    ),
]

_INSERT = (
    "INSERT OR IGNORE INTO job_snapshot "
    "(job_id, job_name, salary_raw, salary_min, salary_max, year_multiplier, "
    " salary_unit, city_id, company_name, education, experience, jd_fulltext, "
    " skill_tags, platform, encrypt_job_id, snapshot_date) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _build_db(db: Path, jobs=JOBS) -> Path:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    for job in jobs:
        eid, name, raw, lo, hi, unit, city_id, edu, exp, jd, day = job
        conn.execute(
            _INSERT,
            (
                eid,
                name,
                raw,
                lo,
                hi,
                None,
                unit,
                city_id,
                "测试公司",
                edu,
                exp,
                jd,
                "[]",
                "BOSS",
                eid,
                day,
            ),
        )
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def published(tmp_path: Path) -> Path:
    """建库 → 跑发布管线 → 返回输出目录（已含 6 个 JSON）。"""
    db = _build_db(tmp_path / "pub.db")
    out = tmp_path / "v1"
    assert publish_main(["--db", str(db), "--out", str(out)]) == 0
    return out


def _load(out: Path, name: str) -> dict:
    return json.loads((out / f"{name}.json").read_text(encoding="utf-8"))


class TestPublishPipeline:
    def test_summary_schema_fields(self, published: Path):
        """summary.json 必填字段存在且类型正确（架构 §3.2）。"""
        s = _load(published, "summary")
        kpi = s["kpi"]
        assert kpi["total_jobs"] == 4  # 本季 4 条
        assert isinstance(kpi["total_jobs"], int)
        assert kpi["avg_salary"]["unit"] == "K/月"
        assert kpi["cities_covered"] == 3  # 北京 / 上海 / 成都
        assert kpi["directions_covered"] == 2  # 后端 / IC设计
        assert kpi["yoy_job_growth"] == pytest.approx(1.0)  # 4/2-1
        assert kpi["qoq_salary_change"] is not None
        assert s["top_direction_by_salary"] == "IC设计"  # 50K > 后端 30K
        assert s["latest_snapshot_date"] == "2026-09-23"

    def test_salary_json_matches_sqlite(self, published: Path, tmp_path: Path):
        """salary JSON 口径与 SQLite 直算一致：本季月薪岗 avg(min)/avg(max)。"""
        db = tmp_path / "pub.db"
        conn = sqlite3.connect(str(db))
        lo, hi, _n = conn.execute(
            "SELECT AVG(salary_min), AVG(salary_max), COUNT(*) FROM job_snapshot "
            "WHERE salary_unit = 'month' AND salary_min IS NOT NULL "
            "AND salary_max IS NOT NULL AND snapshot_date = '2026-09-23'"
        ).fetchone()
        conn.close()
        s = _load(published, "summary")
        # JSON 输出按 2 位小数取舍（发布层既定口径），容差 0.01
        assert s["kpi"]["avg_salary"]["min"] == pytest.approx(lo, abs=0.01)
        assert s["kpi"]["avg_salary"]["max"] == pytest.approx(hi, abs=0.01)
        # salary_trends 本季北京：c1(30-60) + c2(10-20) → min 20 / max 40 / 2 条
        t = _load(published, "salary_trends")
        bj = t["by_city"]["北京"]["2026Q3"]
        assert bj["avg_salary_min"] == pytest.approx(20.0)
        assert bj["avg_salary_max"] == pytest.approx(40.0)
        assert bj["job_count"] == 2
        # 方向维度：后端 2 条，qoq 岗位数 2/1-1=+100%（上季 q1 Java高级开发→后端）
        back = t["by_direction"]["后端"]["2026Q3"]
        assert back["job_count"] == 2
        assert back["qoq_job_count"] == pytest.approx(1.0)
        assert back["yoy_job_count"] == pytest.approx(1.0)  # 去年 y1→后端
        # 历史季度同比/环比字段为 null（compute_yoy_qoq 只对当前季度给值）
        assert t["by_direction"]["后端"]["2026Q2"]["qoq_job_count"] is None

    def test_manifest_matches_files_and_dynamic_filters(self, published: Path, tmp_path: Path):
        """manifest.datasets 与实际文件一一对应；filters 从库动态读取。"""
        m = _load(published, "manifest")
        on_disk = {p.name for p in published.glob("*.json")}
        assert on_disk == set(m["datasets"].values()) | {"manifest.json"}
        assert m["version"] == "2026Q3"
        assert m["data_snapshot_date"] == "2026-09-23"
        assert m["filters"]["quarters"] == ["2025Q3", "2026Q2", "2026Q3"]
        assert m["filters"]["cities"] == ["北京", "上海", "深圳", "杭州", "成都"]
        # directions 动态读 keywords 表：新增一个方向后重新发布必须出现
        assert "材料" in m["filters"]["directions"]
        db = tmp_path / "pub.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO keywords (direction, keyword, platform, is_active) "
            "VALUES ('新方向', '新方向岗位', 'BOSS', 1)"
        )
        conn.commit()
        conn.close()
        assert publish_main(["--db", str(db), "--out", str(published)]) == 0
        m2 = _load(published, "manifest")
        assert "新方向" in m2["filters"]["directions"]

    def test_empty_db_degrades(self, tmp_path: Path):
        """空库（只建表无岗位）降级：仍输出 6 个合法 JSON，format_check 全过。"""
        db = _build_db(tmp_path / "empty.db", jobs=[])
        out = tmp_path / "v1empty"
        assert publish_main(["--db", str(db), "--out", str(out)]) == 0
        s = _load(out, "summary")
        assert s["kpi"]["total_jobs"] == 0
        assert s["kpi"]["avg_salary"]["min"] is None
        assert s["kpi"]["yoy_job_growth"] is None
        assert s["latest_snapshot_date"] is None
        m = _load(out, "manifest")
        assert m["version"] == "empty"
        assert m["filters"]["quarters"] == []
        assert m["filters"]["directions"]  # 种子关键词仍在，filters 不为空
        t = _load(out, "salary_trends")
        assert t["by_direction"] == {}
        assert t["chart_specs"]["direction_comparison"]["data"] is not None
        assert format_check.check_all(out) == []

    def test_format_check_detects_missing_field(self, published: Path):
        """format_check 负例：删必填字段 / 删文件必须报错。"""
        spath = published / "summary.json"
        summary = json.loads(spath.read_text(encoding="utf-8"))
        del summary["kpi"]["total_jobs"]
        spath.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        errors = format_check.check_all(published)
        assert any("total_jobs" in e for e in errors)
        # 删掉一个数据集文件 → 报文件不存在
        (published / "data_status.json").unlink()
        errors = format_check.check_all(published)
        assert any("data_status.json" in e and "不存在" in e for e in errors)

    def test_job_ranking_order_share_yoy(self, published: Path):
        """排行按岗位数降序、share 口径为本季已归属总量、yoy 与 analysis 一致。"""
        r = _load(published, "job_ranking")
        assert [x["direction"] for x in r["rankings"]] == ["后端", "IC设计"]
        assert [x["rank"] for x in r["rankings"]] == [1, 2]
        assert r["rankings"][0]["job_count"] == 2
        assert r["rankings"][0]["share"] == pytest.approx(2 / 3, abs=1e-4)
        assert r["rankings"][0]["yoy_change"] == pytest.approx(1.0)
        assert r["rankings"][0]["top_cities"] == ["北京"]
        # 技能 Top 20：fixture 里 4 条有 JD 文本，高频词应非空且按频次降序
        skills = r["top_skills_across_all"]
        assert skills
        counts = [s["count"] for s in skills]
        assert counts == sorted(counts, reverse=True)

    def test_chart_specs_plotly_shape(self, published: Path):
        """chart_specs 非空，每个 spec 为 Plotly {data, layout} 结构。"""
        expectations = {
            "salary_trends": ("direction_comparison", "city_comparison"),
            "job_ranking": ("ranking_bar", "skills_wordcloud"),
            "edu_exp_distribution": ("edu_pie", "exp_bar_by_dir"),
        }
        for name, keys in expectations.items():
            obj = _load(published, name)
            specs = obj["chart_specs"]
            assert specs, f"{name}.chart_specs 为空"
            for key in keys:
                spec = specs[key]
                assert isinstance(spec["data"], list), f"{name}.{key}.data"
                assert isinstance(spec["layout"], dict), f"{name}.{key}.layout"
                assert isinstance(spec["type"], str)
        # 本季有数据：方向对比图应含两条 bar trace（均值下限/上限）
        t = _load(published, "salary_trends")
        traces = t["chart_specs"]["direction_comparison"]["data"]
        assert len(traces) == 2
        assert traces[0]["type"] == "bar"

    def test_data_status_quality_rates(self, published: Path):
        """采集质量口径：薪资解析率 7/8、JD 率 4/8、去重率 0、快照按日期倒序。"""
        d = _load(published, "data_status")
        assert d["quality"]["salary_parse_rate"] == pytest.approx(7 / 8)
        assert d["quality"]["jd_fulltext_rate"] == pytest.approx(4 / 8)  # c1-c4 均有 JD 文本
        assert d["quality"]["duplicate_rate"] == pytest.approx(0.0)
        assert [s["date"] for s in d["snapshots"]] == [
            "2026-09-23",
            "2026-06-30",
            "2025-09-23",
        ]
        assert d["snapshots"][0]["total_jobs"] == 4
        assert d["snapshots"][0]["cities"] == {"北京": 2, "上海": 1, "成都": 1}
        assert d["collection_log"] == []  # snapshots 表无采集日志时为空数组
