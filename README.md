# Recruitment Data Tracker

招聘数据采集与分析系统 — 面向计算机 / 半导体行业岗位市场的个人研究工具。

## 目标

- 从 BOSS 直聘采集北京、上海、深圳、杭州、成都 5 城的岗位数据
- 按季度对薪资（min / max / year_multiplier）、经验要求、学历要求做同比分析
- 输出 HTML 报告，含 Plotly 图表 + jieba 词云

## 状态

| 阶段 | 状态 |
|------|------|
| Week 1 — 架构 + 预研 | ✅ 完成（5 份架构文档 + BOSS 爬虫预研 60 条样本） |
| Week 2 — 采集管线（v1.1 CDP 方案） | ✅ 完成（scraper CLI wrapper + JSON importer + schema/迁移 + 89 个测试） |
| Week 3 — 数据分析 | 待启动 |
| Week 4 — 跨平台 + 报告 | 待启动 |
| Week 5 — 自动化 | 待启动 |

## 技术栈

- Python 3.11+ / SQLite（WAL，原生 sqlite3，零外部 DB 依赖）
- 采集：外部 CLI [boss-zhipin-scraper](https://github.com/eatmoreduck/boss-zhipin-scraper)（Chrome CDP 被动捕获，ADR-015），本仓库只做 CLI wrapper + JSON importer
- 分析 / 报告：Plotly / jieba（Week 3-4）

## 快速开始

```bash
git clone https://github.com/iskungfu/recruitment-data-tracker.git
cd recruitment-data-tracker
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 1. 初始化数据库（4 表 + schema_version + 5 城 / 35 关键词种子）
python -m storage.schema

# 2. 安装外部采集 CLI（ADR-015：复用其 Chrome CDP 被动捕获，不自建请求）
git clone https://github.com/eatmoreduck/boss-zhipin-scraper
pip install -r boss-zhipin-scraper/requirements.txt
# 首次需登录一次（隔离 profile，不影响日常 Chrome）：
python3 boss-zhipin-scraper/scripts/boss_cdp_raw.py --setup-chrome

# 3. 在 config/settings.yaml 配置 scraper.entry 指向 scripts/boss_cdp_raw.py
#    （或设置环境变量 BOSS_SCRAPER_ENTRY）

# 4. 单城单关键词采集 + 入库
python - <<'PY'
from datetime import date
from pathlib import Path
from core.config import load_settings
from collectors.boss_scraper import ScraperConfig, run_scraper
from importers.boss_importer import import_json_to_db
from storage.connection import get_connection

settings = load_settings()
json_path = run_scraper(ScraperConfig(keyword="后端", city="北京", max_pages=3), settings)
conn = get_connection(settings.db_path)
print("新插入:", import_json_to_db(json_path, city_id=1, snapshot_date=date.today(), conn=conn))
PY

# 5. 测试
pytest
```

> 注意：采集依赖本机 Chrome（CDP 9222 端口被动监听 joblist.json，不发主动请求）。
> 子进程超时 300s，异常抛 `ScraperError` / `ScraperTimeoutError`。

## 架构文档

详见 [docs/architecture/](docs/architecture/) —— 含 ERD、模块接口、目录结构、14 份 ADR。

## 分支策略

- `main` — 稳定版本
- `develop` — 开发基线（PR 合入 main）
- `feature/*` — 功能分支（PR 合入 develop）

## License

MIT