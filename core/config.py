"""配置加载 — 03-module-interfaces.md §6 的 Settings 来源

所有路径均为对当前工作目录的相对路径（项目根目录运行）。
config/settings.yaml 提交至 Git；本地敏感信息放 config/local/（gitignore）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.exceptions import ConfigError

DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


@dataclass(frozen=True)
class Settings:
    """运行配置。

    scraper_entry 指向外部依赖 boss-zhipin-scraper 的入口脚本
    （该工具不是 PATH 上的 CLI，而是 `python3 scripts/boss_cdp_raw.py`，
    见 https://github.com/eatmoreduck/boss-zhipin-scraper README）。
    也可用环境变量 BOSS_SCRAPER_ENTRY 覆盖。
    """

    db_path: Path = Path("data/recruitment.db")
    raw_output_dir: Path = Path("data/raw")
    # 外部 CLI 依赖定位
    scraper_entry: str | None = None      # boss_cdp_raw.py 路径，None 时自动探测
    scraper_cli: str = "boss-zhipin-scraper"  # PATH 上的别名（若用户自建 wrapper）
    python_bin: str = "python3"
    # 采集约束
    max_pages: int = 3                    # ≤3 页/关键词/城市（ADR-011）
    scraper_timeout: int = 300            # 子进程超时 300 秒
    batch_delay_sec: int = 120            # 批次间延迟（多轮渐进）
    cdp_port: int = 9222


def load_settings(path: Path | str = DEFAULT_SETTINGS_PATH) -> Settings:
    """从 YAML 加载配置；文件不存在或缺字段时用默认值。YAML 语法错误抛 ConfigError。"""
    path = Path(path)
    if not path.exists():
        return Settings()
    try:
        import yaml
    except ImportError:
        return Settings()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件 YAML 语法错误 {path}: {e}") from e

    scraper = data.get("scraper") or {}
    system = data.get("system") or {}
    return Settings(
        db_path=Path(system.get("db_path", "data/recruitment.db")),
        raw_output_dir=Path(scraper.get("raw_output_dir", "data/raw")),
        scraper_entry=scraper.get("entry") or None,
        scraper_cli=scraper.get("cli_alias", "boss-zhipin-scraper"),
        python_bin=scraper.get("python_bin", "python3"),
        max_pages=int(system.get("max_pages_per_keyword_city", 3)),
        scraper_timeout=int(scraper.get("timeout_sec", 300)),
        batch_delay_sec=int(scraper.get("batch_delay_sec", 120)),
        cdp_port=int(scraper.get("cdp_port", 9222)),
    )
