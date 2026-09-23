#!/usr/bin/env python3
"""职友集（jobui.com）CDP 采集脚本 — Week 4

本脚本是 collectors/jobui_scraper.py wrapper 的子进程入口，
对齐外部 boss-zhipin-scraper 的 CLI 契约（--keyword/--city/--pages/--format/--output），
由 wrapper 组装参数后 subprocess 调用。

采集方式：CDP 被动优先——连接本机 Chrome（--cdp-port，默认 9222，
需先以 --remote-debugging-port=9222 启动 Chrome），复用真实浏览器指纹，
不自建 HTTP 请求。

表单流程（2026-09-23 recon 实测验证，北京+后端 4586 条免登录）：
  1. 打开 https://www.jobui.com/jobs/（建立同域导航语境）
  2. input[name=jobKw] 逐字输入关键词 → 回车（服务端渲染出结果页）
  3. 同域带 Referer 跳转 build_search_url()（补上 cityKw 城市过滤）
     直接访问该 URL（无 Referer）会 302 → /people/login/，步骤 1-2 不能省。

反爬处理（退出码约定，wrapper 按此映射异常）：
  0 成功 / 1 一般错误 / 2 JobuiLoginRequiredError（登录墙）/ 3 JobuiCaptchaError（验证码）

首版只采第 1 页：分页第 2 页起匿名触发登录弹窗（--pages>1 仅打印警告）。

依赖：playwright（pip install playwright，本脚本不进 pytest 测试路径——
单元测试用 tests/fixtures/fake_jobui_cdp_raw.py 仿真 CLI，不依赖本脚本）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 使脚本可直接 `python3 scripts/jobui_cdp_raw.py` 运行（仓库根目录入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.jobui_scraper import (
    EXIT_CAPTCHA,
    EXIT_LOGIN_WALL,
    JOBUI_ENTRY_URL,
    JOBUI_SOURCE_DOMAIN,
    JobuiCaptchaError,
    JobuiLoginRequiredError,
    build_search_url,
    check_final_url,
    parse_list_html,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _connect_browser(cdp_port: int):
    """连接本机 Chrome CDP；连不上给友好报错（退出码 1）"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("错误: 未安装 playwright（pip install playwright）", file=sys.stderr)
        raise SystemExit(1)

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
    except Exception as e:
        pw.stop()
        print(
            f"错误: 无法连接本机 Chrome CDP (127.0.0.1:{cdp_port}): {e}\n"
            "请先启动: chrome --remote-debugging-port=9222",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return pw, browser


def _wall_exit(page_url: str) -> None:
    """登录墙/验证码检测（复用 check_final_url）——命中即按约定退出码结束

    wrapper 按退出码映射异常：2 → JobuiLoginRequiredError，3 → JobuiCaptchaError
    """
    try:
        check_final_url(page_url)
    except (JobuiLoginRequiredError, JobuiCaptchaError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(EXIT_LOGIN_WALL if isinstance(e, JobuiLoginRequiredError) else EXIT_CAPTCHA)


def collect(keyword: str, city: str, cdp_port: int, nav_wait_sec: float = 4.0) -> list[dict]:
    """执行一次「关键词 × 城市」的表单流采集，返回岗位记录列表。

    仅供 wrapper 经 subprocess 调用；也可在 REPL 中直接 import 调试。
    """
    pw, browser = _connect_browser(cdp_port)
    context = None
    page = None
    own_context = False
    try:
        if browser.contexts:
            # 用户真实 Chrome 的默认 context——绝不能整个 close（会关掉用户其它标签页）
            context = browser.contexts[0]
        else:
            context = browser.new_context()
            own_context = True
        page = context.new_page()
        page.set_default_timeout(45000)

        # 步骤 1：入口页（建立同域导航语境；recon 实测省略会撞登录墙）
        page.goto(JOBUI_ENTRY_URL, wait_until="domcontentloaded")
        time.sleep(3)
        _wall_exit(page.url)

        # 步骤 2：表单输入关键词 → 回车（服务端渲染结果页）
        kw_input = page.locator('input[name="jobKw"]')
        if kw_input.count() == 0:
            print(f"错误: 入口页未找到 jobKw 输入框: {page.url}", file=sys.stderr)
            raise SystemExit(1)
        kw_input.first.click()
        time.sleep(1)
        page.keyboard.type(keyword, delay=120)
        time.sleep(1)
        page.keyboard.press("Enter")
        page.wait_for_load_state("domcontentloaded")
        time.sleep(nav_wait_sec)
        _wall_exit(page.url)

        # 步骤 3：同域带 Referer 跳转，补 cityKw 城市过滤
        target = build_search_url(keyword, city)
        page.goto(target, referer=page.url, wait_until="domcontentloaded")
        time.sleep(nav_wait_sec)
        _wall_exit(page.url)

        # 步骤 4：等待列表容器渲染后取整页 HTML → DOM 解析
        page.wait_for_selector("div.j-recommendJob", timeout=30000)
        html = page.content()
        return parse_list_html(html, page.url)
    finally:
        # 验证缺口修复：只关自己开的 page；仅自建 context 分支才 close context
        # （browser.contexts[0] 是用户真实 Chrome 的默认 context，整体关闭
        #   会连带关掉用户的其它标签页）
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if own_context and context is not None:
            try:
                context.close()
            except Exception:
                pass
        browser.close()
        pw.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="职友集 CDP 采集（列表第 1 页）")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--pages", type=int, default=1,
                        help="首版只采第 1 页；>1 仅打印警告")
    parser.add_argument("--format", default="json", choices=["json"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--cdp-port", type=int, default=9222)
    args = parser.parse_args()

    if args.pages > 1:
        print("警告: 分页第 2 页起匿名触发登录弹窗，首版只采第 1 页", file=sys.stderr)

    try:
        jobs = collect(args.keyword, args.city, args.cdp_port)
    except SystemExit:
        raise
    except Exception as e:
        print(f"错误: 采集失败（{args.keyword} @ {args.city}）: {e}", file=sys.stderr)
        return 1

    payload = {
        "platform": "JOBUI",
        "source_platform": JOBUI_SOURCE_DOMAIN,
        "keyword": args.keyword,
        "city": args.city,
        "total": len(jobs),
        "jobs": jobs,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存 {len(jobs)} 条: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
