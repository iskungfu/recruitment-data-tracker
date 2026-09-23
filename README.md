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
| Week 3 — 数据分析 | ✅ 完成（同比/环比 + JD 词频 + HTML 单文件报告，102 个测试） |
| Week 4 — 跨平台 + 报告 | ✅ 完成（步骤二：职友集采集管线 + migration 0002；步骤三：--compare 双平台对比报告 + P2 平台拆分 + 5 项 P3 修复，167 个测试） |
| Week 5 — 自动化 | ✅ 完成（每周一 9:00 定时任务「招聘数据周报」自动生成 --compare 报告并上传飞书云盘；P3 去重哈希 casefold 修复，168 个测试） |
| Week 6 — 发布管线 + 网站 | ✅ 完成（`data/publish/` 发布管线：SQLite → 6 个 JSON → GitHub `data` 分支 → jsDelivr CDN → 静态网站；季度采集提醒 cron；176 个测试） |
| Week 6 — 并发采集 | ✅ 完成（`scripts/boss_cdp_raw.py` 新增 `--keywords` 并发模式：ThreadPoolExecutor 4-10 worker + 全局 encrypt_job_id 去重 + tqdm 进度 + 登录墙全员收尾；181 个测试） |

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

# 1. 初始化数据库（4 表 + schema_version + 5 城 / 34 关键词种子）
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

## 多关键词并发采集（Week 6）

`scripts/boss_cdp_raw.py` 新增 `--keywords` 并发模式（本仓库已内置改造版，
也可整体覆盖外部 boss-zhipin-scraper 克隆里的同名脚本，单 `--keyword` 用法完全兼容）：

```cmd
REM 并发模式：北京 22 个 CS 关键词，6 个 worker
python scripts\boss_cdp_raw.py --keywords "后端,前端,算法工程师,测试开发,数据分析,架构师,AI Agent,大模型,推荐系统,云计算,安全,运维,芯片设计,芯片验证,FPGA,集成电路,模拟IC,数字IC,射频,半导体工艺,EDA,嵌入式" --city "北京" --pages 3 --workers 6 --output data\raw\beijing_cs_semi.json
```

- `--workers` 默认 6，范围 4-10（超出自动钳制）；同一 worker 连续搜索间隔 uniform(3,7)s
- 每个 worker 独立 CDP 会话 + 独立 page（`scrape_list` 内部自建，线程天然隔离）
- 合并结果按 `encrypt_job_id` 全局去重（不同关键词可能搜出同一岗位），单文件输出
- tqdm 进度条实时显示各 worker 当前关键词；任一 worker 遇到登录墙/验证码，
  全员在当前关键词边界优雅收尾并以退出码 1 退出
- 每关键词同时落盘到 `<输出名>_parts/`（异常中断也保留已抓部分）
- 并发模式当前只做列表采集（等价 `--no-detail`），不支持 `--merge` / `--input`
- 依赖 `pip install tqdm`（未装时进度条自动降级为无，不影响功能）

## 数据分析与报告（Week 3）

```python
# 同比/环比：overall / by_city / by_direction 三维度，分母 NULL/0 返回 None
from analysis.stats import compute_yoy_qoq
compute_yoy_qoq("data/recruitment.db", city="北京")

# JD 高频词（jieba 分词，过滤单字/标点/停用词）
from analysis.keywords import analyze_keywords
analyze_keywords("data/recruitment.db", top_n=50)
```

```bash
# 生成单文件 HTML 报告（KPI 卡片 + 趋势/方向/高频词/学历/经验 5 类图表）
python -m analysis.report data/recruitment.db report.html
```

```bash
# 双平台对比模式：KPI 卡片分平台独立统计 + 跨平台唯一岗位数，
# 薪资趋势图双平台叠放（BOSS 实线 / JOBUI 虚线），默认输出 compare_report.html
python -m analysis.report --compare data/recruitment.db
```

> 报告内嵌 plotly.js（仅首个图表内嵌一次），单文件可直接离线打开。
> 日薪岗位（`salary_unit='day'`）不计入薪资均值；方向归属为
> job_name 关键词启发式，未匹配岗位计入 `unattributed`。
>
> **跨平台口径（Week 4 步骤三裁决）**：`compute_yoy_qoq` 三维度各带 `by_platform`
> 子结构（job_count / avg_salary 分平台统计），`overall` 另含 `total_unique_jobs`
> （本季，按 岗位名+公司+城市 归一（strip+casefold）sha1 哈希跨平台去重——
> 大小写/首尾空白变体计为同一岗位，仅报告层口径、不落库）。
> 普通模式保持 Week 3 行为，报告头提示「含 N 个 JOBUI 聚合条目，
> 请参考 --compare 模式跨平台对比」；双平台重叠请勿直接相加。

## 职友集采集（Week 4）

跨平台对比的第二数据源为职友集（jobui.com）。与 BOSS 不同，职友集没有现成外部 CLI，
采集脚本为我们自己的 `scripts/jobui_cdp_raw.py`（CDP 被动优先：连接本机 Chrome，
复用真实浏览器指纹，不自建请求）。

