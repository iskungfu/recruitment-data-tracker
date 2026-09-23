# 招聘数据网站 — 架构设计

> 版本：v1.0 | 日期：2026-09-23 | 作者：软件架构师
> 对应 PRD v2：5 页 / 单数据源 BOSS / 每 3 月自动采集 / 移动端 375px 无溢出

---

## 0. 用户决策回顾

用户（傅俊康）已在决策卡中选择：

| 决策项 | 选择 |
|--------|------|
| 桌面应用 vs 网站 | **网站**（在线访问，部署到服务器） |
| 手动触发 vs 自动 | **每 3 个月自动拉取** |
| 关注维度 | 薪资趋势 / 岗位需求排行 / 学历经验分布 / ~~Boss vs 职友集~~（已修正为 BOSS 单源） |

**产品经理 v2 修正**：单数据源 BOSS（不用职友集），5 页面闭环，现有代码冻结不修改 core/storage/已有 BOSS 管线。

---

## 1. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     本地采集层（用户本机）                        │
│                                                                 │
│  boss-zhipin-scraper ──CDP──→ Chrome ──抓取──→ data/raw/*.json  │
│         │                                                        │
│         ▼                                                        │
│  importers/boss_importer.py ──清洗──→ SQLite (recruitment.db)   │
│         │                                                        │
│         ▼                                                        │
│  analysis/stats.py    ──预计算──→  data/publish/v1/             │
│  analysis/keywords.py               ├── summary.json            │
│  analysis/report.py                 ├── salary_trends.json      │
│       │                             ├── job_ranking.json        │
│       │                             ├── edu_exp_distribution.json│
│       │                             ├── data_status.json         │
│       │                             └── manifest.json            │
│       │                                                        │
│       ▼          git add + commit + push                        │
│  GitHub: recruitment-data-tracker → `data` branch               │
│       │         (纯 JSON 发布分支，解析型分析不提交)             │
└───────┼─────────────────────────────────────────────────────────┘
        │
        │  jsDelivr CDN（自动缓存 GitHub raw）
        │  https://cdn.jsdelivr.net/gh/iskungfu/recruitment-data-tracker@data/
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     云端展示层（静态网站）                        │
│                                                                 │
│  app_builder → jspage → 部署 URL                                │
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐ │
│  │ 首页总览  │ │ 薪资趋势  │ │ 岗位排行  │ │ 学历经验  │ │数据  │ │
│  │ Page 1   │ │ Page 2   │ │ Page 3   │ │ Page 4   │ │Page 5│ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──┬───┘ │
│       └───────────┴────────────┴────────────┴────────────┘      │
│                           │                                      │
│                    共享状态层 (URL query params)                  │
│                  ?city=北京&direction=全部&quarter=2026Q3         │
│                           │                                      │
│                    fetch manifest.json                           │
│                    → 按需加载各数据集                              │
└─────────────────────────────────────────────────────────────────┘
```

### 1.1 关键决策：分离式架构（本地采集 + GitHub + CDN + 静态网站）

| 问题 | 方案 |
|------|------|
| 服务器没有 Chrome → 采集在本机 | 本地 Python 跑全流程，产出纯 JSON |
| JSON 怎么到网站 | GitHub `data` branch + jsDelivr CDN |
| 网站怎么部署 | app_builder `jspage`（纯前端，无后端） |
| 每 3 个月触发 | 用户本机 launchd/cron + `aily-cli auto` 推送飞书提醒 |

### 1.2 架构层级

```
Layer 4: 展示层     → app_builder jspage（Plotly.js + 纯前端路由）
Layer 3: CDN 层     → jsDelivr（GitHub raw 自动缓存，全球边缘节点）
Layer 2: 发布层     → GitHub `data` branch（JSON 不变式文件）
Layer 1: 计算层     → 本地 Python 脚本（stats.py / keywords.py / report.py）
Layer 0: 采集层     → boss-zhipin-scraper + boss_importer（已有，不改）
```

---

## 2. 技术选型（问题 1）

### 2.1 `arch_type`: `jspage`

| 候选 | 理由 |
|------|------|
| `html` | 单 HTML 文件不适合 5 页 + Plotly 图表 + 跨页状态管理；375px 移动端需响应式路由 |
| `fullstack` | 无后端写入需求——数据全量预计算为 JSON，网站只读；纯静态 CDN 部署即可，无需服务端 |
| **`jspage`** ✅ | 纯前端 + Plotly.js + fetch JSON + URL params 状态路由；可通过 app_builder 部署到可访问 URL |

**技术栈**（网站侧，无需 npm install——app_builder 包管）：
- **Plotly.js**：图表渲染（同 Python 版 Plotly，图表配置可从 `report.py` 直接搬 JSON spec）
- **原生 fetch**：从 jsDelivr CDN 拉 JSON 数据
- **URL query params**：跨页面筛选状态（`?city=北京&direction=全部&quarter=2026Q3`）
- **CSS Grid + clamp()**：375px-1280px 响应式，无横向溢出

### 2.2 为什么不是 fullstack

- 5 个页面全是**只读展示**，无用户输入/登录/写入操作
- 数据每 3 个月更新一次，不是实时数据→编译时/部署时加载最合适
- 后端 API 意味着服务器、数据库、鉴权——复杂度超出价值 10 倍
- jsDelivr CDN 已提供全球边缘缓存 + 自动刷新

---

## 3. 数据流（问题 2 + 3 + 4 + 5）

### 3.1 完整数据流

```
步骤 1: 采集（本机，每 3 月触发一次）
  $ python -m tracker collect
  → boss-zhipin-scraper CDP 采集 → data/raw/*.json
  → boss_importer 清洗入库 → data/recruitment.db

步骤 2: 发布数据生成（本机，采集后立即执行）
  $ python -m tracker publish
  → 从 SQLite 读全量数据
  → stats.py 预计算同比/环比/聚合
  → keywords.py 预计算 Top 20 技能词频
  → report.py 预计算所有图表数据（Plotly JSON spec）
  → 输出 6 个 JSON 文件到 data/publish/v1/

步骤 3: 推送发布（本机）
  $ git add data/publish/v1/
  $ git commit -m "publish: 2026Q3 data snapshot"
  $ git push origin data

步骤 4: 延迟（CDN 自动）
  jsDelivr 检测 GitHub commit → 自动缓存新 JSON → 全球边缘节点生效（~1-5 分钟）

步骤 5: 网站加载（用户浏览器）
  打开网站 → fetch manifest.json → 检查版本 →
  fetch 对应 JSON 数据集 → Plotly.js 渲染图表
```

### 3.2 每层的数据格式

#### Layer 1: 发布数据 JSON 规范（data/publish/v1/）

**`manifest.json`**（网站首先加载的索引）
```json
{
  "version": "2026Q3",
  "generated_at": "2026-10-01T02:30:00+08:00",
  "generated_by": "tracker-publish v0.1",
  "data_snapshot_date": "2026-10-01",
  "datasets": {
    "summary": "summary.json",
    "salary_trends": "salary_trends.json",
    "job_ranking": "job_ranking.json",
    "edu_exp_distribution": "edu_exp_distribution.json",
    "data_status": "data_status.json"
  },
  "filters": {
    "cities": ["北京", "上海", "深圳", "杭州", "成都"],
    "directions": ["前端", "后端", "算法", "AI应用", "数据", "测试", "IC设计", "IC验证", "工艺", "封测", "设备", "材料"],
    "quarters": ["2026Q3"]
  }
}
```

**`summary.json`**（首页总览——4 个 KPI 卡片数据）
```json
{
  "kpi": {
    "total_jobs": 3482,
    "avg_salary": {"min": 22.5, "max": 35.8, "unit": "K/月"},
    "cities_covered": 5,
    "directions_covered": 12,
    "yoy_job_growth": null,
    "qoq_salary_change": null
  },
  "top_direction_by_growth": "AI应用",
  "top_direction_by_salary": "算法",
  "latest_snapshot_date": "2026-10-01"
}
```

**`salary_trends.json`**（第 2 页——薪资趋势）
```json
{
  "metrics": ["avg_salary_min", "avg_salary_max", "job_count"],
  "by_direction": {
    "前端": {
      "2026Q3": {
        "avg_salary_min": 18.2, "avg_salary_max": 28.5,
        "job_count": 342, "yoy_job_count": null, "qoq_job_count": null
      }
    }
  },
  "by_city": {
    "北京": {
      "2026Q3": {
        "avg_salary_min": 25.3, "avg_salary_max": 38.1,
        "job_count": 892, "yoy_salary": null
      }
    }
  },
  "chart_specs": {
    "direction_comparison": {"type": "bar", "data": [...], "layout": {...}},
    "city_comparison": {"type": "bar", "data": [...], "layout": {...}}
  }
}
```

**`job_ranking.json`**（第 3 页——岗位需求排行）
```json
{
  "rankings": [
    {"rank": 1, "direction": "后端", "job_count": 582, "share": 0.167,
     "top_cities": ["北京", "深圳"], "yoy_change": null},
    {"rank": 2, "direction": "前端", "job_count": 342, "share": 0.098, ...}
  ],
  "top_skills_across_all": [
    {"skill": "Python", "count": 1204},
    {"skill": "Java", "count": 987}
  ],
  "chart_specs": {
    "ranking_bar": {"type": "barh", "data": [...], "layout": {...}},
    "skills_wordcloud": {"type": "bar", "data": [...], "layout": {...}}
  }
}
```

**`edu_exp_distribution.json`**（第 4 页——学历经验分布）
```json
{
  "education": {
    "本科": 2145, "硕士": 892, "大专": 312, "博士": 45, "不限": 88
  },
  "experience": {
    "1-3年": 1203, "3-5年": 982, "5-10年": 589, "应届": 420, "不限": 288
  },
  "by_direction": {
    "前端": {"education": {"本科": 250, "硕士": 68, ...}, "experience": {...}}
  },
  "chart_specs": {
    "edu_pie": {"type": "pie", "data": [...], "layout": {...}},
    "exp_bar_by_dir": {"type": "bar", "data": [...], "layout": {...}}
  }
}
```

**`data_status.json`**（第 5 页——数据状态栏）
```json
{
  "snapshots": [
    {"date": "2026-10-01", "total_jobs": 3482, "cities": {"北京": 892, "上海": 712, "深圳": 680, "杭州": 623, "成都": 575}},
    {"date": "2026-07-01", "total_jobs": 3210, "cities": {...}}
  ],
  "quality": {
    "salary_parse_rate": 0.973,
    "jd_fulltext_rate": 0.68,
    "duplicate_rate": 0.042
  },
  "collection_log": [
    {"keyword": "后端", "city": "北京", "status": "done", "pages": 3, "jobs": 45}
  ]
}
```

#### Layer 2: 发布管线（新增，不改现有代码）

```python
# data/publish/cli.py（新增，不在 frozen 范围内）
"""
python -m data.publish.cli
→ 从 SQLite 读取全量 → 调现有 analysis 模块 → 输出 JSON → git push
"""
```

**复用策略**：不改 `analysis/stats.py` / `keywords.py` 源码——新增 `data/publish/cli.py` 调它们的公开函数，纯数据管道：
```python
from analysis.stats import compute_yoy_qoq, aggregate_by_direction
from analysis.keywords import segment_jd, top_keywords_for_direction
from analysis.report import generate_chart_spec   # 已有 Plotly JSON spec 产出能力
from storage.dao import get_jobs_by_date_range, get_existing_keys
```

#### Layer 3: 网站端数据加载

```javascript
// 网站启动时
async function loadData() {
  const manifest = await fetch(`${CDN_BASE}/manifest.json`).then(r => r.json());
  const datasets = {};
  for (const [name, file] of Object.entries(manifest.datasets)) {
    datasets[name] = await fetch(`${CDN_BASE}/${file}`).then(r => r.json());
  }
  return { manifest, datasets };
}
```

---

## 4. 现有代码复用策略（问题 3）

### 4.1 复用清单

| 现有模块 | 复用方式 | 改动 |
|---------|---------|------|
| `analysis/stats.py` | `compute_yoy_qoq()` 直接调，输出写入 JSON | **不改源码** |
| `analysis/keywords.py` | `top_keywords_for_direction()` → JSON | **不改源码** |
| `analysis/report.py` | `generate_chart_spec()` → Plotly JSON spec 嵌入 data JSON | **不改源码** |
| `storage/dao.py` | 读取全量数据的 SQL 查询 | **不改源码** |
| `storage/schema.py` | 已有 4 表不变 | **不改** |
| `importers/boss_importer.py` | 已有管线不变 | **不改** |

### 4.2 新增文件（不碰 frozen 区域）

```
data/
  publish/
    cli.py              ← 发布管线主入口（python -m data.publish.cli）
    __init__.py
    format_check.py      ← JSON schema 校验（确保输出一致）
  publish/v1/
    .gitkeep
    manifest.json        ← 由 cli.py 生成
    summary.json
    salary_trends.json
    job_ranking.json
    edu_exp_distribution.json
    data_status.json

scripts/
  quarterly_publish.sh   ← 一键全流程：collect → publish → git push
```

### 4.3 图解：Python → JSON → 网站

```
现有 analysis/*.py（不改）          新增 data/publish/cli.py
     │                                     │
     │  import                              │  orchestrate
     ▼                                     ▼
compute_yoy_qoq()  ─────────────→  预计算结果 → JSON
segment_jd()       ─────────────→  Top 20 技能 → JSON
generate_chart_spec() ──────────→  Plotly spec → JSON   → GitHub data branch
                                                                   │
                                                           jsDelivr CDN
                                                                   │
                                                             fetch() in browser
                                                                   │
                                                           Plotly.js 渲染
```

---

## 5. 部署方案（问题 4）

### 5.1 网站部署

| 层 | 部署位置 | 说明 |
|----|---------|------|
| HTML/JS/CSS | app_builder（jspage）→ 部署 URL | app_builder 自动构建 + 部署 |
| JSON 数据 | GitHub `data` branch → jsDelivr CDN | `data/publish/v1/*.json` 按版本发布 |
| 数据库 | 本机 `data/recruitment.db` | 不上传 GitHub（.gitignore） |

### 5.2 CDN 路径

```
网站 fetch 基础路径（jsDelivr）:
  https://cdn.jsdelivr.net/gh/iskungfu/recruitment-data-tracker@data/publish/v1/

示例:
  https://cdn.jsdelivr.net/gh/iskungfu/recruitment-data-tracker@data/publish/v1/manifest.json
  https://cdn.jsdelivr.net/gh/iskungfu/recruitment-data-tracker@data/publish/v1/summary.json
```

### 5.3 CDN 优势

- GitHub `data` branch 推送 → jsDelivr 自动缓存 → 全球 CDN 边缘节点
- 无带宽限制、无需服务器、无需 Cloudflare/OSS 配置
- jsDelivr 支持 purge cache（`https://purge.jsdelivr.net/gh/...`）

---

## 6. 采集与网站的桥接（问题 5）

### 6.1 每 3 个月自动采集流程

```
T-3d: aily-cli auto cron "0 9 28 3,6,9,12 *" → 飞书提醒 "下季度采集日临近"
T-0: 用户本机运行 quarterly_publish.sh（手动或 cron）
       │
       ├── python -m tracker collect       ← CDP 采集（需本机 Chrome）
       ├── python -m data.publish.cli      ← 分析 + 生成 JSON
       ├── git add data/publish/v1/
       ├── git commit -m "publish: 2026Q4"
       └── git push origin data
       │
T+5min: jsDelivr 检测新 commit → 自动缓存
T+5min: 网站加载新数据（manifest.json version 变更 → 刷新所有数据集）
```

### 6.2 触发方式

| 方式 | 配置 | 适用场景 |
|------|------|---------|
| **aily-cli auto cron** | `0 9 1 1,4,7,10 *` → 飞书推送提醒 "该跑季度采集了" | 提醒用户手动执行，最稳妥 |
| **用户本机 launchd/cron** | `0 2 1 1,4,7,10 *` → 执行 `quarterly_publish.sh` | 全自动（需本机常开） |
| 手动 | 无 | 兜底 |

**推荐组合**：aily-cli auto 发飞书提醒 + 用户本机 cron 自动执行 `quarterly_publish.sh`。双重保障——本机 cron 跑通了用户无感，失败了有飞书提醒介入。

### 6.3 为什么不能全托管

- CDP 采集需要本机 Chrome（BOSS 反爬不认 headless）
- 采集过程可能有登录验证码——用户需在本机操作
- 服务器无桌面环境，无法运行 boss-zhipin-scraper

---

## 7. 页面间数据一致性（问题 6）

### 7.1 状态管理方案：URL Query Params

```
5 个页面共享 3 个筛选维度，通过 URL query params 传递：

?city=北京&direction=全部&quarter=2026Q3
```

### 7.2 实现

```javascript
// 全球状态对象（从 URL 读取）
const state = {
  city:      getParam('city')      || '全部',
  direction: getParam('direction') || '全部',
  quarter:   getParam('quarter')   || 'latest',
};

// 切换筛选 → 更新 URL（所有页面自动响应）
function setFilter(key, value) {
  const url = new URL(window.location);
  url.searchParams.set(key, value);
  history.pushState({}, '', url);  // 无刷新路由
  state[key] = value;
  renderCurrentPage();             // 当前页重新渲染（从已加载的 datasets 过滤）
}
```

### 7.3 数据加载策略

```
网站启动
  → fetch manifest.json（~500B，一次）
  → 按页面懒加载：
      Page 1（首页总览）  → fetch summary.json
      Page 2（薪资趋势）  → fetch salary_trends.json
      Page 3（岗位排行）  → fetch job_ranking.json
      Page 4（学历经验）  → fetch edu_exp_distribution.json
      Page 5（数据状态）  → fetch data_status.json

切换筛选（city/direction/quarter）
  → 不重新 fetch（数据已在内存）
  → 前端过滤 datasets → Plotly.react() 增量更新图表

切换季度查看历史
  → 仅当选中非当前季度时 fetch 历史 manifest
```

### 7.4 为什么不用 localStorage / Redux / Context

- 5 页数据量小（6 个 JSON 总 < 500KB），全部 in-memory 即可
- URL params 天然支持分享（"看看北京 Q3 的数据" → 发链接即可）
- 浏览器前进/后退自动恢复筛选状态
- 零依赖，无框架约束

---

## 8. 移动端适配

### 8.1 要点

- 5 页通过底部 tab bar 切换（移动端）或顶部 nav（桌面端）
- 图表用 Plotly.js `responsive: true`，容器 `max-width: 100%`
- 表格列数过多时→横向 scroll（`overflow-x: auto`），不做列裁剪
- 375px 基准：`grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr))` 避免溢出
- 字号：桌面 16px / 移动 14px；间距缩小 25%

### 8.2 页面布局（移动端）

```
┌─────────────────────┐
│    招聘数据看板      │  ← 固定顶部标题栏
├─────────────────────┤
│  城市: [北京 ▾]      │  ← 筛选栏（水平滚动 pills）
│  方向: [全部 ▾]      │
│  季度: [2026Q3 ▾]   │
├─────────────────────┤
│                     │
│   页面内容区         │  ← flex-grow: 1, overflow-y: auto
│   （KPI 卡片 /      │
│    图表 / 表格）     │
│                     │
├─────────────────────┤
│ [总览] [趋势] [排行] │  ← 固定底部 tab bar（5 tabs）
│ [分布] [状态]       │
└─────────────────────┘
```

---

## 9. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 用户本机 cron 不工作 | 中 | 数据不更新 | aily-cli auto 推送飞书提醒+操作指南 |
| boss-zhipin-scraper 上游不兼容 | 中 | 采集失败 | fork 锁定 commit；W3 预研兼容性 |
| jsDelivr CDN 不可用 | 低 | 网站空白 | 降级到 GitHub raw URL（`raw.githubusercontent.com`） |
| 手机端 Plotly 图表太大 | 中 | 首次加载慢 | 懒加载（仅当前页 fetch 数据）；`manifest.json` 轻量预检 |
| GitHub `data` branch 误删 | 低 | 数据丢失 | 每季度发布前备份 `data/publish/` 到本地 archive |

---

## 10. ADR-017：网站架构裁决

### 状态
Accepted（2026-09-23）

### 背景
PRD v2 要求将招聘数据分析系统做成在线网站（5 页 + 375px 移动端），但采集依赖本机 Chrome CDP。

### 决策
+ **本地采集 + 云端展示分离架构**：采集/分析/预计算在用户本机 Python 跑，产出一组 JSON 文件推送到 GitHub `data` branch → jsDelivr CDN 分发 → 静态单页网站（app_builder jspage）通过 fetch + Plotly.js 渲染。

### 备选方案
| 方案 | 缺点 |
|------|------|
| fullstack（后端 API + DB） | CDP 采集无法放在服务器；后端需要维护 + 数据库 + 鉴权 |
| 纯静态 HTML 单文件 | 5 页 + Plotly 图表的单 HTML 文件过大（>5MB），加载慢；跨页面状态管理困难 |
| **jspage + CDN JSON** ✅ | 前端轻量、CDN 分发数据、URL params 状态路由；无后端运维 |

### 后果
+ 部署简单：app_builder 自动构建+部署
+ 数据分发免费：jsDelivr CDN 全球 110+ 节点
+ 现有代码零改动：frozen core/storage/analysis 模块，仅新增发布管线
- 采集不是完全自动：需本机 cron/launchd 或用户手动触发（aily-cli auto 可发提醒辅助）
- 混合数据源：网站从 CDN 拉数据，`data` branch 是唯一信源

---

## 11. 研发就绪清单

研发拿到本文档 + 现有仓库 `develop` 分支后，可直接开工：

**Phase 1（发布管线，本地）**
- [ ] 新建 `data/publish/cli.py`：调 `analysis/stats.py` / `keywords.py` / `report.py` → 输出 6 个 JSON
- [ ] 新建 `data/publish/format_check.py`：JSON schema 校验
- [ ] 新建 `scripts/quarterly_publish.sh`：collect → publish → git push
- [ ] 配置 aily-cli auto cron：季度提醒
- [ ] 配置本机 cron/launchd：季度自动执行

**Phase 2（网站，app_builder jspage）**
- [ ] 5 页面骨架（底部 tab + 筛选 pills + 内容区）
- [ ] URL params 状态路由（city / direction / quarter）
- [ ] fetch manifest.json + 懒加载数据集
- [ ] Plotly.js 图表渲染（从 `chart_specs` 字段直接 `Plotly.react()`）
- [ ] 375px 响应式适配（CSS Grid + clamp）
- [ ] 降级策略（CDN 不可用 → GitHub raw URL）

### 数据格式约定速查

| 文件 | 用途 | 页面 | 大小（估） |
|------|------|------|----------|
| `manifest.json` | 索引 + 版本 + 可用筛选值 | 启动 | < 1KB |
| `summary.json` | 4 KPI 卡片 | Page 1 | < 2KB |
| `salary_trends.json` | 薪资折线/柱状图 | Page 2 | < 80KB |
| `job_ranking.json` | 岗位排行 + 技能 Top 20 | Page 3 | < 50KB |
| `edu_exp_distribution.json` | 学历饼图 + 经验柱状图 | Page 4 | < 40KB |
| `data_status.json` | 采集质量 + 历史记录 | Page 5 | < 20KB |

所有 JSON 的 `chart_specs` 字段均为 Plotly.js 直接可用的 `{data, layout}` 对象（Python Plotly `fig.to_dict()` 输出，由现有 `analysis/report.py` 的 `generate_chart_spec()` 提供）。