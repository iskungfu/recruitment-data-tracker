"""scraper CLI wrapper 测试 — §6：subprocess 调用、超时、异常路径

用仿真 CLI（tests/fixtures/fake_boss_cdp_raw.py）复刻真实
boss-zhipin-scraper 的入参/出参契约，不依赖 Chrome / 网络。
"""

from __future__ import annotations

import json

import pytest

from collectors.boss_scraper import (
    ScraperConfig,
    check_scraper_installed,
    run_scraper,
    run_scraper_batch,
)
from core.exceptions import ScraperError, ScraperTimeoutError


class TestRunScraper:
    def test_success_returns_json_path(self, settings, tmp_path):
        config = ScraperConfig(
            keyword="后端", city="北京", max_pages=3, timeout=5,
            output_dir=tmp_path / "raw",
        )
        out = run_scraper(config, settings)
        assert out.is_file()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["keyword"] == "后端"
        assert payload["city"] == "北京"
        assert payload["total"] == 3
        assert len(payload["jobs"]) == 3

    def test_timeout_raises(self, settings, tmp_path):
        config = ScraperConfig(
            keyword="SLOW", city="北京", timeout=1, output_dir=tmp_path / "raw",
        )
        with pytest.raises(ScraperTimeoutError):
            run_scraper(config, settings)

    def test_nonzero_exit_raises(self, settings, tmp_path):
        config = ScraperConfig(
            keyword="FAIL", city="北京", timeout=5, output_dir=tmp_path / "raw",
        )
        with pytest.raises(ScraperError):
            run_scraper(config, settings)

    def test_empty_output_raises(self, settings, tmp_path):
        config = ScraperConfig(
            keyword="EMPTY", city="北京", timeout=5, output_dir=tmp_path / "raw",
        )
        with pytest.raises(ScraperError):
            run_scraper(config, settings)

    def test_missing_entry_raises(self, tmp_path):
        from core.config import Settings

        s = Settings(scraper_entry="/nonexistent/boss_cdp_raw.py", scraper_cli="definitely-not-exists-cli")
        # 确保自动探测也不会命中（相对路径在 tmp cwd 下不存在）
        config = ScraperConfig(keyword="后端", city="北京", output_dir=tmp_path / "raw")
        with pytest.raises(ScraperError, match="未找到"):
            run_scraper(config, s)


class TestRunScraperBatch:
    def test_batch_collects_successes(self, settings, tmp_path):
        settings = settings.__class__(**{**settings.__dict__, "raw_output_dir": tmp_path / "raw"})
        paths = run_scraper_batch(["后端"], ["北京", "上海"], settings, max_pages=3)
        assert len(paths) == 2
        assert all(p.is_file() for p in paths)

    def test_batch_skips_failures(self, settings, tmp_path):
        settings = settings.__class__(**{**settings.__dict__, "raw_output_dir": tmp_path / "raw"})
        paths = run_scraper_batch(["FAIL", "后端"], ["北京"], settings, max_pages=3)
        assert len(paths) == 1  # FAIL 记录日志后继续


class TestCheckScraperInstalled:
    def test_returns_bool(self):
        result = check_scraper_installed()
        assert isinstance(result, bool)

    def test_true_when_entry_env_set(self, monkeypatch):
        from tests.conftest import FAKE_SCRAPER_ENTRY

        monkeypatch.setenv("BOSS_SCRAPER_ENTRY", str(FAKE_SCRAPER_ENTRY))
        assert check_scraper_installed() is True
