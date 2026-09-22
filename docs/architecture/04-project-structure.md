# 项目目录结构与配置模板

> 版本：v1.0 | 日期：2026-09-22 | 对应架构概览 §2

---

## 1. 完整目录树

```
recruitment-data-tracker/
├── README.md                      # 项目说明（模板见 §6）
├── CHANGELOG.md                   # 变更日志（模板见 §7）
├── LICENSE                        # MIT
├── .gitignore                     # 见 §4
├── .gitattributes                 # Git 属性（行尾、Diff 驱动）
├── pyproject.toml                 # 项目元数据 + 依赖（见 §3）
├── requirements.txt               # 锁定版本（pip freeze 生成）
├── config/
│   ├── settings.yaml              # 关键词、城市、cron（提交）
│   └── local/
│       └── cookies.json           # 本地 Cookie（.gitignore 排除）
├── src/
│   └── tracker/                   # 主包
│       ├── __init__.py
│       ├── __main__.py            # python -m tracker 入口
│       │
│       ├── core/                  # 核心共享
│       │   ├── __init__.py
│       │   ├── models.py          # dataclass（03 §1）
│       │   ├── salary.py          # 薪资解析（03 §2）
│       │   ├── cleansing.py       # 数据清洗（03 §3）
│       │   ├── dedup.py           # 去重（03 §3）
│       │   ├── config.py          # 配置加载
│       │   └── exceptions.py      # 异常体系（03 §11）
│       │
│       ├── storage/               # 存储层
│       │   ├── __init__.py
│       │   ├── connection.py      # SQLite 连接（03 §4）
│       │   ├── schema.py          # 建表脚本
│       │   ├── dao.py             # 数据访问对象（03 §5）
│       │   └── migrations/
│       │       └── 0001_initial.sql  # 完整 DDL（02 §2）
│       │
│       ├── collectors/            # 数据采集
│       │   ├── __init__.py
│       │   ├── base.py            # 采集器基类（03 §6）
│       │   ├── boss.py            # BOSS 实现（03 §7）
│       │   └── jobui.py           # 职友集实现（W2 预研）
│       │
│       ├── analysis/              # 数据分析
│       │   ├── __init__.py
│       │   ├── stats.py            # 同比/环比（03 §8）
│       │   └── wordfreq.py        # JD 分词（03 §9）
│       │
│       ├── reporting/             # 报告生成
│       │   ├── __init__.py
│       │   ├── renderer.py        # HTML 渲染（03 §10）
│       │   ├── charts.py          # Plotly 图表封装
│       │   └── templates/
│       │       └── report.html.j2 # Jinja2 模板
│       │
│       ├── cli/                   # 命令行入口
│       │   ├── __init__.py
│       │   ├── collect.py         # python -m tracker collect
│       │   ├── report.py          # python -m tracker report
│       │   ├── health.py          # python -m tracker health
│       │   └── migrate.py         # python -m tracker migrate
│       │
│       └── utils/                 # 工具
│           ├── __init__.py
│           ├── anti_crawl.py      # 延迟、UA 池
│           ├── logger.py          # 结构化日志
│           ├── http.py            # HTTP 客户端封装
│           └── retry.py           # tenacity 包装
│
├── tests/                         # 单元测试
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_salary.py             # 薪资解析
│   ├── test_cleansing.py          # 数据清洗
│   ├── test_dedup.py              # 去重
│   ├── test_stats.py              # 同比/环比
│   └── test_quarter.py            # 季度归属
│
├── scripts/                       # 运维脚本
│   ├── init_db.sh                 # 一键建库
│   ├── deploy_cron.sh             # 注册 cron（W5）
│   └── health_check.sh            # 健康检查（W5）
│
├── data/                          # 数据目录（.gitignore 排除 data/）
│   ├── recruitment.db             # SQLite 数据库
│   ├── reports/                   # 生成的 HTML 报告
│   └── logs/                      # 运行日志
│
└── docs/                          # 文档
    ├── PRD.md                     # PRD 副本
    ├── architecture/
    │   ├── 01-architecture-overview.md
    │   ├── 02-database-erd.md
    │   ├── 03-module-interfaces.md
    │   ├── 04-project-structure.md    # 本文件
    │   └── 05-adr.md
    └── ops/
        ├── deployment.md          # 部署手册（W5）
        └── troubleshooting.md     # 故障排查（W5）
```

---

## 2. W1 周内必建文件清单（约 1100 行代码量）

### 核心可立即开工（Week 1 收口前必须完成）

