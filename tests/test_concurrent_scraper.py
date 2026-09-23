"""并发采集层测试 — scripts/boss_cdp_raw.py 的 --keywords 模式（Week 6）

不走真实 CDP/网络：用 importlib 按路径加载脚本模块，注入 fake scrape_fn
验证并发编排逻辑（关键词解析、跨 worker 全局去重、登录墙传播、单点失败隔离）。
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "boss_cdp_raw.py"
spec = importlib.util.spec_from_file_location("boss_cdp_raw", SCRIPT)
boss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boss)


def _jobs(prefix, eids):
    return [{"title": f"{prefix}-{e}", "encrypt_job_id": e} for e in eids]


def test_keywords_split():
    # 中英文逗号、空白、空段、保序去重
    assert boss.parse_keywords("后端,前端， 算法工程师 ,,后端") == ["后端", "前端", "算法工程师"]
    assert boss.parse_keywords("") == []
    assert boss.parse_keywords(None) == []


def test_keywords_file(tmp_path):
    f = tmp_path / "keywords.txt"
    f.write_text("后端\n前端,算法工程师\n\n后端\n", encoding="utf-8")
    assert boss.load_keywords_file(str(f)) == ["后端", "前端", "算法工程师"]


def test_dedup_across_workers():
    # 两个"worker"（关键词）返回相同 encrypt_job_id → 合并后只保留一条
    def fake(kw):
        return {"keyword": kw, "total": 2, "jobs": _jobs(kw, ["eid-1", "eid-2"])}

    results = boss.scrape_keywords_concurrent(
        ["后端", "前端"],
        "北京",
        3,
        {},
        workers=2,
        scrape_fn=fake,
        inter_delay=0,
        progress=False,
    )
    merged, counts = boss.merge_keyword_results(results, ["后端", "前端"])
    assert sum(counts.values()) == 4  # 原始 4 条
    assert len(merged) == 2  # 全局去重后 2 条
    assert [j["encrypt_job_id"] for j in merged] == ["eid-1", "eid-2"]
    # encrypt_job_id 缺失时回退 job_link 去重
    dup = [
        {"title": "A", "encrypt_job_id": "", "job_link": "https://x/1"},
        {"title": "B", "encrypt_job_id": "", "job_link": "https://x/1"},
    ]
    assert len(boss.dedupe_jobs_global(dup)) == 1


def test_login_wall_propagates():
    # 模拟验证码：任一 worker 命中 → 异常传播、其他 worker 收尾、不挂死
    calls = []

    def fake(kw):
        calls.append(kw)
        if kw == "前端":
            raise boss.LoginGateError("模拟验证码/登录墙")
        time.sleep(0.2)
        return {"keyword": kw, "total": 0, "jobs": []}

    t0 = time.time()
    with pytest.raises(boss.LoginGateError):
        boss.scrape_keywords_concurrent(
            ["后端", "前端", "算法", "测试"],
            "北京",
            3,
            {},
            workers=2,
            scrape_fn=fake,
            inter_delay=30,
            progress=False,
        )
    elapsed = time.time() - t0
    # 不挂死：命中登录墙后 inter_delay=30s 不再生效，整体应在几秒内返回
    assert elapsed < 10
    assert "前端" in calls


def test_worker_failure_isolated():
    # 单关键词抛一般异常不拖垮整体：该词记 error，其余正常完成
    def fake(kw):
        if kw == "算法":
            raise RuntimeError("模拟 CDP 掉线")
        return {"keyword": kw, "total": 1, "jobs": _jobs(kw, [f"eid-{kw}"])}

    results = boss.scrape_keywords_concurrent(
        ["后端", "算法", "前端"],
        "北京",
        3,
        {},
        workers=2,
        scrape_fn=fake,
        inter_delay=0,
        progress=False,
    )
    assert results["算法"]["total"] == 0
    assert "RuntimeError" in results["算法"]["error"]
    merged, counts = boss.merge_keyword_results(results, ["后端", "算法", "前端"])
    assert counts["后端"] == 1 and counts["前端"] == 1
    assert len(merged) == 2
