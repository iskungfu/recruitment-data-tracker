"""jobui.com（职友集）CDP 采集 wrapper — Week 4 步骤二

对齐 collectors/boss_scraper.py 的三函数契约：
  check_jobui_scraper_installed() / run_scraper() / run_scraper_batch()

与 BOSS 的差异：BOSS 复用外部 boss-zhipin-scraper（eatmoreduck，ADR-015）；
职友集无现成外部 CLI，采集脚本为我们自己的 scripts/jobui_cdp_raw.py
（CDP 被动优先：跑在本机 Chrome 上，经 connect_over_cdp 复用登录态/指纹）。

预研结论（2026-09-23 recon 实测，见任务评论）：
  - 公开搜索入口：GET https://www.jobui.com/jobs?cityKw=<城市>&jobKw=<关键词>
    但直接访问（无 Referer）会 302 → /people/login/ 登录墙；
    必须从 https://www.jobui.com/jobs/ 表单流程进入（填 jobKw → 回车 →
    同域带 Referer 跳转目标 URL），实测 北京+后端 4586 条免登录。
  - 列表为服务端渲染 HTML，无列表 JSON API；每页 20 条；
    第 2 页起匿名触发登录弹窗 → 首版只采第 1 页（20 条/组合）。
  - 反爬：高频访问触发 IP 级 /tips/valid.php 图片验证码，
    约 10-15 分钟自动解封；登录仅支持微信扫码（首版匿名采集）。
  - 详情页 /job/<id>/ 为跳转页（无 JD 正文）→ jd_fulltext 统一 NULL。

限速（组长裁决）：批次内相邻两次搜索之间 sleep uniform(5, 10) 秒。
settings.batch_delay_sec == 0 视为测试模式，不等待（与 BOSS 批次约定一致）。
"""

from __future__ import annotations

import logging
import os
import random
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from core.config import Settings
from core.exceptions import ScraperError, ScraperTimeoutError, TrackerError

log = logging.getLogger(__name__)

JOBUI_BASE_URL = "https://www.jobui.com"
JOBUI_ENTRY_URL = f"{JOBUI_BASE_URL}/jobs/"           # 表单流程入口（带 Referer 语境）
JOBUI_SOURCE_DOMAIN = "www.jobui.com"

# 数据来源：recon bj_ok_list.html（北京+后端，2026-09-23 真实捕获）
LIST_XPATH = '//div[contains(concat(" ", normalize-space(@class), " "), " c-job-list ")]'
_JOB_ID_RE = re.compile(r"/job/(\d+)/")

# 脚本约定退出码（scripts/jobui_cdp_raw.py）
EXIT_LOGIN_WALL = 2
EXIT_CAPTCHA = 3

_ENTRY_CANDIDATES = ("scripts/jobui_cdp_raw.py",)


class JobuiLoginRequiredError(TrackerError):
    """采集流程被重定向到 /people/login/（匿名表单流程失效，需重新走表单入口）"""


class JobuiCaptchaError(TrackerError):
    """IP 被 /tips/valid.php 图片验证码拦截（高频触发，约 10-15 分钟自动解封）"""


@dataclass(frozen=True)
class JobuiScraperConfig:
    """单次采集参数（对齐 ScraperConfig，max_pages 首版固定第 1 页）"""

    keyword: str
    city: str                            # 城市名，如"北京"（URL 里作 cityKw）
    max_pages: int = 1                   # 首版只采第 1 页（分页第 2 页起匿名触发登录弹窗）
    timeout: int = 300                   # 子进程超时
    output_dir: Path = Path("data/raw")  # JSON 落盘目录


def build_search_url(keyword: str, city: str) -> str:
    """构造公开搜索 URL。注意：直接访问会撞登录墙，须由表单流程/带 Referer 导航使用"""
    return f"{JOBUI_BASE_URL}/jobs?{urlencode({'cityKw': city, 'jobKw': keyword})}"


