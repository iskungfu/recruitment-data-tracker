"""boss-zhipin-scraper CLI wrapper — 03-module-interfaces.md §6

boss-zhipin-scraper 是外部 CLI 依赖，不是我们的代码。
我们的代码只做：① 组装参数 ② 调 subprocess ③ 定位 JSON 输出。

真实 CLI（以 https://github.com/eatmoreduck/boss-zhipin-scraper README / 源码为准）：
    python3 scripts/boss_cdp_raw.py --keyword "后端" --city "北京" \
        --pages 3 --format json --output data/raw/xxx.json

说明：v1.1 接口文档 §6 假设的 `boss-zhipin-scraper collect --max-pages`
子命令在上游仓库并不存在——真实入口是 scripts/boss_cdp_raw.py，页数参数
为 --pages。本模块按真实 CLI 实现，函数签名与 §6 保持一致。

采集跑在本机 Chrome CDP 上（需先 `boss_cdp_raw.py --setup-chrome` 登录一次）。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.config import Settings
from core.exceptions import ScraperError, ScraperTimeoutError

log = logging.getLogger(__name__)

# 自动探测 scraper 入口的常见相对位置（当前工作目录下）
_ENTRY_CANDIDATES = (
    "boss-zhipin-scraper/scripts/boss_cdp_raw.py",
    "external/boss-zhipin-scraper/scripts/boss_cdp_raw.py",
    "vendor/boss-zhipin-scraper/scripts/boss_cdp_raw.py",
)


@dataclass(frozen=True)
class ScraperConfig:
    """单次采集的参数 (scraper CLI flags)"""

    keyword: str
    city: str                            # boss-zhipin-scraper 城市名（如"北京"）
    max_pages: int = 3                   # ≤3 页/关键词/城市（ADR-011）
    timeout: int = 300                   # 子进程超时 300 秒
    output_dir: Path = Path("data/raw")  # JSON 落盘目录
    fetch_detail: bool = False           # W2 列表页优先，JD 详情两阶段回填（ADR-012）


def _resolve_scraper_argv(settings: Settings) -> list[str]:
    """定位外部 CLI 并返回 argv 前缀。

    优先级：settings.scraper_entry > 环境变量 BOSS_SCRAPER_ENTRY
            > PATH 上的 scraper_cli 别名 > 常见相对路径自动探测。
    找不到抛 ScraperError。
    """
    entry = settings.scraper_entry or os.environ.get("BOSS_SCRAPER_ENTRY")
    if entry and Path(entry).is_file():
        return [settings.python_bin, entry]

    cli = shutil.which(settings.scraper_cli)
    if cli:
        return [cli]

    for candidate in _ENTRY_CANDIDATES:
        if Path(candidate).is_file():
            return [settings.python_bin, candidate]

    raise ScraperError(
        "未找到 boss-zhipin-scraper。请：\n"
        "  1. git clone https://github.com/eatmoreduck/boss-zhipin-scraper\n"
        "  2. pip install -r boss-zhipin-scraper/requirements.txt\n"
        "  3. 在 config/settings.yaml 的 scraper.entry 配置 scripts/boss_cdp_raw.py 路径\n"
        "     或设置环境变量 BOSS_SCRAPER_ENTRY"
    )


def _output_path(config: ScraperConfig) -> Path:
    """生成本次采集的 JSON 落盘路径（相对当前工作目录）"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = lambda s: "".join(c if c.isalnum() else "_" for c in s).strip("_")
    return config.output_dir / f"boss_jobs_{safe(config.city)}_{safe(config.keyword)}_{ts}.json"


def run_scraper(config: ScraperConfig, settings: Settings) -> Path:
    """启动 boss-zhipin-scraper CLI（subprocess），返回产出的 JSON 路径。

    失败抛 ScraperError（非零退出码 / 输出缺失或为空）；
    超时（默认 300s）抛 ScraperTimeoutError。
    """
    argv_prefix = _resolve_scraper_argv(settings)
    out_path = _output_path(config)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    argv = argv_prefix + [
        "--keyword", config.keyword,
        "--city", config.city,
        "--pages", str(config.max_pages),
        "--format", "json",
        "--output", str(out_path),
        "--cdp-port", str(settings.cdp_port),
    ]
    if not config.fetch_detail:
        argv.append("--no-detail")  # 列表页优先，JD 两阶段回填

    log.info("启动 scraper: %s", " ".join(argv))
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as e:
        raise ScraperError(f"scraper 子进程启动失败: {e}") from e

    try:
        stdout, stderr = proc.communicate(timeout=config.timeout)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        proc.wait()
        raise ScraperTimeoutError(
            f"scraper 超时（>{config.timeout}s）: {config.keyword} @ {config.city}"
        ) from e

    if proc.returncode != 0:
        tail = (stderr or stdout or "").strip()[-500:]
        raise ScraperError(
            f"scraper 非零退出码 {proc.returncode}: {config.keyword} @ {config.city}\n{tail}"
        )

    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise ScraperError(
            f"scraper 未产出有效 JSON: {out_path}\n{(stdout or '')[-500:]}"
        )
    log.info("采集完成: %s", out_path)
    return out_path


def run_scraper_batch(
    keywords: list[str],
    cities: list[str],
    settings: Settings,
    max_pages: int = 3,
) -> list[Path]:
    """多轮渐进：遍历 (keyword × city) 组合，逐次调用 run_scraper()。

    每轮之间 sleep settings.batch_delay_sec（默认 120s）让 CDP session 重建。
    单个组合失败记录日志后继续，不中断整批；返回成功的 JSON 路径列表。
    """
    results: list[Path] = []
    combos = [(kw, city) for kw in keywords for city in cities]
    for i, (kw, city) in enumerate(combos):
        config = ScraperConfig(
            keyword=kw, city=city,
            max_pages=max_pages, timeout=settings.scraper_timeout,
            output_dir=settings.raw_output_dir,
        )
        try:
            results.append(run_scraper(config, settings))
        except ScraperError as e:
            log.error("采集失败（跳过，继续下一组合）: %s", e)
        if i < len(combos) - 1:
            time.sleep(settings.batch_delay_sec)
    return results


def check_scraper_installed() -> bool:
    """环境检查：boss-zhipin-scraper 是否可用（PATH 别名 / 环境变量 / 常见相对路径）。

    任何情况下返回 bool，不抛异常。
    """
    try:
        if shutil.which("boss-zhipin-scraper"):
            return True
        entry = os.environ.get("BOSS_SCRAPER_ENTRY")
        if entry and Path(entry).is_file():
            return True
        return any(Path(c).is_file() for c in _ENTRY_CANDIDATES)
    except Exception:  # 环境检查永不抛异常
        return False
