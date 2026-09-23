"""发布管线包 — 本地分析结果 → 静态 JSON → GitHub data branch → jsDelivr CDN。

架构契约见 docs/06-website-architecture-v1.0.md §3.2：
6 个 JSON（manifest / summary / salary_trends / job_ranking /
edu_exp_distribution / data_status）输出到 data/publish/v1/。

模块：
- cli.py          发布编排入口（python -m data.publish.cli）
- format_check.py 输出 schema 校验（python -m data.publish.format_check）
"""
