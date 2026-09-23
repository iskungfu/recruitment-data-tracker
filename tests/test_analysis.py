"""Week 3 分析模块测试 — 同比环比 / 词频 / 报告生成

数据基线（三个季度，月薪中点）：
- 2025Q3（去年同期）: 2 条 — 北京 Java 25K(20-30)、上海 前端 35K(30-40)
- 2026Q2（上季度）  : 2 条 — 北京 Java 30K(25-35)、北京 前端 40K(35-45)
- 2026Q3（本季）    : 4 条 — 北京 Java 45K(30-60)、北京 Python 15K(10-20)、
                              上海 数字IC 50K(40-60)、成都 未知岗位 日薪(NULL)
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from analysis.keywords import analyze_keywords, tokenize
from analysis.report import generate_report
from analysis.stats import compute_yoy_qoq
from storage.schema import create_tables

JOBS = [
    # (encrypt_job_id, job_name, salary_raw, min, max, unit, city_id, edu, exp, jd, date)
    ("y1", "Java开发工程师", "20-30K", 20.0, 30.0, "month", 1, "本科", "3-5年", None, "2025-09-23"),
    ("y2", "前端工程师", "30-40K", 30.0, 40.0, "month", 2, "本科", "1-3年", None, "2025-09-23"),
    ("q1", "Java高级开发", "25-35K", 25.0, 35.0, "month", 1, "本科", "3-5年", None, "2026-06-30"),
    ("q2", "前端资深工程师", "35-45K", 35.0, 45.0, "month", 1, "硕士", "5-10年", None, "2026-06-30"),
    ("c1", "Java后端工程师", "30-60K·15薪", 30.0, 60.0, "month", 1, "本科", "3-5年",
     "负责后端系统开发，熟悉 Java 和 MySQL，掌握 Spring 框架与分布式架构", "2026-09-23"),
    ("c2", "Python后端工程师", "10-20K", 10.0, 20.0, "month", 1, "本科", "1-3年",
     "使用 Python 进行后端开发，熟悉 MySQL 数据库与接口设计", "2026-09-23"),
    ("c3", "数字IC设计工程师", "40-60K", 40.0, 60.0, "month", 2, "硕士", "3-5年",
     "负责数字IC设计与验证，熟悉 Verilog 与芯片设计流程", "2026-09-23"),
    ("c4", "杂项实习岗位", "500-550元/天", None, None, "day", 5, None, "经验不限",
     "协助团队完成日常工作", "2026-09-23"),
]

_INSERT = (
    "INSERT OR IGNORE INTO job_snapshot "
    "(job_id, job_name, salary_raw, salary_min, salary_max, year_multiplier, "
    " salary_unit, city_id, company_name, education, experience, jd_fulltext, "
    " skill_tags, platform, encrypt_job_id, snapshot_date) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


@pytest.fixture()
def analysis_db(tmp_path: Path) -> Path:
    """建库 + 插入 JOBS 基线数据，返回 db 路径。"""
    db = tmp_path / "analysis.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    for job in JOBS:
        eid, name, raw, lo, hi, unit, city_id, edu, exp, jd, day = job
        conn.execute(
            _INSERT,
            (eid, name, raw, lo, hi, None, unit, city_id, "测试公司",
             edu, exp, jd, "[]", "BOSS", eid, day),
        )
    conn.commit()
    conn.close()
    return db


class TestYoyQoq:
    def test_overall_percentages(self, analysis_db):
        r = compute_yoy_qoq(analysis_db)["overall"]
        assert r["current_quarter"] == "2026Q3"
        assert r["job_count"] == 4
        # qoq：岗位数 4/2-1 = +100%；薪资 本季月薪均值 (45+15+50)/3 ≈ 36.67
        #      vs 上季 (30+40)/2 = 35 → ≈ +4.76%
        assert r["qoq"]["job_count"] == pytest.approx(1.0)
        assert r["qoq"]["avg_salary"] == pytest.approx((45 + 15 + 50) / 3 / 35 - 1)
        # yoy：岗位数 4/2-1 = +100%；薪资 vs 去年同期 (25+35)/2 = 30
        assert r["yoy"]["job_count"] == pytest.approx(1.0)
        assert r["yoy"]["avg_salary"] == pytest.approx((45 + 15 + 50) / 3 / 30 - 1)

    def test_day_salary_excluded_from_avg(self, analysis_db):
        """日薪岗（c4）计入岗位数但不参与薪资均值"""
        r = compute_yoy_qoq(analysis_db)["overall"]
        assert r["job_count"] == 4                      # 含日薪岗
        assert r["avg_salary"] == pytest.approx((45 + 15 + 50) / 3)  # 不含

    def test_by_city_and_city_filter(self, analysis_db):
        r = compute_yoy_qoq(analysis_db)
        assert set(r["by_city"]) == {"北京", "上海", "成都"}
        bj = r["by_city"]["北京"]
        assert bj["job_count"] == 2
        assert bj["qoq"]["job_count"] == pytest.approx(0.0)   # 2 vs 2
        # 城市过滤（str 名字 / int id 同口径）
        filtered = compute_yoy_qoq(analysis_db, city="北京")
        assert filtered["overall"]["job_count"] == 2
        assert set(filtered["by_city"]) == {"北京"}
        assert filtered["overall"]["job_count"] == \
            compute_yoy_qoq(analysis_db, city=1)["overall"]["job_count"]

    def test_by_direction(self, analysis_db):
        r = compute_yoy_qoq(analysis_db)["by_direction"]
        assert r["后端"]["job_count"] == 2              # Java + Python 岗
        assert r["IC设计"]["job_count"] == 1
        assert r["后端"]["yoy"]["job_count"] == pytest.approx(1.0)  # 2 vs 去年 1

    def test_yoy_qoq_null_denominator(self, tmp_path):
        """只有本季数据 → qoq/yoy 全 NULL；空库 → overall None"""
        db = tmp_path / "one_quarter.db"
        conn = sqlite3.connect(str(db))
        create_tables(conn)
        conn.execute(
            _INSERT,
            ("only1", "Java开发", "10-20K", 10.0, 20.0, None, "month", 1,
             "公司", "本科", "1-3年", None, "[]", "BOSS", "only1", "2026-09-23"),
        )
        conn.commit()
        conn.close()
        r = compute_yoy_qoq(db)["overall"]
        assert r["qoq"] == {"job_count": None, "avg_salary": None}
        assert r["yoy"] == {"job_count": None, "avg_salary": None}

        empty = tmp_path / "empty.db"
        conn = sqlite3.connect(str(empty))
        create_tables(conn)
        conn.close()
        r = compute_yoy_qoq(empty)
        assert r["current_quarter"] is None and r["overall"] is None


class TestKeywords:
    def test_top_n_stable(self, analysis_db):
        result = analyze_keywords(analysis_db, top_n=50)
        assert result, "应非空"
        counts = dict(result)
        # "MySQL" 在两条 JD 中各出现一次 → 频次 2
        assert counts["MySQL"] == 2
        assert counts["Java"] == 1
        # 降序 + 同频次字典序，结果确定
        assert result == sorted(result, key=lambda kv: (-kv[1], kv[0]))

    def test_top_n_limit(self, analysis_db):
        assert len(analyze_keywords(analysis_db, top_n=3)) == 3

    def test_single_char_and_stopwords_filtered(self):
        tokens = tokenize("的 了 在 是 和 与 及 或 等 我 你 做 Java 开发")
        assert "Java" in tokens
        for w in ("的", "了", "在", "是", "和", "与", "及", "或", "等", "我", "你", "做"):
            assert w not in tokens

    def test_punctuation_and_digits_filtered(self):
        tokens = tokenize("薪资 10-20K，13薪！（急招）")
        assert all(any(ch.isalpha() or "一" <= ch <= "鿿" for ch in t) for t in tokens)
        assert "10" not in tokens and "20" not in tokens


class TestReport:
    def test_pie_values_are_counts(self):
        """回归锁：饼图 values 必须是频次列表（dict.values()），不是键列表"""
        from analysis.report import _fig_pie

        dist = {"本科": 56, "大专": 4}
        trace = _fig_pie(dist, "学历").data[0]
        assert list(trace.labels) == ["本科", "大专"]
        assert list(trace.values) == [56, 4]

    def test_report_generates(self, analysis_db, tmp_path):
        out = generate_report(analysis_db, output_path=tmp_path / "report.html")
        p = Path(out)
        assert p.is_file()
        assert p.stat().st_size > 1024
        html = p.read_text(encoding="utf-8")
        assert "2026Q3" in html
        assert "招聘数据季度报告" in html

    def test_report_cli_entry(self, analysis_db, tmp_path):
        """python -m analysis.report 能产出 report.html（验收标准 2）"""
        import subprocess
        import sys

        out = tmp_path / "cli_report.html"
        r = subprocess.run(
            [sys.executable, "-m", "analysis.report", str(analysis_db), str(out)],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, r.stderr
        assert out.is_file() and out.stat().st_size > 1024

    def test_report_empty_db(self, tmp_path):
        """空库也能产出报告（占位文案，不抛异常）"""
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        create_tables(conn)
        conn.close()
        out = generate_report(db, output_path=tmp_path / "empty.html")
        assert Path(out).stat().st_size > 1024



# ================================================================
# Week 4 步骤三：P2 平台拆分 / total_unique_jobs / --compare 报告 / P3-4
# ================================================================

#: 双平台探针数据（本季 2026-09-23，全在北京，月薪中点）：
#: b1 与 j1 为同一岗位（同名+同公司+同城）在两平台各采一条 → 跨平台双计
_MIXED = [
    # (eid, job_name, raw, lo, hi, unit, city_id, company, platform)
    ("b1", "Java后端工程师", "30-60K", 30.0, 60.0, "month", 1, "测试公司", "BOSS"),
    ("j1", "Java后端工程师", "25-35K", 25.0, 35.0, "month", 1, "测试公司", "JOBUI"),
    ("b2", "Python后端工程师", "10-20K", 10.0, 20.0, "month", 1, "另一公司", "BOSS"),
]


@pytest.fixture()
def mixed_db(tmp_path: Path) -> Path:
    """BOSS + JOBUI 混合库（本季 3 条，其中 1 条跨平台重复）"""
    db = tmp_path / "mixed.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    for eid, name, raw, lo, hi, unit, city_id, company, platform in _MIXED:
        conn.execute(
            _INSERT,
            (eid, name, raw, lo, hi, None, unit, city_id, company,
             "本科", "3-5年", None, "[]", platform, eid, "2026-09-23"),
        )
    conn.commit()
    conn.close()
    return db


class TestPlatformSplit:
    """P2：by_platform 子结构 + total_unique_jobs（sha1 归一哈希，报告层口径）"""

    def test_overall_by_platform_and_unique(self, mixed_db):
        r = compute_yoy_qoq(mixed_db)["overall"]
        assert r["job_count"] == 3
        assert r["avg_salary"] == pytest.approx(30.0)       # (45+30+15)/3
        assert r["by_platform"] == {
            "boss": {"job_count": 2, "avg_salary": pytest.approx(30.0)},   # (45+15)/2
            "jobui": {"job_count": 1, "avg_salary": pytest.approx(30.0)},   # 30
        }
        # b1 与 j1 同名+同公司+同城 → 跨平台只算 1 个唯一岗位
        assert r["total_unique_jobs"] == 2

    def test_by_city_by_direction_by_platform(self, mixed_db):
        r = compute_yoy_qoq(mixed_db)
        bj = r["by_city"]["北京"]
        assert bj["by_platform"]["boss"]["job_count"] == 2
        assert bj["by_platform"]["jobui"]["job_count"] == 1
        backend = r["by_direction"]["后端"]
        assert backend["by_platform"]["boss"]["job_count"] == 2
        assert backend["by_platform"]["jobui"]["job_count"] == 1

    def test_unique_jobs_matches_sha1_spec(self, mixed_db):
        """去重口径锁定：sha1(f"{job_name}|{company_name}|{city_id}")，可复算"""
        import hashlib
        expect = len({
            hashlib.sha1(e.encode()).hexdigest()
            for e in ("Java后端工程师|测试公司|1", "Python后端工程师|另一公司|1")
        })
        assert compute_yoy_qoq(mixed_db)["overall"]["total_unique_jobs"] == expect

    def test_pure_boss_db_by_platform(self, analysis_db):
        """纯 BOSS 库：by_platform 只含 boss；唯一数 = 本季岗位数（无跨平台重复）"""
        r = compute_yoy_qoq(analysis_db)
        assert set(r["overall"]["by_platform"]) == {"boss"}
        assert r["overall"]["total_unique_jobs"] == r["overall"]["job_count"]

    def test_null_city_bucket_is_unknown_city(self, tmp_path):
        """P3-4 回归：city_id NULL 的岗位归入「未知城市」，不再产出 city_None 字面桶"""
        db = tmp_path / "nullcity.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        conn.execute(
            _INSERT,
            ("n1", "神秘岗位", "10-20K", 10.0, 20.0, None, "month",
             None, "公司", "本科", "1-3年", None, "[]", "JOBUI",
             "n1", "2026-09-23"),
        )
        conn.commit()
        conn.close()
        r = compute_yoy_qoq(db)
        assert "city_None" not in r["by_city"]
        assert r["by_city"]["未知城市"]["job_count"] == 1
        assert r["by_city"]["未知城市"]["by_platform"] == {
            "jobui": {"job_count": 1, "avg_salary": pytest.approx(15.0)}
        }


class TestCompareReport:
    """--compare 双平台对比报告 + 普通模式 JOBUI 提示行"""

    def test_compare_kpis_and_platform_trend(self, mixed_db, tmp_path):
        out = generate_report(mixed_db, output_path=tmp_path / "cmp.html", compare=True)
        html = Path(out).read_text(encoding="utf-8")
        # KPI：双平台独立数据 + 唯一岗位数
        assert "BOSS 直聘（本季）</div><div class='value'>2 条</div>" in html
        assert "职友集 JOBUI（本季）</div><div class='value'>1 条</div>" in html
        assert "跨平台唯一岗位数（本季）</div><div class='value'>2</div>" in html
        # 趋势图区切换为双平台叠放标题（plotly trace 名做了 unicode 转义，
        # 图层结构在 test_fig_trend_compare_traces 里对 figure 对象断言）
        assert "薪资趋势（分城市 × 平台：BOSS 实线、JOBUI 虚线" in html
        assert "双平台对比模式" in html
        # 普通模式三卡口径不在对比报告里
        assert "总岗位数（全部季度）" not in html

    def test_fig_trend_compare_traces(self, mixed_db):
        """对比模式趋势图：每 (城市×平台) 一条线，BOSS 实线 / JOBUI 虚线"""
        from analysis.report import (
            _connect,
            _fig_trend_compare,
            _quarterly_salary_by_platform,
        )

        conn = _connect(mixed_db)
        try:
            series = _quarterly_salary_by_platform(conn, None)
        finally:
            conn.close()
        assert set(series) == {("北京", "BOSS"), ("北京", "JOBUI")}
        fig = _fig_trend_compare(series)
        assert {t.name for t in fig.data} == {"北京·BOSS", "北京·JOBUI"}
        dash = {t.name: t.line.dash for t in fig.data}
        assert dash["北京·BOSS"] == "solid"
        assert dash["北京·JOBUI"] == "dash"

    def test_compare_pure_boss_db_zero_jobui(self, analysis_db, tmp_path):
        """纯 BOSS 库出对比报告：JOBUI 卡按 0 条 / — 兜底，不报错"""
        out = generate_report(analysis_db, output_path=tmp_path / "cmp.html", compare=True)
        html = Path(out).read_text(encoding="utf-8")
        assert (
            "职友集 JOBUI（本季）</div><div class='value'>0 条</div>"
            "<div class='sub'>均值月薪 —</div>" in html
        )
        assert "跨平台唯一岗位数（本季）</div><div class='value'>4</div>" in html

    def test_normal_mode_keeps_week3_behavior_with_jobui_note(self, mixed_db, tmp_path):
        out = generate_report(mixed_db, output_path=tmp_path / "n.html")
        html = Path(out).read_text(encoding="utf-8")
        assert "含 1 个 JOBUI 聚合条目，请参考 --compare 模式跨平台对比" in html
        assert "总岗位数（全部季度）" in html            # 三卡口径不变
        assert "跨平台唯一岗位数" not in html

    def test_normal_mode_pure_boss_no_note(self, analysis_db, tmp_path):
        out = generate_report(analysis_db, output_path=tmp_path / "n2.html")
        html = Path(out).read_text(encoding="utf-8")
        assert "JOBUI 聚合条目" not in html

    def test_report_cli_compare_flag(self, mixed_db, tmp_path):
        """python -m analysis.report --compare <db> <out> 产出双平台对比报告"""
        import subprocess
        import sys

        out = tmp_path / "cli_cmp.html"
        r = subprocess.run(
            [sys.executable, "-m", "analysis.report", "--compare", str(mixed_db), str(out)],
            capture_output=True, text=True, timeout=180,
        )
        assert r.returncode == 0, r.stderr
        assert out.is_file() and out.stat().st_size > 1024
        html = out.read_text(encoding="utf-8")
        assert "跨平台唯一岗位数（本季）" in html


    def test_missing_db_no_side_effect(self, tmp_path):
        """P2 修复：DB 不存在 → FileNotFoundError，且不静默创建空文件

        三个入口（compute_yoy_qoq / analyze_keywords / generate_report）
        统一校验，任何一个都不应留下空 db 文件副作用。
        """
        missing = tmp_path / "no_such_dir" / "missing.db"
        with pytest.raises(FileNotFoundError):
            compute_yoy_qoq(missing)
        assert not missing.exists()

        with pytest.raises(FileNotFoundError):
            analyze_keywords(missing)
        assert not missing.exists()

        with pytest.raises(FileNotFoundError):
            generate_report(missing, output_path=tmp_path / "x.html")
        assert not missing.exists()
        assert not (tmp_path / "x.html").exists()
