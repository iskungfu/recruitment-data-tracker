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
| Week 2 — 爬虫 MVP | 待启动 |
| Week 3 — 数据分析 | 待启动 |
| Week 4 — 跨平台 + 报告 | 待启动 |
| Week 5 — 自动化 | 待启动 |

## 技术栈

- Python 3.11+ / SQLite / Plotly / jieba
- Playwright（BOSS 反爬）/ 原生 sqlite3（零外部 DB 依赖）

## 快速开始

```bash
git clone https://github.com/iskungfu/recruitment-data-tracker.git
cd recruitment-data-tracker
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m tracker migrate  # 初始化数据库
```

## 架构文档

详见 [docs/architecture/](docs/architecture/) —— 含 ERD、模块接口、目录结构、14 份 ADR。

## 分支策略

- `main` — 稳定版本
- `develop` — 开发基线（PR 合入 main）
- `feature/*` — 功能分支（PR 合入 develop）

## License

MIT