```bash
# 0. 依赖：pip install lxml playwright（lxml 为 DOM 解析必装；playwright 仅采集脚本需要）

# 1. 启动带 CDP 的本机 Chrome
chrome --remote-debugging-port=9222

# 2. 单组合采集（表单流：入口页 → 输入关键词 → 带 Referer 跳转，匿名免登录；
#    首版只采第 1 页，每页 20 条）
python3 scripts/jobui_cdp_raw.py --keyword "后端" --city "北京" \
    --pages 1 --format json --output data/raw/jobui_jobs_北京_后端.json --cdp-port 9222

# 3. 入库（自动应用 migration 0002 补 source_platform/source_url 列；
#    薪资统一换算 K 落库与 BOSS 同口径；城市未匹配时 city_id 置 NULL 不丢记录）
python -m importers.jobui_importer data/raw/jobui_jobs_*.json --db data/recruitment.db

# 批量：经 wrapper（相邻组合间 sleep max(batch_delay_sec, uniform(5,10))s 限速——
#    JOBUI 批次该配置值仅作开关/下限：0 = 测试模式不等待，>0 时至少随机等 5-10 秒）
python3 -c "
from core.config import Settings
from collectors.jobui_scraper import JobuiScraperConfig, run_scraper, run_scraper_batch
settings = Settings()
run_scraper_batch(['后端', 'Java'], ['北京', '上海'], settings)   # 失败组合跳过不中断
"
```

字段映射口径（2026-09-23 组长裁决）：薪资统一换算 **K** 落库（元 ÷1000 / K ×1 / 万 ×10；
"面议"→NULL；"XX以上"→仅 salary_min；日薪→`salary_unit='day'`、min/max NULL；
默认 `year_multiplier=12`）；学历/经验/公司名**原文照存**（"本科以上"≠"本科"）；
`encrypt_job_id = jobui_<jobID>`；新增 `source_platform`（域名）/ `source_url`（详情页 URL）
两列（migration 0002）；`jd_fulltext` 统一 NULL（职友集详情页为跳转页，无 JD 正文）。

反爬：直接访问搜索 URL（无 Referer）会撞登录墙 → 必须走表单流；高频访问触发
IP 级图片验证码（约 10-15 分钟自动解封）；登录墙/验证码分别映射
`JobuiLoginRequiredError` / `JobuiCaptchaError`（wrapper 按脚本退出码 2/3 映射）。

## 发布管线与网站（Week 6）

本地分析结果发布为静态 JSON，网站经 jsDelivr CDN 只读加载
（架构：`docs/06-website-architecture-v1.0.md`，分离式架构——采集/分析在本机，
展示在云端静态页）。

```bash
# 一键季度发布：采集（tracker 模块未实现则跳过）→ 生成 6 个 JSON → 推送 data 分支
# 注意：当前版本一键脚本不含采集（tracker 模块待后续实现），采集需手动执行；
#       脚本会直接发布现有库数据，并在跳过采集时打印警告。
bash scripts/quarterly_publish.sh

# 或只跑发布（默认 data/recruitment.db → data/publish/v1/）
python -m data.publish.cli --db data/demo.db --out data/publish/v1

# 单独校验已发布的 JSON
python -m data.publish.format_check data/publish/v1
```

- 输出 6 个 JSON（schema 见架构 §3.2）：`manifest.json`（索引 + 动态 filters）/
  `summary.json` / `salary_trends.json` / `job_ranking.json` /
  `edu_exp_distribution.json` / `data_status.json`
- 冻结约束：`core/`、`storage/`、`collectors/`、`importers/`、`analysis/` 源码零改动，
  发布层只 import `analysis` 公开函数（`compute_yoy_qoq` / `analyze_keywords` /
  `get_quarter_of` / `quarter_label`）；方向归属启发式与 `analysis.stats` 同口径平行实现
- `chart_specs` 字段为 Plotly.js 直接可用的 `{type, data, layout}`，网站 `Plotly.react()` 渲染
- 空库降级：只建表无岗位时仍输出合法 JSON（数值 0 / null、结构保留），format_check 全过
- CDN 基础路径：`https://cdn.jsdelivr.net/gh/iskungfu/recruitment-data-tracker@data/data/publish/v1/`
  （`@data` 为发布分支名、其后 `data/` 为仓库内目录——data 分支与 develop 同树，
  故路径含两段 data；降级源：`https://raw.githubusercontent.com/iskungfu/recruitment-data-tracker/data/data/publish/v1/`）
- 季度提醒：定时任务「季度采集提醒」（每季度首月 1 号 9:00 飞书提醒执行季度发布）

## 架构文档

详见 [docs/architecture/](docs/architecture/) —— 含 ERD、模块接口、目录结构、14 份 ADR。

## 分支策略

- `main` — 稳定版本
- `develop` — 开发基线（PR 合入 main）
- `feature/*` — 功能分支（PR 合入 develop）

## License

MIT