- [ ] `pyproject.toml`（依赖声明 + 入口点）
- [ ] `.gitignore`（见 §4）
- [ ] `src/tracker/__init__.py`
- [ ] `src/tracker/core/models.py`（完整 dataclass）
- [ ] `src/tracker/core/exceptions.py`（异常体系）
- [ ] `src/tracker/core/salary.py`（薪资解析 + 测试）
- [ ] `src/tracker/core/cleansing.py`（清洗 + 测试）
- [ ] `src/tracker/core/dedup.py`（去重 + 测试）
- [ ] `src/tracker/core/config.py`（YAML 加载）
- [ ] `src/tracker/storage/connection.py`
- [ ] `src/tracker/storage/schema.py`
- [ ] `src/tracker/storage/migrations/0001_initial.sql`
- [ ] `src/tracker/storage/dao.py`
- [ ] `src/tracker/collectors/base.py`（ABC 基类）
- [ ] `src/tracker/utils/anti_crawl.py`（延迟 + UA 池）
- [ ] `src/tracker/utils/logger.py`
- [ ] `src/tracker/utils/http.py`
- [ ] `src/tracker/utils/retry.py`
- [ ] `src/tracker/cli/migrate.py`（建库命令）
- [ ] `tests/test_salary.py`
- [ ] `tests/test_cleansing.py`
- [ ] `tests/test_dedup.py`
- [ ] `tests/test_quarter.py`
- [ ] `README.md`（见 §6 模板）
- [ ] `CHANGELOG.md`（见 §7 模板）

### Week 2+ 才需要的（仅占位签名即可）

- `src/tracker/collectors/boss.py`（仅 raise NotImplementedError）
- `src/tracker/collectors/jobui.py`（仅占位）
- `src/tracker/analysis/stats.py`（仅占位签名）
- `src/tracker/analysis/wordfreq.py`（仅占位签名）
- `src/tracker/reporting/renderer.py`（仅占位签名）
- `src/tracker/cli/collect.py` / `cli/report.py` / `cli/health.py`

---

## 3. `pyproject.toml` 模板

```toml
[project]
name = "recruitment-data-tracker"
version = "0.1.0"
description = "招聘数据采集与分析系统：BOSS + 职友集季度自动采集，HTML 报告生成"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "iskungfu" }]

dependencies = [
    "requests>=2.31",
    "playwright>=1.40",
    "jieba>=0.42",
    "jinja2>=3.1",
    "plotly>=5.18",
    "pyyaml>=6.0",
    "tenacity>=8.2",
    "click>=8.1",
    "pandas>=2.1",       # 仅分析阶段使用
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
    "ruff>=0.1",
]

[project.scripts]
tracker = "tracker.__main__:main"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## 4. `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.env

# 工具
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# 数据与运行时
data/
!data/.gitkeep
logs/

# 配置文件 — Cookie 含敏感信息
config/local/

# 编辑器
.vscode/
.idea/
*.swp
.DS_Store

# 浏览器自动化
ms-playwright/
```

---

## 5. `config/settings.yaml`

```yaml
# 招聘数据采集与分析系统 — 主配置
# 提交至 Git；本地敏感信息（Cookie）放 config/local/

system:
  snapshot_dates: ["01-01", "04-01", "07-01", "10-01"]  # 季度采集日
  max_pages_per_keyword_city: 10                          # 单关键词单城 ≤10 页
  request_delay_min_sec: 12                                # 随机延迟下限
  request_delay_max_sec: 22                                # 随机延迟上限

cities:
  active: [北京, 上海, 深圳, 杭州, 成都]

# 关键词维护在 DB keywords 表；此处仅作 plan 备份
# keywords:
#   - direction: 前端
#     keyword: Vue
#     ...

anti_crawl:
  user_agents:                                              # UA 池
    - "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    - "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"
    - "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36"

reporting:
  output_dir: "data/reports"
  top_n_skills: 20

logging:
  level: INFO
  format: json
  dir: "data/logs"
  rotation: weekly
```

---

## 6. `README.md` 模板

```markdown
# Recruitment Data Tracker

招聘数据采集与分析系统。每季度自动采集 BOSS 直聘 + 职友集招聘数据，
输出计算机类（前端 / 后端 / 算法 / AI 应用 / 数据 / 测试）和
半导体类（IC 设计 / IC 验证 / 工艺 / 封测 / 设备 / 材料）共 12 个方向的
薪资趋势 / 岗位数量 / 技术要求演变分析报告。

仅个人研究使用。

## 功能特性

- 🗓️ 季度自动采集（1/4/7/10 月第 1 天）
- 🏙️ 5 城固定：北京 / 上海 / 深圳 / 杭州 / 成都
- 💾 SQLite 单文件，零运维
- 📊 HTML 单文件报告（含 Plotly 交互图表）
- 🔄 中断安全：每页采集完立即入库
- 📈 同比 + 环比分析
- 🧠 jieba JD 全文 / 技能词频 Top 20

