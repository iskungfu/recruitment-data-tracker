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
- `storage/schema.py` + `storage/migrations/0001_initial.sql`：4 表 + schema_version + 种子数据（5 城 + 34 关键词，PRD §3.1 裁决口径）；含 `year_multiplier` / `salary_unit` / `UNIQUE(encrypt_job_id, snapshot_date)`
- `core/`：models / salary 解析（月薪·N薪/日薪/时薪，日薪不折算混算）/ cleansing（学历、公司名）/ dedup / config / exceptions
- `storage/`：connection（WAL + busy_timeout）/ dao / `python -m storage.schema` 初始化入口
- `analysis/stats.py`：季度归属 + 同比/环比（分母 NULL/0 → NULL）
- 实测：单城（北京）× 单关键词（后端）× ≤3 页管线跑通（仿真 CLI + W1 真实样本 60 条均验证）
- 89 个单元测试全部通过（薪资/城市/学历/去重/季度/同比环比/importer/wrapper/schema）

### Changed
- **用户裁决（2026-09-23，PRD §3.1）**：前端方向保持 3 个关键词（前端/Vue/React），keywords 种子数据定为 34 行；删除曾补入的 `('前端', 'JavaScript')`，SQL / ERD / ADR / 配置 / README / 测试断言同步回退为 34
- 架构文档 v1.2：`03-module-interfaces.md` 替换为 v1.2 版——§6 CLI 入口对齐 boss-zhipin-scraper 上游真实命令（`scripts/boss_cdp_raw.py --pages`），§7 字段映射表对齐 scraper 真实 JSON 输出 key（三格式兼容兜底）；§14 验收口径同步为 keywords 34 行
- ERD §4 容量估算同步：keywords 34 行、snapshots 单季度 170 行、一年累积 680 行
- README：Week 3 状态 + 数据分析使用说明

### Added (Week 3 — 数据分析)
- `analysis/stats.py` 新增 `compute_yoy_qoq(db_path, city=None)`：overall / by_city / by_direction 三维度同比+环比（复用 `get_quarter_of` / `_ratio`，分母 NULL/0 → NULL）；日薪岗位（`salary_unit='day'`）不计入薪资均值；月薪均值取 (min+max)/2 中点；方向归属为启发式（job_name 含关键词 → 该关键词方向，未匹配计入 `unattributed` 字段）
- `analysis/keywords.py` 新增 `analyze_keywords(db_path, top_n=50)`：jieba 分词 + 单字/标点/停用词过滤，频次并列时按词字典序排序（确定性输出）
- `analysis/report.py` 新增 `generate_report(db_path, city=None) -> str`：KPI 卡片（总岗位 / 5 城排名 / 当季均薪）+ 5 类图表（多城市薪资趋势线图、方向薪资分组柱状图、JD 高频词横向柱状图、学历/经验分布饼图）；`string.Template` + Plotly `to_html` 单文件输出（plotly.js 仅首个图表内嵌，~4.5MB，无外部 `<script src>`）；CLI：`python -m analysis.report [db_path] [output]`，默认 `data/recruitment.db` → `report.html`
- `tests/test_analysis.py`：13 个测试（同比环比数值/日薪排除/城市过滤/空分母、词频 top_n/停用词/单字过滤、报告生成/CLI 入口/空库），含 `test_pie_values_are_counts` 回归锁
- 依赖正式化：jieba / plotly 写入 pyproject dependencies（原为注释占位）
- 修复（浏览器渲染验证发现）：饼图曾误传标签列表为频次（`values=list(dist)` → `values=list(dist.values())`），已修复并加回归测试

### Planned
- Week 4：职友集采集 + 跨平台对比
- Week 5：cron 自动化 + CI 健康检查