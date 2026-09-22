#!/usr/bin/env python3
"""仿真 boss-zhipin-scraper 的 scripts/boss_cdp_raw.py —— 仅用于单元测试。

复刻真实 CLI 行为（以 eatmoreduck/boss-zhipin-scraper v2.2 源码为准）：
  - 参数：--keyword --city --pages --format json --output <文件> --no-detail
  - 输出：{"keyword","city","total","jobs":[...]}，job 字段为真实格式
    （title / salary / location / tags / boss_name / skills / encrypt_job_id / job_link）

特殊 keyword 用于触发异常路径：
  - "SLOW"   : sleep 10 秒（测试 ScraperTimeoutError）
  - "FAIL"   : 非零退出（测试 ScraperError）
  - "EMPTY"  : 正常退出但不产出文件（测试 ScraperError）
"""

from __future__ import annotations

import argparse
import json
import sys
import time

SAMPLE_JOBS = [
    {
        "title": "后端开发工程师",
        "salary": "30-60K·15薪",
        "salary_source": "api",
        "location": "北京·朝阳区·望京",
        "tags": "3-5年 | 本科",
        "boss_name": "示例科技有限公司",
        "skills": "Java | Spring | MySQL",
        "encrypt_job_id": "test-encrypt-0001",
        "job_link": "https://www.zhipin.com/job_detail/test-encrypt-0001.html",
    },
    {
        "title": "Python 后端工程师",
        "salary": "15-30K",
        "salary_source": "api",
        "location": "北京·海淀区·中关村",
        "tags": "1-3年 | 本科",
        "boss_name": "另一家公司",
        "skills": "Python | FastAPI",
        "encrypt_job_id": "test-encrypt-0002",
        "job_link": "https://www.zhipin.com/job_detail/test-encrypt-0002.html",
    },
    {
        "title": "后端实习生",
        "salary": "500-550元/天",
        "salary_source": "api",
        "location": "北京·朝阳区",
        "tags": "在校生 | 本科",
        "boss_name": "实习公司",
        "skills": "Go",
        "encrypt_job_id": "test-encrypt-0003",
        "job_link": "https://www.zhipin.com/job_detail/test-encrypt-0003.html",
    },
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--city", required=True)
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--format", default="json", choices=["json", "csv"])
    p.add_argument("--output", required=True)
    p.add_argument("--cdp-port", type=int, default=9222)
    p.add_argument("--no-detail", action="store_true")
    args = p.parse_args()

    if args.keyword == "SLOW":
        time.sleep(10)
        return 0
    if args.keyword == "FAIL":
        print("模拟 scraper 崩溃", file=sys.stderr)
        return 2
    if args.keyword == "EMPTY":
        return 0  # 退出码 0 但不写文件

    jobs = []
    for job in SAMPLE_JOBS:
        job = dict(job)
        job["location"] = f"{args.city}·" + job["location"].split("·", 1)[-1]
        jobs.append(job)
    payload = {"keyword": args.keyword, "city": args.city, "total": len(jobs), "jobs": jobs}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"已保存: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
