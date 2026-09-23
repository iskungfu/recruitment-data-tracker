#!/usr/bin/env python3
"""仿真 scripts/jobui_cdp_raw.py —— 仅用于单元测试，不依赖 Chrome / 网络。

复刻真实采集脚本的 CLI 契约与退出码约定：
  - 参数：--keyword --city --pages --format json --output --cdp-port
  - 输出：{"platform","source_platform","keyword","city","total","jobs":[...]}
    job 字段为 jobui 列表页 DOM 解析后的真实格式（job_id / title / salary /
    experience / education / company_name / detail_url / company_url / add_date）
  - 退出码：0 成功 / 1 一般错误 / 2 登录墙 / 3 验证码

特殊 keyword 用于触发异常路径：
  - "SLOW"   : sleep 10 秒（测试 ScraperTimeoutError）
  - "FAIL"   : 退出码 1（测试 ScraperError）
  - "EMPTY"  : 退出码 0 但不产出文件（测试 ScraperError）
  - "LOGIN"  : 退出码 2（测试 JobuiLoginRequiredError）
  - "CAPTCHA": 退出码 3（测试 JobuiCaptchaError）
"""

from __future__ import annotations

import argparse
import json
import sys
import time

SAMPLE_JOBS = [
    {
        "job_id": "900000001",
        "encrypt_job_id": "jobui_900000001",
        "title": "后端开发",
        "salary": "35000-50000元",
        "experience": "3-5年",
        "education": "本科以上",
        "company_name": "中科软科技股份有限公司",
        "detail_url": "https://www.jobui.com/job/900000001/",
        "company_url": "https://www.jobui.com/company/19563/jobs/",
        "add_date": "1天前",
    },
    {
        "job_id": "900000002",
        "encrypt_job_id": "jobui_900000002",
        "title": "Java 开发工程师",
        "salary": "8-15k",
        "experience": "1-3年",
        "education": "本科以上",
        "company_name": "某科技有限公司",
        "detail_url": "https://www.jobui.com/job/900000002/",
        "company_url": "https://www.jobui.com/company/790998/jobs/",
        "add_date": "1天前",
    },
    {
        "job_id": "900000003",
        "encrypt_job_id": "jobui_900000003",
        "title": "后端实习生",
        "salary": "150-200元/天",
        "experience": "不限经验",
        "education": "初中以上",
        "company_name": "实习公司",
        "detail_url": "https://www.jobui.com/job/900000003/",
        "company_url": "https://www.jobui.com/company/8885887/jobs/",
        "add_date": "2天前",
    },
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--city", required=True)
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--format", default="json", choices=["json"])
    p.add_argument("--output", required=True)
    p.add_argument("--cdp-port", type=int, default=9222)
    args = p.parse_args()

    if args.keyword == "SLOW":
        time.sleep(10)
        return 0
    if args.keyword == "FAIL":
        print("模拟采集脚本崩溃", file=sys.stderr)
        return 1
    if args.keyword == "EMPTY":
        return 0  # 退出码 0 但不写文件
    if args.keyword == "LOGIN":
        print("JobuiLoginRequiredError: 登录墙 https://www.jobui.com/people/login/", file=sys.stderr)
        return 2
    if args.keyword == "CAPTCHA":
        print("JobuiCaptchaError: 验证码 https://www.jobui.com/tips/valid.php", file=sys.stderr)
        return 3

    payload = {
        "platform": "JOBUI",
        "source_platform": "www.jobui.com",
        "keyword": args.keyword,
        "city": args.city,
        "total": len(SAMPLE_JOBS),
        "jobs": SAMPLE_JOBS,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"已保存: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
