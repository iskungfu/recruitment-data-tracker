# CHANGELOG

## [Unreleased]

### Added (Week 6 — 并发采集)
- `scripts/boss_cdp_raw.py` 入仓（源自外部 boss-zhipin-scraper v2.2，随 Week 1 预研克隆）并新增 `--keywords` / `--keywords-file` / `--workers` 并发模式：`ThreadPoolExecutor` 4-10 worker（默认 6，超出自动钳制），每 worker 独立 CDP 会话 + page（复用 `scrape_list` 既有结构，不改其签名），同一 worker 连续搜索间隔 uniform(3,7)s，tqdm 进度条实时显示各 worker 当前关键词，合并结果按 `encrypt_job_id` 全局去重后单文件输出，每关键词增量落盘 `<输出名>_parts/`
- 登录墙/验证码（`LoginGateError`）：任一 worker 命中即 stop_event 通知全员在当前关键词边界优雅收尾，主线程重抛并以退出码 1 退出；单关键词其他异常记 `error` 字段不拖垮整体
- 并发模式仅列表采集（等价 `--no-detail`），不支持 `--merge` / `--input`；单 `--keyword` 模式完全向后兼容
- `data/city_codes.json` 入仓（11K 城市码表，仓库内运行可离线解析城市）
- `tests/test_concurrent_scraper.py` 5 个测试（关键词解析/文件读取、跨 worker 去重、登录墙传播不挂死、单点失败隔离），全仓 181 测试全绿
- 与派发的偏差说明：派发要求「worker 复用同一 page 搜下一个关键词」，实现改为每关键词独立 page——`scrape_list` 内部自建/自毁会话，改造复用需动其签名与清理逻辑，风险大于收益；每关键词新 tab 开销 <1s 且更贴近真人行为

### Fixed (Week 6 — 发布脚本速修)
- `scripts/quarterly_publish.sh`：P2 修复——`python -m tracker collect || true` 引用了不存在的 `tracker` 模块，每次静默跳过采集；改为先用 `importlib.import_module('tracker')` 探测，模块存在才采集，否则打印警告后继续发布现有库数据（当前版本采集需手动执行，README 已注明）
- 同脚本 P3 修复：提交推送改为 `git diff --cached --quiet || git commit ... && git push origin HEAD:data`，无变更时跳过 commit 不再误报失败（已实测两种路径）

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

### Added (Week 4 — 职友集采集管线，步骤二)
- `collectors/jobui_scraper.py`：职友集 CDP 采集 wrapper，对齐 boss_scraper 三函数契约（`check_jobui_scraper_installed` / `run_scraper` / `run_scraper_batch`）；批次内相邻搜索 `sleep uniform(5, 10)` 限速（`batch_delay_sec=0` 为测试模式不等待）；登录墙/验证码按脚本退出码 2/3 映射为 `JobuiLoginRequiredError` / `JobuiCaptchaError`；`check_final_url` / `build_search_url` / `parse_list_html`（lxml DOM 解析，真实页面含无字段占位卡时跳过）
- `scripts/jobui_cdp_raw.py`：职友集采集脚本（playwright `connect_over_cdp` 连本机 Chrome，表单流匿名免登录——入口页→输入 jobKw→同域带 Referer 跳转；首版只采第 1 页 20 条，第 2 页起匿名触发登录弹窗）
- `importers/jobui_importer.py`：JSON→SQLite，复用 boss_importer 框架（read_scraper_json + dedup + INSERT OR IGNORE）；字段口径按组长裁决：薪资统一换算 **K** 落库（元÷1000/K×1/万×10；面议→NULL；XX以上→仅 salary_min；日薪→day+NULL；默认 month+year_multiplier=12）——追裁决 (a) 对齐 `core/salary.py` 冻结契约 K/月，跨平台对比同口径；学历/经验/公司名原文照存；城市未匹配→city_id NULL 不丢记录；`jd_fulltext` 统一 NULL（详情页为跳转页）；CLI `python -m importers.jobui_importer`（缺失 DB 友好报错，对齐 P2 口径）
- `storage/migrations/0002_jobui_source.sql` + `storage/schema.py` 迁移循环：job_snapshot 新增 `source_platform`（来源域名）/ `source_url`（详情页 URL）列；`apply_pending_migrations` 按 schema_version 版本号顺序执行 0002+，幂等；旧库首次经 jobui importer 入库时自动补列（`ensure_source_columns`）
- `tests/`：46 个新测试——DOM 解析用 2026-09-23 预研真实捕获 HTML 切片（`tests/fixtures/jobui_list_sample.html`，20 有效卡+3 占位卡）；薪资换算覆盖裁决五类+真实样本补充格式（裸数字/万/大写K/万以上）；学历原文（"本科以上"≠"本科"）；来源站列写入；登录墙/验证码 URL 检测与退出码映射；仿真 CLI 复刻 wrapper 契约不依赖 Chrome/网络；migration 幂等与旧库自动补列；BOSS/JOBUI 同表 K 口径混合入库验证（跨平台对比前提）
- 依赖：`lxml>=4.9` 写入 pyproject dependencies（playwright 为采集脚本可选运行时依赖，不进测试路径）
- 实测：`python -m storage.schema` → `python -m importers.jobui_importer`（真实样本 20 条）端到端跑通；149 个测试全绿（旧 103 + 新 46）