## 快速开始

```bash
# 1. 安装依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. 初始化数据库
python -m tracker migrate

# 3. 配置 BOSS Cookie（手动从浏览器获取 wt2）
mkdir -p config/local
echo '{"wt2": "your_wt2_here"}' > config/local/cookies.json

# 4. 手动采集一次（测试）
python -m tracker collect --dry-run --keyword 后端 --city 北京 --max-pages 2

# 5. 生成季度报告
python -m tracker report --quarter 2026Q3
```

## 阶段规划

| Week | 目标 | 状态 |
|------|------|------|
| 1 | 架构设计 + 爬虫预研 | ✅ |
| 2 | BOSS 爬虫 MVP（≥900 条） | ⏳ |
| 3 | 数据分析 + 同比环比 | ⏳ |
| 4 | HTML 报告生成器 | ⏳ |
| 5 | 自动化部署 | ⏳ |

## 文档

- [PRD](docs/PRD.md)
- [架构概览](docs/architecture/01-architecture-overview.md)
- [数据库 ERD](docs/architecture/02-database-erd.md)
- [模块接口](docs/architecture/03-module-interfaces.md)
- [目录结构](docs/architecture/04-project-structure.md)
- [ADR](docs/architecture/05-adr.md)

## 合规

- 数据仅个人研究，不对外公开
- 严格按季度采集，单请求间隔 12-22 秒
- 遇反爬失败立即降级，不硬刚

## License

MIT
```

---

## 7. `CHANGELOG.md` 模板

```markdown
# Changelog

所有对本项目的重要变更都会记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### Added
- (待办)

## [0.1.0] - 2026-09-22

### Week 1 — 架构设计 + 爬虫预研

#### Added
- 架构文档 5 份（架构概览 / ERD / 接口 / 目录 / ADR）
- 数据库 Schema v1（4 张表 + schema_version）
- 共享数据模型（dataclass） + 异常体系
- 薪资解析、城市归一、学历归一、数据去重核心算法
- 采集器抽象基类（ABC）
- 反爬工具（12-22s 随机延迟 + UA 池）
- 配置加载（YAML）+ 结构化日志
- 数据库连接 / 迁移 / DAO
- CLI 入口 `tracker`（建库命令可用，采集 / 报告 / 健康检查占位）
- 单元测试骨架 + 5 个核心测试通过
- 一键部署脚本框架（init_db.sh / deploy_cron.sh / health_check.sh）

#### Known Limitations
- BOSS Cookie 城市编码 `boss_city_code` / `jobui_slug` 用 `TODO_W2_*` 占位（W2 实测替换）
- `collectors/boss.py` / `jobui.py` 仅占位签名（W2 实现）
- `cli/collect.py` / `report.py` / `health.py` 仅占位签名（W2 / W4 / W5）
- 单关键词单城实际封禁阈值约 3 次快速请求（W1 预研暴露，W2 改小批次 + 长延迟）
```

---

## 8. 一键建库脚本（`scripts/init_db.sh`）

```bash
#!/usr/bin/env bash
set -euo pipefail

# 初始化数据库 + 应用迁移 + 灌入种子数据
cd "$(dirname "$0")/.."

mkdir -p data
touch data/.gitkeep

source .venv/bin/activate
python -m tracker migrate

echo "✅ 数据库初始化完成：data/recruitment.db"
echo "📊 种子数据：5 城 + 34 关键词"
```

---

## 9. 提交策略

### Git 分支规范

| 分支 | 用途 |
|------|------|
| `main` | 稳定可运行版本，每个 Week 收口后 merge 一次 |
| `develop` | 日常开发主分支，所有 PR merge 到这里 |
| `feature/*` | 单个功能开发（如 `feature/week2-boss-collector`） |
| `fix/*` | Bug 修复 |
| `docs/*` | 纯文档变更 |

### 提交信息规范（Conventional Commits）

```
feat(collectors): 实现 BOSS 直聘列表页解析
fix(salary): 修正 "100-150/时" 时薪解析失败
docs(adr): 实现 ADR-005 调度方案（cron vs APScheduler）
chore(deps): 升级 plotly 到 5.19
test(stats): 添加同比环比边界测试
```

### Week 1 首推

首次 push 包含：
- 完整目录结构（仅 W1 周内必建文件 + 占位签名）
- 4 张表 schema + 种子数据
- 5 份架构文档
- 5 个核心测试通过
- README / CHANGELOG / .gitignore / pyproject.toml

后续每个 Week 收口后 PR 合并到 `develop`，最后 merge 到 `main` 打 tag。