def check_final_url(url: str) -> str:
    """最终 URL 反爬检测：登录墙 / 验证码。正常返回原 URL。

    - 含 /people/login → JobuiLoginRequiredError
    - 含 /tips/valid   → JobuiCaptchaError
    """
    if "/people/login" in url:
        raise JobuiLoginRequiredError(f"跳转到登录页（匿名表单流程失效）: {url}")
    if "/tips/valid" in url:
        raise JobuiCaptchaError(f"触发图片验证码（IP 级限流，约 10-15 分钟解封）: {url}")
    return url


def parse_list_html(html: str, page_url: str = "") -> list[dict]:
    """列表页 HTML → 职友集岗位记录列表（scraper JSON 的 jobs 元素）。

    DOM 结构（recon 实测，div.j-recommendJob > div.c-job-list，每页 20 条）：
      a.job-name[href="/job/<id>/"] > h3  → 标题（<strong> 高亮需拼接）
      span[title="工作经验要求：X"] > span → 经验（原文照存）
      span[title="学历要求：X"] > span    → 学历（原文照存，"本科以上"≠"本科"）
      span.job-pay-text                  → 薪资原文（"8-15k" / "35000-50000元" / "1.5-1.6万"）
      a.job-company-name[href="/company/<id>/jobs/"] → 公司名
      div.job-add-date                   → 发布时间（"1天前"）
    缺 job-name/pay/company 的占位卡片（真实页面存在）直接跳过。
    """
    from lxml import html as lxml_html  # 延迟导入：依赖声明在 pyproject dependencies

    doc = lxml_html.fromstring(html)
    records: list[dict] = []
    for card in doc.xpath(LIST_XPATH):
        name_a = card.xpath('.//a[contains(@class,"job-name")]')
        if not name_a:
            continue
        href = name_a[0].get("href") or ""
        m = _JOB_ID_RE.search(href)
        if not m:
            continue
        title = "".join(name_a[0].itertext()).strip()
        pays = card.xpath('.//span[contains(@class,"job-pay-text")]/text()')
        companies = card.xpath('.//a[contains(@class,"job-company-name")]/text()')
        if not title or not pays:
            continue

        experience = education = ""
        for span in card.xpath('.//span[@title]/@title'):
            if span.startswith("工作经验要求："):
                experience = span[len("工作经验要求："):]
            elif span.startswith("学历要求："):
                education = span[len("学历要求："):]

        add_dates = card.xpath('.//div[contains(@class,"job-add-date")]/text()')
        company_url = ""
        comp_a = card.xpath('.//a[contains(@class,"job-company-name")]/@href')
        if comp_a:
            company_url = f"{JOBUI_BASE_URL}{comp_a[0]}"

        records.append({
            "job_id": m.group(1),
            "encrypt_job_id": f"jobui_{m.group(1)}",
            "title": title,
            "salary": pays[0].strip(),
            "experience": experience.strip(),
            "education": education.strip(),
            "company_name": (companies[0].strip() if companies else ""),
            "detail_url": f"{JOBUI_BASE_URL}{href}",
            "company_url": company_url,
            "add_date": (add_dates[0].strip() if add_dates else ""),
        })
    return records


def _resolve_jobui_argv(settings: Settings) -> list[str]:
    """定位职友集采集脚本入口。

    优先级：环境变量 JOBUI_SCRAPER_ENTRY > 当前工作目录下 scripts/jobui_cdp_raw.py
    （与 BOSS wrapper 的 cwd 相对探测约定一致，在仓库根目录运行）。
    找不到抛 ScraperError。
    """
    entry = os.environ.get("JOBUI_SCRAPER_ENTRY")
    if entry and Path(entry).is_file():
        return [settings.python_bin, entry]

    for candidate in _ENTRY_CANDIDATES:
        if Path(candidate).is_file():
            return [settings.python_bin, candidate]

    raise ScraperError(
        "未找到职友集采集脚本 scripts/jobui_cdp_raw.py。请：\n"
        "  1. 确认在仓库根目录运行，或\n"
        "  2. 设置环境变量 JOBUI_SCRAPER_ENTRY 指向该脚本的绝对路径\n"
        "（该脚本依赖 playwright，见 README「职友集采集（Week 4）」）"
    )