### Added (Week 4 步骤三 — --compare 双平台对比 + P2 平台拆分)
- `analysis/stats.py`：`compute_yoy_qoq` 三维度（overall / by_city / by_direction）每项新增 `by_platform` 子结构（`{"boss": {...}, "jobui": {...}}`，job_count / avg_salary 分平台统计，同一行循环内并行聚合）；`overall` 顶部新增 `total_unique_jobs`（本季，按 job_name+company_name+city_id 归一 sha1 哈希跨平台去重，仅报告层统计口径、不落库）；无数据平台不出现在 by_platform，报告层缺平台回退 0 条/—
- `analysis/report.py`：`--compare` 模式（argparse CLI）产出双平台对比报告——KPI 卡片分平台独立数据（条数 + 均值月薪）+ 跨平台唯一岗位数卡片；薪资趋势图双平台叠放（每 城市×平台 一条线，BOSS 实线 / JOBUI 虚线，图例「城市·平台」）；报告头注明去重口径与「不落库」。普通模式保持 Week 3 三卡片行为不变，JOBUI 聚合条目 >0 时报告头加一行「含 N 个 JOBUI 聚合条目，请参考 --compare 模式跨平台对比」；compare 模式默认输出 `compare_report.html`
- P3-1 `collectors/jobui_scraper.py`：JOBUI 批次限速改为 `time.sleep(max(batch_delay_sec, random.uniform(5, 10)))`——原实现忽略配置数值；该值现仅作开关（0 = 测试模式不等待）/下限
- P3-2 `importers/jobui_importer.py`：`import_json_to_db` 返回 `(inserted, parsed_total)`，`import_batch` 的 `duplicates = parsed_total - inserted`——解析失败不再混入重复计数
- P3-3 `importers/jobui_importer.py`：单值日薪（"200元/天"/"300/天"/"150.5元/天"）新增正则识别 → `unit='day'`、min/max NULL，不再默认落 month
- P3-4 `analysis/stats.py`：`by_city` 城市 NULL 时桶名由字面 `"city_None"` 改为 `row["city_name"] or (f"city_{city_id}" if city_id else "未知城市")`
- P3-5 `storage/schema.py`：新增 `apply_migration_script`（语句拆分 + 事务包裹 + 逐条 `ALTER TABLE ADD COLUMN` 前 PRAGMA table_info 列检查，列存在跳过）；`apply_pending_migrations` 与 importer 的 `ensure_source_columns` 均改走该入口——半迁移窗口（两列间崩溃：列在版本未记）重跑自愈，不再报 duplicate column；`ensure_source_columns` 早退条件收紧为「列齐且版本已记」
- `scripts/jobui_cdp_raw.py`：清理口径修复——只 `page.close()`，仅自建 context 分支才 `context.close()`（复用用户真实 Chrome 默认 context 时不再误关整个浏览器上下文）
- `tests/`：18 个新测试——平台拆分口径（分平台 job_count/avg_salary、total_unique_jobs sha1 公式锁定、纯 BOSS 库、NULL city_id 样本进「未知城市」桶）、--compare 报告（KPI 双平台卡片 + 唯一岗位数 HTML、趋势图 trace 名/虚实线在 Figure 对象上断言、纯 BOSS 库回退、普通模式三卡片 + 提示行、CLI subprocess）、P3 回归（限速 max 语义、解析失败不入 duplicates、单值日薪参数化、半迁移自愈两条路径）
- 实测：149 + 18 = 167 个测试全绿；`python -m analysis.report --compare data/demo.db` 产出对比报告（纯 BOSS 库回退正常：JOBUI 0 条/—，唯一岗位数 60 = 条数）；Chromium 渲染验证双平台混合库（60 BOSS + 20 JOBUI 同季）KPI 三卡片与双平台叠放趋势图清晰

