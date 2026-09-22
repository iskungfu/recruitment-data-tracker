# CHANGELOG

## [Unreleased]

### Added (Week 1 — 架构基线)
- 架构概览：模块边界、端到端数据流、NFR 落点
- 数据库 ERD：4 表（snapshots / keywords / cities / job_snapshot）+ DDL + 种子数据
- 模块接口：dataclass + 函数签名 + 异常体系 + 分阶段交付计划
- 项目目录结构：完整树形结构 + pyproject.toml / .gitignore / README 模板
- 架构决策记录 ADR：14 份，覆盖 SQLite / 模块化单体 / 反爬 / Cookie / JD 两阶段 / cron 等
- BOSS 直聘爬虫预研报告 + 60 条真实样本（CSV + JSON）

### Planned
- Week 2：爬虫 MVP（5 城采集器 + SQLite 写入）
- Week 3：同比分析 + 关键词词云 + HTML 报告
- Week 4：职友集采集 + 跨平台对比
- Week 5：cron 自动化 + CI 健康检查