def _output_path(config: JobuiScraperConfig) -> Path:
    """生成本次采集的 JSON 落盘路径（相对当前工作目录）"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = lambda s: "".join(c if c.isalnum() else "_" for c in s).strip("_")
    return config.output_dir / f"jobui_jobs_{safe(config.city)}_{safe(config.keyword)}_{ts}.json"


def run_scraper(config: JobuiScraperConfig, settings: Settings) -> Path:
    """启动 scripts/jobui_cdp_raw.py（subprocess），返回产出的 JSON 路径。

    失败抛 ScraperError（非零退出码 / 输出缺失或为空）；
    超时抛 ScraperTimeoutError；
    脚本退出码 2 → JobuiLoginRequiredError；3 → JobuiCaptchaError。
    """
    argv_prefix = _resolve_jobui_argv(settings)
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
    log.info("启动 jobui 采集: %s", " ".join(argv))
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        raise ScraperError(f"jobui 采集子进程启动失败: {e}") from e

    try:
        stdout, stderr = proc.communicate(timeout=config.timeout)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        proc.wait()
        raise ScraperTimeoutError(
            f"jobui 采集超时（>{config.timeout}s）: {config.keyword} @ {config.city}"
        ) from e

    if proc.returncode == EXIT_LOGIN_WALL:
        raise JobuiLoginRequiredError(
            f"登录墙（{config.keyword} @ {config.city}）: {(stderr or '').strip()[-300:]}"
        )
    if proc.returncode == EXIT_CAPTCHA:
        raise JobuiCaptchaError(
            f"验证码拦截（{config.keyword} @ {config.city}）: {(stderr or '').strip()[-300:]}"
        )
    if proc.returncode != 0:
        tail = (stderr or stdout or "").strip()[-500:]
        raise ScraperError(
            f"jobui 采集非零退出码 {proc.returncode}: "
            f"{config.keyword} @ {config.city}\n{tail}"
        )

    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise ScraperError(
            f"jobui 采集未产出有效 JSON: {out_path}\n{(stdout or '')[-500:]}"
        )
    log.info("jobui 采集完成: %s", out_path)
    return out_path


def run_scraper_batch(
    keywords: list[str],
    cities: list[str],
    settings: Settings,
    max_pages: int = 1,
) -> list[Path]:
    """多轮渐进：遍历 (keyword × city)，逐次调用 run_scraper()。

    相邻两次搜索之间 sleep uniform(5, 10) 秒（组长裁决的限速）；
    settings.batch_delay_sec == 0 视为测试模式不等待（与 BOSS 批次约定一致）。
    单个组合失败（含登录墙/验证码）记录日志后继续，不中断整批；
    返回成功的 JSON 路径列表。
    """
    results: list[Path] = []
    combos = [(kw, city) for kw in keywords for city in cities]
    for i, (kw, city) in enumerate(combos):
        config = JobuiScraperConfig(
            keyword=kw, city=city,
            max_pages=max_pages, timeout=settings.scraper_timeout,
            output_dir=settings.raw_output_dir,
        )
        try:
            results.append(run_scraper(config, settings))
        except (ScraperError, JobuiLoginRequiredError, JobuiCaptchaError) as e:
            log.error("jobui 采集失败（跳过，继续下一组合）: %s", e)
        if i < len(combos) - 1 and settings.batch_delay_sec > 0:
            time.sleep(random.uniform(5, 10))
    return results


def check_jobui_scraper_installed() -> bool:
    """环境检查：jobui 采集脚本是否可用。任何情况下返回 bool，不抛异常。"""
    try:
        entry = os.environ.get("JOBUI_SCRAPER_ENTRY")
        if entry and Path(entry).is_file():
            return True
        return any(Path(c).is_file() for c in _ENTRY_CANDIDATES)
    except Exception:  # 环境检查永不抛异常
        return False