### Fixed (Week 5 — P3 去重哈希归一)
- `analysis/stats.py` `_norm`：去重哈希归一由「仅 None→空串」改为 `str(v).strip().casefold()`——跨平台同名岗位仅大小写/首尾空白不同（如 BOSS "Python后端工程师" vs JOBUI "python后端工程师"）计为 1 个唯一岗位（修复前计 2，唯一岗位数偏高；保守方向不误并不同岗）。规格测试 `test_unique_jobs_matches_sha1_spec` 同步锁定新公式（大小写/空白变体复算为同 1 个），新增 `test_unique_jobs_case_insensitive` 回归；168 个测试全绿

### Added (Week 5 — cron 自动化)
- 定时任务「招聘数据周报」（aily auto，autoUid `auto_4m43by07vtqa8`）：每周一 9:00 触发，已开闲时执行（凌晨预跑、9:00 投递）。流程：进入持久化项目目录（`~/.aily/workspace/recruitment-data-tracker`，缺失则从公开仓库克隆）→ `git pull origin develop` → `python -m analysis.report --compare` → compare_report.html 上传飞书云盘（命名「招聘数据周报 <日期>.html」）→ 任务评论区汇报本周数据概况（总岗位数 / 双平台岗位数 / 本季均值月薪 / 同比环比）

### Added (Week 6 — 发布管线 + 网站，Phase 1)
- `data/publish/cli.py`（`python -m data.publish.cli`）：发布编排——连 SQLite → 调 `compute_yoy_qoq`（overall / by_city / by_direction 三维度）→ 生成 6 个 JSON 到 `data/publish/v1/`：`manifest.json`（索引；`filters.cities/directions` 从 cities/keywords 表动态读取、不写死 12 个方向；`quarters` 从采集日期聚合）、`summary.json`（KPI + Top 方向）、`salary_trends.json`（方向/城市季度序列 + 本季同比环比，历史季度同比环比字段置 null）、`job_ranking.json`（方向排行 + share + top_cities + 技能 Top 20 词频）、`edu_exp_distribution.json`（学历/经验整体 + 按方向分布）、`data_status.json`（快照历史 + 薪资解析率/JD 率/去重率 + 采集日志）。冻结约束：`core/storage/collectors/importers/analysis` 零改动，仅 import analysis 公开函数；方向归属启发式与 `analysis.stats._attribute_direction` 同口径平行实现（私有函数不可 import）
- `data/publish/format_check.py`（`python -m data.publish.format_check`）：6 个 JSON 的 schema 校验——必填字段存在、数值类型正确（bool 不算数值）、`chart_specs` 非空且含 Plotly `{data, layout}` 结构、`manifest.datasets` 与目录实际文件一一对应（多余 JSON 报错）
- `scripts/quarterly_publish.sh`：季度一键发布——`python -m tracker collect || true`（采集失败不阻断）→ `python -m data.publish.cli` → `git add data/publish/v1/ && git commit && git push origin HEAD:data`（任意本地分支可推送远端 data 分支）
- `chart_specs` 全部经 `fig.to_json()` 产出 Plotly.js 直接可用的 `{type, data, layout}`；方向对比分组柱状 / 城市薪资趋势折线 / 排行水平条形 / 技能高频条形 / 学历饼图 / 经验×方向堆叠柱状
- 空库降级：只建表无岗位时仍输出 6 个合法 JSON（total_jobs=0、薪资/增长 null、manifest.version="empty"），format_check 全过
- `tests/test_publish.py`：8 个测试——summary 字段与类型、salary JSON 与 SQLite 直算口径一致（含方向 qoq/yoy 数值）、manifest 与文件一一对应 + filters 动态读取（新增方向即时反映）、空库降级、format_check 负例（删字段/删文件必报错）、排行顺序/share/yoy、chart_specs Plotly 结构、采集质量口径（解析率 7/8、JD 率 4/8、去重率 0）
- 定时任务「季度采集提醒」（aily auto cron `0 0 9 1 1,4,7,10 *`）：每季度首月 1 号 9:00 飞书提醒执行 `bash scripts/quarterly_publish.sh`
- 全仓 176 个测试全绿（旧 168 + 新 8）

### Planned