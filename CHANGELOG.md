# CHANGELOG

## [Unreleased]

### Added (Week 1 — 架构基线)
- 架构概览：模块边界、端到端数据流、NFR 落点
- 数据库 ERD：4 表（snapshots / keywords / cities / job_snapshot）+ DDL + 种子数据
- 模块接口：dataclass + 函数签名 + 异常体系 + 分阶段交付计划
- 项目目录结构：完整树形结构 + pyproject.toml / .gitignore / README 模板
- 架构决策记录 ADR：14 份，覆盖 SQLite / 模块化单体 / 反爬 / Cookie / JD 两阶段 / cron 等
- BOSS 直聘爬虫预研报告 + 60 条真实样本（CSV + JSON）

### Added (Week 2 — 采集管线，架构 v1.1 CDP 方案)
- `collectors/boss_scraper.py`：boss-zhipin-scraper CLI wrapper（subprocess.Popen，300s 超时 → `ScraperTimeoutError`，非零退出/空输出 → `ScraperError`）；按真实 CLI（`scripts/boss_cdp_raw.py --pages`）实现，函数签名同接口文档 §6
- `importers/boss_importer.py`：JSON → SQLite UPSERT（§7 五函数）；字段映射兼容 scraper 真实输出、§7 假设字段、W1 预研样本三种格式；`dedup_jobs` + `INSERT OR IGNORE` 双重去重
- `storage/schema.py` + `storage/migrations/0001_initial.sql`：4 表 + schema_version + 种子数据（5 城 + 35 关键词）；含 `year_multiplier` / `salary_unit` / `UNIQUE(encrypt_job_id, snapshot_date)`
- `core/`：models / salary 解析（月薪·N薪/日薪/时薪，日薪不折算混算）/ cleansing（学历、公司名）/ dedup / config / exceptions
- `storage/`：connection（WAL + busy_timeout）/ dao / `python -m storage.schema` 初始化入口
- `analysis/stats.py`：季度归属 + 同比/环比（分母 NULL/0 → NULL）
- 实测：单城（北京）× 单关键词（后端）× ≤3 页管线跑通（仿真 CLI + W1 真实样本 60 条均验证）
- 89 个单元测试全部通过（薪资/城市/学历/去重/季度/同比环比/importer/wrapper/schema）

### Changed
- ERD 种子数据补齐第 35 个关键词（前端/JavaScript）——原文档容量表写 35 行但清单只列 34 个，按 §14 验收对齐，待对照 PRD §3.1 确认

### Planned
- Week 3：同比分析 + 关键词词云 + HTML 报告
- Week 4：职友集采集 + 跨平台对比
- Week 5：cron 自动化 + CI 健康检查