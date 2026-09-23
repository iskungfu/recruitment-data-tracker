"""职友集采集器测试 — DOM 解析（真实 HTML 样本）/ URL 反爬检测 / wrapper 契约

DOM 样本：tests/fixtures/jobui_list_sample.html，为 2026-09-23 预研时
www.jobui.com/jobs?cityKw=北京&jobKw=后端 的真实服务端渲染 HTML 原样切片
（20 条有效岗位卡 + 3 条无字段占位卡）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from collectors.jobui_scraper import (
    JobuiCaptchaError,
    JobuiLoginRequiredError,
    JobuiScraperConfig,
    build_search_url,
    check_final_url,
    check_jobui_scraper_installed,
    parse_list_html,
    run_scraper,
    run_scraper_batch,
)
from core.exceptions import ScraperError, ScraperTimeoutError

FIXTURES = Path(__file__).parent / "fixtures"
REAL_LIST_HTML = (FIXTURES / "jobui_list_sample.html").read_text(encoding="utf-8")
FAKE_ENTRY = FIXTURES / "fake_jobui_cdp_raw.py"


@pytest.fixture()
def jobui_settings(tmp_path):
    from core.config import Settings

    return Settings(
        db_path=tmp_path / "test.db",
        raw_output_dir=tmp_path / "raw",
        python_bin="python3",
        scraper_timeout=5,
        batch_delay_sec=0,
    )


@pytest.fixture()
def jobui_env(monkeypatch):
    monkeypatch.setenv("JOBUI_SCRAPER_ENTRY", str(FAKE_ENTRY))


class TestParseListHtml:
    """DOM 解析 —— 用真实捕获的 HTML 样本"""

    def test_real_sample_record_count(self):
        """20 条有效卡 + 3 条无 job-name/pay 的占位卡 → 恰好解析出 20 条"""
        records = parse_list_html(REAL_LIST_HTML)
        assert len(records) == 20

    def test_real_sample_first_record_fields(self):
        records = parse_list_html(REAL_LIST_HTML)
        r = records[0]
        assert r["job_id"] == "189827721"
        assert r["encrypt_job_id"] == "jobui_189827721"
        assert r["title"] == "后端开发"          # <strong>后端</strong>开发 拼接
        assert r["salary"] == "8-15k"
        assert r["experience"] == "3-5年"
        assert r["education"] == "本科以上"       # 原文含"以上"，此处不归一化
        assert r["company_name"] == "中科软科技股份有限公司"
        assert r["detail_url"] == "https://www.jobui.com/job/189827721/"
        assert r["company_url"] == "https://www.jobui.com/company/19563/jobs/"
        assert r["add_date"] == "1天前"

    def test_real_sample_salary_variants(self):
        """预研实测的 4 种薪资格式全部保留原文，交由 importer 换算"""
        salaries = {r["salary"] for r in parse_list_html(REAL_LIST_HTML)}
        for expected in ("8-15k", "35000-50000元", "40000-70000", "1.5-1.6万"):
            assert expected in salaries

    def test_every_record_has_required_fields(self):
        for r in parse_list_html(REAL_LIST_HTML):
            assert r["job_id"].isdigit()
            assert r["title"]
            assert r["salary"]
            assert r["company_name"]
            assert r["detail_url"].startswith("https://www.jobui.com/job/")


class TestAntiCrawlUrlDetection:
    """登录墙 / 验证码 URL 检测（recon 实测的两种拦截形态）"""

    def test_login_wall_raises(self):
        with pytest.raises(JobuiLoginRequiredError):
            check_final_url("https://www.jobui.com/people/login/?redirect=/jobs")

    def test_captcha_raises(self):
        with pytest.raises(JobuiCaptchaError):
            check_final_url("https://www.jobui.com/tips/valid.php?act=init")

    def test_normal_url_passes(self):
        url = "https://www.jobui.com/jobs?cityKw=%E5%8C%97%E4%BA%AC&jobKw=%E5%90%8E%E7%AB%AF"
        assert check_final_url(url) == url


class TestBuildSearchUrl:
    def test_url_encodes_chinese_params(self):
        url = build_search_url("后端", "北京")
        assert url == "https://www.jobui.com/jobs?cityKw=%E5%8C%97%E4%BA%AC&jobKw=%E5%90%8E%E7%AB%AF"


class TestRunScraper:
    """wrapper 契约 —— 用仿真 CLI（fake_jobui_cdp_raw.py），不依赖 Chrome/网络"""

    def test_success_returns_json_path(self, jobui_settings, jobui_env, tmp_path):
        config = JobuiScraperConfig(keyword="后端", city="北京", output_dir=tmp_path / "raw")
        out = run_scraper(config, jobui_settings)
        assert out.is_file()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["platform"] == "JOBUI"
        assert payload["city"] == "北京"
        assert payload["total"] == 3
        assert len(payload["jobs"]) == 3
        assert payload["jobs"][0]["job_id"] == "900000001"

    def test_timeout_raises(self, jobui_settings, jobui_env, tmp_path):
        config = JobuiScraperConfig(keyword="SLOW", city="北京", timeout=1, output_dir=tmp_path / "raw")
        with pytest.raises(ScraperTimeoutError):
            run_scraper(config, jobui_settings)

    def test_nonzero_exit_raises(self, jobui_settings, jobui_env, tmp_path):
        config = JobuiScraperConfig(keyword="FAIL", city="北京", output_dir=tmp_path / "raw")
        with pytest.raises(ScraperError):
            run_scraper(config, jobui_settings)

    def test_empty_output_raises(self, jobui_settings, jobui_env, tmp_path):
        config = JobuiScraperConfig(keyword="EMPTY", city="北京", output_dir=tmp_path / "raw")
        with pytest.raises(ScraperError):
            run_scraper(config, jobui_settings)

    def test_login_wall_exit_code_raises(self, jobui_settings, jobui_env, tmp_path):
        """脚本退出码 2 → JobuiLoginRequiredError（wrapper 负责映射）"""
        config = JobuiScraperConfig(keyword="LOGIN", city="北京", output_dir=tmp_path / "raw")
        with pytest.raises(JobuiLoginRequiredError):
            run_scraper(config, jobui_settings)

    def test_captcha_exit_code_raises(self, jobui_settings, jobui_env, tmp_path):
        """脚本退出码 3 → JobuiCaptchaError"""
        config = JobuiScraperConfig(keyword="CAPTCHA", city="北京", output_dir=tmp_path / "raw")
        with pytest.raises(JobuiCaptchaError):
            run_scraper(config, jobui_settings)

    def test_missing_entry_raises(self, tmp_path, monkeypatch):
        from core.config import Settings

        monkeypatch.delenv("JOBUI_SCRAPER_ENTRY", raising=False)
        s = Settings(python_bin="python3")
        # 在空 cwd 下解析不到任何入口
        monkeypatch.chdir(tmp_path)
        config = JobuiScraperConfig(keyword="后端", city="北京", output_dir=tmp_path / "raw")
        with pytest.raises(ScraperError, match="未找到"):
            run_scraper(config, s)


class TestRunScraperBatch:
    def test_batch_collects_and_skips_failures(self, jobui_settings, jobui_env):
        """FAIL/LOGIN 组合失败跳过，成功组合继续；batch_delay_sec=0 不等待"""
        paths = run_scraper_batch(["FAIL", "LOGIN", "后端"], ["北京"], jobui_settings)
        assert len(paths) == 1
        assert paths[0].is_file()

    def test_batch_multi_city(self, jobui_settings, jobui_env):
        paths = run_scraper_batch(["后端"], ["北京", "上海"], jobui_settings)
        assert len(paths) == 2
        assert all(p.is_file() for p in paths)


class TestCheckInstalled:
    def test_returns_bool(self):
        assert isinstance(check_jobui_scraper_installed(), bool)

    def test_true_when_entry_env_set(self, monkeypatch):
        monkeypatch.setenv("JOBUI_SCRAPER_ENTRY", str(FAKE_ENTRY))
        assert check_jobui_scraper_installed() is True
