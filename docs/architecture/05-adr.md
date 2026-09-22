# 架构决策记录（ADR）

> 版本：v1.1 | 日期：2026-09-23
> v1.1 变更：新增 ADR-015（采集层复用 boss-zhipin-scraper CDP 被动捕获），原 ADR-015 顺延为 ADR-016

---

## ADR-001：模块化单体（Modular Monolith）

### 状态
Accepted（2026-09-22）

### 背景
PRD §6 技术约束要求轻量级实现，无 Web 服务。系统按阶段划分 5 个模块：采集 / 清洗 / 分析 / 报告 / 存储。

### 决策
+ 选择 **模块化单体**：单进程 + 单 SQLite + 模块化目录结构，不引入微服务 / 消息队列 / API 网关。

### 备选方案
| 方案 | 缺点 |
|------|------|
| 微服务（5 服务 + Redis/RabbitMQ）| 季度单次采集无并发需求，基础设施复杂度远超业务价值 |
| 单一脚本（无模块）| Week 3 分析 + Week 4 报告模块会变成"屎山"，无法维护 |
| **模块化单体** ✅ | 单进程部署；模块边界清晰；可后续拆服务 |

### 后果
+ 部署简单：单一进程 + 单一可执行文件
+ 模块边界由目录结构强制（`collectors/` `analysis/` `reporting/` 互不直接 import）
- 若未来需要高频采集，需重新拆服务

---

## ADR-002：SQLite 而非 PostgreSQL

### 状态
Accepted

### 背景
PRD §6.1 明确"存储：SQLite（不上 Postgres/Kafka/Redis）"。一年内数据量 < 30000 行，< 50MB。

### 决策
+ 使用 **SQLite 3.35+**，单文件存储 `data/recruitment.db`，启用 WAL 模式。

### 后果
+ 零运维：单文件、跨平台、备份即拷贝
+ ACID 事务 + 外键约束 + JSON 函数（SQLite 3.38+）
- 单写者：大量并发写入会阻塞；当前场景单采集任务串行提交，完全够用
- 数据备份需自行实现（建议每周 `cp data/recruitment.db backup/`）

---

## ADR-003：Python 3.11+ 而非 3.9/3.10

### 状态
Accepted

### 决策
+ 要求 **Python 3.11+**，利用新特性：
  - `tomllib` 内置（解析 `pyproject.toml`）
  - `Self` 类型注解（dataclass 链式）
  - `ExceptionGroup`（多异常聚合）
  - 性能提升 10-60%（CPython 3.11）

### 后果
+ 现代 Python 写法，无需手动 typing workaround
- 截至 2026-09，3.11+ 已普遍可用，部署环境无障碍

---

## ADR-004：Plotly 而非 Matplotlib/ECharts

### 状态
Accepted

### 决策
+ 图表使用 **Plotly**，HTML 嵌入模式 `include_plotlyjs="inline"`。

### 备选方案
| 方案 | 缺点 |
|------|------|
| Matplotlib | 输出 PNG/SVG，无法交互；折线图难以 hover 查数据 |
| ECharts | JS 库，需 CDN 加载或内嵌，体积大（>1MB） |
| **Plotly** ✅ | 单 HTML 嵌入约 3-5MB，交互良好，Python API 直观 |

### 后果
+ 单 HTML 报告无外部依赖（Plotly.js 内嵌）
+ 移动端可交互
- 单文件体积 3-5MB，移动端首次加载稍慢（PRD §5 章节 4-5 图表为可接受）

---

## ADR-005：cron 由 aily-cli auto 驱动

### 状态
Accepted

### 决策
+ 定时任务由 **aily-cli auto cron** 驱动，不引入 APScheduler / Celery beat。

### Cron 表达式
| 任务 | 表达式 | 时间 |
|------|--------|------|
| 季度采集 | `0 2 1 1,4,7,10 *` | 1/4/7/10 月 1 日 02:00 |
| 季度报告 | `0 3 2 1,4,7,10 *` | 1/4/7/10 月 2 日 03:00（采集后 25 小时） |
| 每周健康检查 | `0 9 * * 1` | 每周一 09:00 |

### 后果
+ 平台统一管理 cron，无需进程守护
+ 健康检查可触发飞书通知（PRD §10）
- 若 aily-cli auto 不可用，系统整体降级（需记录运维降级方案）

---

## ADR-006：原生 sqlite3 而非 SQLAlchemy

### 状态
Accepted

### 决策
+ 使用 Python 标准库 **`sqlite3`**，手写 DAO 层，不引入 ORM。

### 后果
+ 4 张表 → ~10 个 SQL 语句，无 ORM 学习成本
+ SQL 透明，便于调试
- 无自动 schema migration（手写 `migrations/0001_initial.sql` 等，部署脚本顺序执行）

---

## ADR-007：Jinja2 报告模板

### 状态
Accepted

### 决策
+ HTML 报告使用 **Jinja2** 模板（`reporting/templates/report.html.j2`），数据从 dataclass 列表传入。

