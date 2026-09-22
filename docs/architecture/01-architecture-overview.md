# 招聘数据采集与分析系统 — 架构概览

> 版本：v1.1 | 日期：2026-09-23 | 作者：软件架构师
> v1.1 变更：采集层从"自研 API scraper"切换为"boss-zhipin-scraper CLI wrapper + 数据导入器"（ADR-015）
> 对应 PRD：[招聘数据采集与分析系统 PRD](https://larkcommunity.feishu.cn/docx/SZT6dhjTxor4XKxP5JHczQW0nD2)

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **模块化单体（Modular Monolith）** | 部署为一个进程，源码按领域拆分为高内聚模块；不引入微服务、消息队列、分布式组件 |
| **简单优先（YAGNI）** | 每季度一次采集，不做实时/高频/流式；不引入数据库连接池、ORM、缓存层 |
| **可恢复（Resilient）** | 每页采集完立即写入 SQLite，Ctrl+C 中断不丢数据；job_id + snapshot_date 复合主键去重 |
| **可观测（Observable）** | 所有关键路径打结构化日志（JSON 行）；健康检查 cron 每周报告数据状态 |
| **可演进（Evolvable）** | 模块接口通过 dataclass 契约隔离；采集器通过 ABC 抽象基类定义，新增平台只需实现接口 |

---

## 2. 模块划分

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI 入口层                            │
│   cli/collect.py    cli/report.py    cli/health.py           │
└──────────┬──────────────────┬──────────────────┬────────────┘
           │                  │                  │
┌──────────▼────────┐ ┌──────▼──────┐ ┌────────▼──────────┐
│  collectors/      │ │  analysis/  │ │  reporting/        │
│  - boss_scraper.py│ │  - stats.py │ │  - renderer.py     │
│    (CLI wrapper)  │ │  - wordfreq │ │  - templates/      │
│  - jobui.py       │ │  - salary.py│ │  - charts.py       │
│                   │ │             │ │                    │
├───────────────────┤ │             │ │                    │
│  importers/       │ │             │ │                    │
│  - boss_importer  │ │             │ │                    │
│    (JSON→UPSERT)  │ │             │ │                    │
└──────────┬────────┘ └──────┬──────┘ └────────┬──────────┘
           │                 │                  │
┌──────────▼─────────────────▼──────────────────▼────────────┐
│                     storage/                                 │
│  schema.py │ dao.py │ migrations/ │ connection.py            │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                     core/                                    │
│  models.py (dataclass) │ cleansing.py │ dedup.py │ config.py│
└─────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                     utils/                                   │
│  logger.py │ http.py │ retry.py                              │
└─────────────────────────────────────────────────────────────┘
```

### 模块职责

| 模块 | 职责 | 依赖 |
|------|------|------|
| `cli/` | 命令行入口，组装参数 → 调用下层模块 | 所有下层模块 |
| `collectors/` | boss-zhipin-scraper CLI wrapper（subprocess 封装），调用外部 CLI → 产出 `data/raw/*.json` | `core.models`, `core.config` |
| `importers/` | 读取 scraper 产出的 JSON → 清洗 + 去重 → SQLite UPSERT | `storage.dao`, `core.models`, `core.cleansing` |
| `analysis/` | 薪资标准化、同比环比计算、jieba 词频统计 | `storage.dao`, `core.models` |
| `reporting/` | Jinja2 渲染 HTML 单文件 + Plotly 图表嵌入 | `storage.dao`, `analysis` |
| `storage/` | SQLite DDL / DML / 迁移 / 连接管理 | `core.models` |
| `core/` | 共享数据模型（dataclass）、清洗、去重、配置加载 | 无 |
| `utils/` | 日志、HTTP 客户端、重试 | `core.config` |

---

## 3. 端到端数据流

```
[boss-zhipin-scraper CLI]           ← 外部依赖，本机 Chrome CDP 被动捕获
       │  subprocess.Popen
       ▼
[collectors/boss_scraper.py] ──调用──→  data/raw/<city>_<keyword>_<date>.json
       │
       ▼
[importers/boss_importer.py] ──解析──→  JobRecord（扁平 dict）
       │
       ▼
[core/cleansing.py]         ──清洗──→  cleaned job (城市名统一、学历归一)
       │
       ▼
[core/dedup.py]             ──去重──→  按 (encrypt_job_id, snapshot_date) 复合键
       │
       ▼
[storage/dao.py]            ──入库──→  SQLite job_snapshot 表（UPSERT 语义）
       │
       ▼  (Week 3)
[analysis/stats.py]         ──聚合──→  12 方向 × 薪资/数量 × 同比/环比
[analysis/wordfreq.py]      ──分词──→  Top 20 技能词频
       │
       ▼  (Week 4)
[reporting/renderer.py]     ──渲染──→  HTML 单文件报告（6 章节 + Plotly）
```

### 数据写入保障

- **逐页提交**：每页 15 条采集完 → `conn.commit()`，中断不丢已写入数据
- **去重幂等**：`INSERT OR IGNORE INTO job_snapshot ...`，`(job_id, snapshot_date)` UNIQUE 约束
- **dry-run 模式**：`--dry-run` flag，全流程走通但不写库，用于首次部署验证

---

## 4. 关键依赖

| 依赖 | 用途 | 选型理由 |
|------|------|------|
| `boss-zhipin-scraper` (外部 CLI) | BOSS 直聘 CDP 被动捕获 | eatmoreduck/boss-zhipin-scraper，本机 Chrome DevTools Protocol，已完成 PreResearch 验证（≥60 条） |
| `jieba` | JD 中文分词 | 轻量纯 Python，无外部依赖，足够胜任招聘 JD 分词 |
| `jinja2` | HTML 报告模板渲染 | Python 生态最成熟的模板引擎 |
| `plotly` | 交互式图表（折线图 / 柱状图） | 单 HTML 嵌入，无需服务器 |
| `pyyaml` | 配置文件解析 | 简单配置（关键词、城市、cron）用 YAML 最直观 |
| `tenacity` | 重试逻辑 | 比手写 while 循环更可读 |
| `click` | CLI 命令行框架 | 轻量，比 argparse 更友好 |

**注**：`playwright` 不再列为直接依赖——由 boss-zhipin-scraper 内部管理 CDP 连接。

### 明确不引入

| 不引入 | 原因 |
|--------|------|
| SQLAlchemy / Peewee ORM | 4 张表，原生 sqlite3 更简单 |
| Flask / FastAPI / Django | 不需要 Web 服务 |
| Celery / APScheduler | cron 由 aily-cli auto 驱动 |
| Redis / PostgreSQL | SQLite 单文件，零运维 |
| Scrapy | 太重，每季度一次的采集不需要爬虫框架 |
| pydantic | dataclass 足够，不加额外类型校验层 |

---

## 5. 非功能需求（NFR）落点

| NFR | 设计方案 | 验证方式 |
|-----|---------|---------|
| **可靠性** | scraper 子进程超时 300s + JSON 落盘作为中间态，导入层 UPSERT 幂等 | 中断后续抓测试（Week 2） |
| **可维护性** | 模块化单体 + CLI wrapper 隔离外部依赖 + dataclass 契约 | 更换采集源只需实现新 importer |
| **性能** | 采集瓶颈在 Chrome CDP（每页约 5-8s），多城市多关键词走多轮渐进；分析阶段 pandas 全量加载 4 表到内存（单季度 <5000 条，<5MB） | 采集耗时不敏感；分析 <30 秒 |
| **安全性** | Cookie 由 boss-zhipin-scraper 在本机 Chrome Profile 管理，不提交 Git | .gitignore 排除 /config/local/ 和 `data/raw/` |
| **可观测性** | `utils/logger.py` 输出 JSON 行格式；scraper stdout/stderr 捕获落日志；`cli/health.py` 输出数据完整性报告 | 每周健康检查 cron 推送飞书 |

---

## 6. 风险与已锁决策

| 风险 | 已锁决策 | ADR |
|------|---------|-----|
| BOSS 反爬升级（账号封禁） | ≤3 页/关键词/城市，多轮渐进采集，单日单账号 ≤5 批次 | ADR-011 |
| boss-zhipin-scraper 上游停止维护 | 当前 commit 锁定 + fork 到个人仓库备灾 | ADR-015 |
| Cookie / CDP 登录态失效 | 健康检查检测 → 飞书通知用户重新登录，不自动重试 | ADR-008 |
| 前两季度无同比 | 报告中明确标注"时间序列建立中"，不伪造数据 | ADR-010 |
| 职友集采集方式未预研 | Week 2 同步预研，先跑通 BOSS 主源 | ADR-013 |
| 日薪制岗位（实习/兼职） | min/max 置空 + salary_raw 保留原文；ERD `salary_unit` 字段标注 | - |

---

## 7. 与 PRD 的追溯矩阵

| PRD 需求 | 架构落点 |
|---------|---------|
| §3.1 12 方向关键词 | `config/settings.yaml` → `keywords` 表预填 |
| §3.2 5 城 | `cities` 表预填 5 行，采集器遍历 |
| §3.3 季度采集 | `snapshots` 表记录每次采集元信息 |
| §3.5 13 项字段 | `job_snapshot` 表 18 列（含扩展字段 `year_multiplier`, `salary_unit`） |
| §4.1 同比/环比 | `analysis/stats.py` 基于 `snapshot_date` 季度归属计算 |
| §4.2 薪资标准化 | `core/salary.py` parse_salary() |
| §5 输出物 | `reporting/renderer.py` + `templates/report.html.j2` |
| §6 技术栈 | Python 3.11+ / SQLite / requests / playwright / jieba / plotly / jinja2 |
| §7 MVP 边界 | 无 Web 界面、无多平台、无用户系统 |
| §9 合规 | 反爬延迟 12-22s + UA 池 + 仅个人研究 |