### 后果
+ 模板与逻辑分离，HTML 设计师可独立调整样式
+ Jinja2 沙箱模式默认安全（无 XSS 风险）

---

## ADR-008：Cookie 失效通知用户而非自动重试

### 状态
Accepted

### 背景
PRD §10 "Cookie 失效 → 每周健康检查任务监控，失效时发飞书消息提醒用户重新登录"。
PRD §6 反爬策略原文写"cookie 失效自动重试 3 次"——但同一失效 cookie 重试 3 次仍为空，
**重试无效**。PRD 附录 B.5 已裁决。

### 决策
+ Cookie 失效 → 触发 `AccountBannedError`（BOSS code=32）或健康检查检测 → **飞书消息通知用户**，不自动重试。

### 后果
+ 行为可预期：失效 → 等用户介入
+ 避免无效重试浪费请求配额
- 用户需要介入（但每次仅需登录一次，30 秒操作）

---

## ADR-009：UA 池 + 真实 Chrome UA

### 状态
Accepted

### 决策
+ UA 池预置 3 个真实 Chrome / Safari / Firefox UA，每次请求随机选择。

### 后果
+ 规避简单 UA 黑名单
- BOSS 真实风控远不止 UA 检测（CDP 注入 + Fetch 域拦截才是核心，详见 §Week 1 预研）

---

## ADR-010：前两季度无同比 — 报告明确标注

### 状态
Accepted

### 背景
PRD §10 "前两季度无同比数据 → 报告中明确标注时间序列建立中"。

### 决策
+ 同比字段缺失时，UI 显示"建立中"，**不伪造数据**。

### 后果
+ 数据真实性优先
- 前两季度报告的"市场总览"章节同比列为空

---

## ADR-011：小批次 + 长延迟的反爬节奏

### 状态
Accepted

### 背景
Week 1 预研暴露 BOSS 实测风控：**约 3 次快速 API 请求即触发 code=32 账号临时封禁**。
PRD §6 的 12-22 秒随机延迟是下限，实际需要更保守。

### 决策
+ **生产配置**：单关键词单城 ≤2 页/批次，批次间隔 ≥5 分钟，单日单账号 ≤5 个批次。

### 后果
+ 单账号单次采集可完成 35 关键词 × 5 城 ÷ 5 批次 = 35 次会话 / 季度
+ 季度采集总耗时约 3-5 天（每次会话 30 分钟），可接受
- Week 2 实施时需用户配合多次手动登录取 wt2

---

## ADR-012：列表页 + 详情页两阶段采集

### 状态
Accepted

### 背景
Week 1 预研发现 BOSS 列表 API 不返回 jd_fulltext（60/60 样本 jd_fulltext 为空），
JD 全文需点进详情页。同一会话内两阶段可避免重复抓列表。

### 决策
+ **阶段 1**：列表页抓取 13 项核心字段（含 encryptJobId + salary）
+ **阶段 2**：对 `jd_fulltext IS NULL` 的记录，详情页回填 JD 全文

### 后果
+ `job_snapshot.jd_fulltext` 允许为 NULL（schema 已设）
+ Week 2 实施时同会话内顺序执行两阶段
- 单关键词单城抓取耗时翻倍；为缓解，仅回填空值记录，不重复抓列表

---

## ADR-013：先 BOSS 单源，职友集 Week 2 同步预研

### 状态
Accepted

### 决策
+ Week 1 已跑通 BOSS 预研。Week 2 同步预研职友集接入方式与字段映射；
  Week 2-3 实现职友集采集器。

### 后果
+ 主源稳定后再接入辅源，避免 Week 2 阻塞
- 报告中"数据来源"会标注"主源 BOSS + 辅源 职友集"两个数据点

---

## ADR-014：报告 cron 推迟到季度首日后 25 小时

### 状态
Accepted

### 背景
PRD §6 cron 表达式 `0 3 2 1,4,7,10 *`（采集后 25 小时）。PRD 附录 B.4 已裁决。

### 决策
+ 报告 cron 推迟到季度首日（采集日）后 25 小时，确保采集完成。

### 后果
+ 报告生成的 snapshot_date 完整（避免部分城市未完成）
- 报告生成时机晚 1 天；个人研究场景可接受

---

## ADR-015：采集层复用 boss-zhipin-scraper CDP 被动捕获

### 状态
Accepted（2026-09-23）

### 背景
Week 1 预研尝试直调 BOSS 搜索 API 进行自研 scraper，在实测中暴露了严重风控问题：
- **约 3 次快速 API 请求即触发 code=32 账号临时封禁**（PreResearch 实测数据）
- 封禁期间数小时不可用，需等待自动解除
- 直调 API 的反爬对抗成本极高：需要逆向 BOSS 请求签名、绕过 Fetch 域拦截（warlockdata 清页）、维持 CDP 登录态

与此同时，开源项目 `eatmoreduck/boss-zhipin-scraper` 已在 PreResearch 中跑通：
- Chrome CDP 被动捕获 — 不直接调 API，而是监听浏览器网络请求
- ≥60 条真实数据（含明文薪资 `salaryDesc`、完整字段覆盖 PRD §3.5）
- 60/60 encryptJobId 唯一，52/60 解析出 min/max K

### 决策
+ **采集层架构从"自研 API scraper"切换为"boss-zhipin-scraper CLI wrapper + 数据导入器"**。
+ boss-zhipin-scraper 作为**外部 CLI 依赖**（通过 `subprocess.Popen` 调用），不是我们的代码。
+ 我们的代码职责变为：① 组装 CLI 参数 ② 调 subprocess ③ 解析 JSON 输出 ④ 清洗入库。

### 备选方案
| 方案 | 优点 | 缺点 | 裁决 |
|------|------|------|------|
| **自研 API scraper** | 完全可控、零外部依赖 | PreResearch 实测 3 次 API 请求即封号；反爬逆向成本极高（签名逆向、CDP 域拦截）；W2 大概率无法交付 ≥900 条目标 | ❌ 风险过高 |
| 阿里云市场付费 API | 稳定可靠、有 SLA | 约 50 元/次，季度成本 50×35×5 = 多轮渐进难以估算；预算需用户批准；无"免费验证"通道 | ❌ 备选保留，scraper 不可行时启用 |
| **boss-zhipin-scraper CLI wrapper** ✅ | PreResearch 已验证可行；CDP 被动捕获绕过 API 风控；开源社区持续维护 | 依赖本机 Chrome + Chrome Profile 登录态；上游停止维护风险 | ✅ 采纳 |

### 后果
+ **正面**：
  - 核心风控问题由 boss-zhipin-scraper 内部消化，我们无需处理反爬
  - CDP 被动捕获 = 跟真实浏览器行为一致，封号概率大幅降低
  - 接口简单：`boss-zhipin-scraper collect --keyword X --city Y` → JSON → import

- **负面**：
  - 部署增加外部依赖（`pip install boss-zhipin-scraper` + 本机 Chrome）
  - 上游停止维护风险 → 已决策：锁定当前 commit + fork 到个人仓库备灾
  - 采集瓶颈从网络 I/O 变为 Chrome CDP（每页约 5-8s，可接受）

### 架构影响
- **模块 `collectors/` 拆分**：`collectors/boss_scraper.py`（CLI wrapper）+ `importers/boss_importer.py`（JSON→SQLite UPSERT）
- **移除模块**：`collectors/base.py`（ABC 基类）、`utils/anti_crawl.py`（反爬工具）— 反爬逻辑由 scraper 内部管理
- **新增异常**：`ScraperError` / `ScraperTimeoutError` / `SchemaIncompatibleError`
- **依赖变更**：`playwright` 从直接依赖移除，`boss-zhipin-scraper` 作为外部 CLI 新增
- **不变**：ERD（4 表 schema）、`core/` 清洗/模型层、`analysis/` 分析层、`reporting/` 报告层

### PreResearch 封号证据
- **实测**：同一 session 内第 3 次 API 搜索请求 → HTTP code=32 `"账户存在异常行为，已暂时被禁止"`
- **影响**：封禁期间本机完全无法调 BOSS 搜索 API；登录态不受影响（手机 App 正常）
- **恢复**：数小时后自动解除，重新取 wt2 即可

---

## ADR-016：架构设计文档优先于代码

### 状态
Accepted

### 决策
+ Week 1 **先文档后代码**：架构 / ERD / 接口 / 目录 / ADR 全部就位 → 研发照文档写代码不追问。

### 后果
+ 减少 Week 2 的实现期沟通，文档即契约
+ 代码质检官（若引入）可对照 ADR 审查实现

---

## 附：决策追溯矩阵

| ADR | 解决 PRD 缺口 / 决策 |
|-----|---------------------|
| 001 | §6 技术约束 — 单体架构 |
| 002 | §6 存储 — SQLite 选定 |
| 003 | §6 语言版本 — Python 3.11+ |
| 004 | §5 输出物 — 交互图表 |
| 005 | §6 定时调度 — 3 个 cron |
| 006 | §6 简单约束 — 原生 sqlite3 |
| 007 | §5 输出物 — HTML 模板 |
| 008 | B.5 — Cookie 失效通知用户 |
| 009 | §6 反爬策略 — UA 池 |
| 010 | §10 — 前两季度无同比标注 |
| 011 | W1 预研风险 — 小批次长延迟 |
| 012 | W1 预研 — JD 两阶段回填 |
| 013 | W1 预研范围 — 职友集同步预研 |
| 014 | B.4 — 报告 cron 推迟 25 小时 |
| 015 | W1 预研 — 采集层复用 boss-zhipin-scraper CDP 被动捕获 vs 自研 API scraper |
| 016 | W1 启动 — 文档先于代码 |

所有 ADR 严格对应 PRD 已有决策或预研已暴露风险，**未引入未经裁决的新约束**。