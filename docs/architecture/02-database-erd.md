# 数据库 ERD 与 Schema

> 版本：v1.0 | 日期：2026-09-22 | 对应架构概览 §2 模块 `storage/`

---

## 1. 实体关系图（ERD）

```
┌──────────────┐        ┌──────────────────┐        ┌──────────────┐
│   keywords   │        │   job_snapshot    │        │    cities     │
├──────────────┤        ├──────────────────┤        ├──────────────┤
│ id (PK)      │        │ id (PK, AUTOINCR)│        │ id (PK)      │
│ direction    │        │ job_id            │◄──┐    │ name         │
│ keyword      │──┐     │ job_name          │   │    │ province     │
│ platform     │  │     │ salary_raw        │   │    │ boss_city_code│
│ is_active    │  │     │ salary_min        │   │    │ jobui_slug   │
└──────────────┘  │     │ salary_max        │   │    │ is_active    │
                  │     │ year_multiplier   │   │    └──────────────┘
                  │     │ salary_unit       │   │          │
┌──────────────┐  │     │ city_id (FK)      │───┼──────────┘
│  snapshots   │  │     │ company_name      │   │
├──────────────┤  │     │ education         │   │
│ id (PK)      │  │     │ experience        │   │
│ snapshot_date│  │     │ jd_fulltext       │   │
│ keyword_id───┼──┘     │ skill_tags        │   │
│ city_id ─────┼────────│ platform          │   │
│ city_name    │        │ encrypt_job_id    │   │
│ keyword      │        │ snapshot_date     │   │
│ status       │        │ created_at        │   │
│ started_at   │        └──────────────────┘   │
│ completed_at │                               │
│ job_count    │        ┌──────────────────┐    │
│ error_log    │        │  schema_version   │    │
└──────────────┘        ├──────────────────┤
                         │ version          │
                         │ applied_at       │
                         │ description      │
                         └──────────────────┘
```

### 关系说明

| 关系 | 类型 | 说明 |
|------|------|------|
| keywords → job_snapshot | 逻辑关联 | 通过 `keyword` 字段值匹配（非外键，keyword 可能变更） |
| cities → job_snapshot | FK | `city_id` 外键关联，约束数据完整性 |
| snapshots → keywords | FK | `keyword_id` 外键，记录每次采集使用的关键词 |
| snapshots → cities | FK | `city_id` 外键，记录每次采集的目标城市 |

---

## 2. 完整 DDL（SQLite）

```sql
-- ============================================================
-- 招聘数据采集与分析系统 — 数据库 Schema v1
-- 兼容 SQLite 3.35+
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------
-- 表 1: schema_version — 迁移版本跟踪
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_version (version, description)
VALUES (1, 'Initial schema: cities, keywords, snapshots, job_snapshot');

-- ----------------------------------------------------------
-- 表 2: cities — 目标城市
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS cities (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL UNIQUE,       -- "北京"、"上海" 等
    province       TEXT NOT NULL,              -- 所属省份
    boss_city_code TEXT,                       -- BOSS 直聘城市编码（W2 实测填入）
    jobui_slug     TEXT,                       -- 职友集城市 slug（W2 实测填入）
    is_active      INTEGER NOT NULL DEFAULT 1, -- 1=启用, 0=停用
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 种子数据：5 城，已裁决
INSERT OR IGNORE INTO cities (name, province, boss_city_code, jobui_slug) VALUES
    ('北京', '北京市', 'TODO_W2_BOSS_BEIJING',    'TODO_W2_JOBUI_BEIJING'),
    ('上海', '上海市', 'TODO_W2_BOSS_SHANGHAI',   'TODO_W2_JOBUI_SHANGHAI'),
    ('深圳', '广东省', 'TODO_W2_BOSS_SHENZHEN',   'TODO_W2_JOBUI_SHENZHEN'),
    ('杭州', '浙江省', 'TODO_W2_BOSS_HANGZHOU',   'TODO_W2_JOBUI_HANGZHOU'),
    ('成都', '四川省', 'TODO_W2_BOSS_CHENGDU',    'TODO_W2_JOBUI_CHENGDU');

-- ----------------------------------------------------------
-- 表 3: keywords — 采集关键词
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS keywords (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    direction  TEXT NOT NULL,              -- 方向：前端/后端/算法/AI应用/数据/测试 (计算机)
                                           --      IC设计/IC验证/工艺/封测/设备/材料 (半导体)
    keyword    TEXT NOT NULL UNIQUE,       -- 搜索关键词："Vue"、"Java"、"数字IC" 等
    platform   TEXT NOT NULL DEFAULT 'BOSS', -- BOSS / 职友集 / 猎聘
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 种子数据：12 方向 × 关键词，对应 PRD §3.1
INSERT OR IGNORE INTO keywords (direction, keyword) VALUES
    -- 计算机类
    ('前端',   '前端'),
    ('前端',   'Vue'),
    ('前端',   'React'),
    ('后端',   '后端'),
    ('后端',   'Java'),
    ('后端',   'Python'),
    ('后端',   'Go'),
    ('算法',   '算法工程师'),
    ('算法',   '机器学习'),
    ('算法',   '深度学习'),
    ('AI应用', 'AI Agent'),
    ('AI应用', 'LLM'),
    ('AI应用', 'RAG'),
    ('数据',   '数据分析师'),
    ('数据',   '数据工程师'),
    ('测试',   '测试工程师'),
    ('测试',   '自动化测试'),
    -- 半导体类
    ('IC设计', '数字IC'),
    ('IC设计', '模拟IC'),
    ('IC设计', '版图工程师'),
    ('IC验证', 'IC验证'),
    ('IC验证', 'UVM'),
    ('IC验证', 'SystemVerilog'),
    ('工艺',   '半导体工艺'),
    ('工艺',   '晶圆'),
    ('工艺',   '光刻'),
    ('封测',   '封装工程师'),
    ('封测',   '芯片测试'),
    ('设备',   '半导体设备'),
    ('设备',   '刻蚀'),
    ('设备',   '薄膜沉积'),
    ('材料',   '硅片'),
    ('材料',   '光刻胶'),
    ('材料',   '电子特气');

-- ----------------------------------------------------------
-- 表 4: snapshots — 采集任务元信息
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,           -- 采集日期 YYYY-MM-DD
    keyword_id   INTEGER NOT NULL REFERENCES keywords(id),
    city_id      INTEGER NOT NULL REFERENCES cities(id),
    city_name    TEXT NOT NULL,            -- 冗余城市名，方便查询
    keyword      TEXT NOT NULL,            -- 冗余关键词，方便查询
    status       TEXT NOT NULL DEFAULT 'pending', -- pending / running / done / failed
    started_at   TEXT,
    completed_at TEXT,
    job_count    INTEGER DEFAULT 0,
    error_log    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_snapshots_date ON snapshots(snapshot_date);
CREATE INDEX idx_snapshots_status ON snapshots(status);

-- ----------------------------------------------------------
-- 表 5: job_snapshot — 岗位快照（核心数据表）
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL,                  -- 平台原始 job_id（如 encryptJobId）
    job_name        TEXT NOT NULL,                  -- 岗位名
    salary_raw      TEXT NOT NULL,                  -- 薪资原文："30-60K·15薪"
    salary_min      REAL,                           -- 薪资下限（K/月），日薪制为 NULL
    salary_max      REAL,                           -- 薪资上限（K/月），日薪制为 NULL
    year_multiplier INTEGER,                        -- 年薪月数："15薪"→15，NULL 表示未标注
    salary_unit     TEXT DEFAULT 'month',           -- 薪资单位：month / day / hour
    city_id         INTEGER REFERENCES cities(id),  -- 城市 FK
    company_name    TEXT NOT NULL,                  -- 公司名
    education       TEXT,                           -- 学历要求（归一化后）
    experience      TEXT,                           -- 经验要求
    jd_fulltext     TEXT,                           -- JD 全文（列表页无正文时可为空，W2 两阶段回填）
    skill_tags      TEXT,                           -- 平台标签，JSON 数组字符串
    platform        TEXT NOT NULL DEFAULT 'BOSS',   -- BOSS / 职友集
    encrypt_job_id  TEXT,                           -- BOSS 加密 job_id，用于去重
    snapshot_date   TEXT NOT NULL,                  -- 采集日期 YYYY-MM-DD
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),

    -- 去重约束：同一岗位同一天不重复入库
    UNIQUE(encrypt_job_id, snapshot_date)
);

-- 查询索引
CREATE INDEX idx_job_city      ON job_snapshot(city_id);
CREATE INDEX idx_job_date      ON job_snapshot(snapshot_date);
CREATE INDEX idx_job_direction ON job_snapshot(job_name);  -- 辅助按方向筛选
CREATE INDEX idx_job_salary    ON job_snapshot(salary_min, salary_max);
```

---

## 3. 字段映射表：PRD §3.5 ↔ DB Schema

| PRD 字段 | DB 列 | 类型 | 说明 |
|---------|-------|------|------|
| 岗位名 | `job_name` | TEXT NOT NULL | 原始岗位名，不做归一化 |
| 薪资原文 | `salary_raw` | TEXT NOT NULL | 保留原文如 "30-60K·15薪" |
| 薪资下限 | `salary_min` | REAL | 解析后数值（K/月），日薪 NULL |
| 薪资上限 | `salary_max` | REAL | 解析后数值（K/月），日薪 NULL |
| 城市 | `city_id` → `cities.name` | FK | 通过 city_id 关联 |
| 公司名 | `company_name` | TEXT NOT NULL | 原始公司名 |
| 学历要求 | `education` | TEXT | "本科及以上"→"本科"（归一化） |
| 经验要求 | `experience` | TEXT | 原始经验文本 |
| JD 全文 | `jd_fulltext` | TEXT | 可空，W2 两阶段回填 |
| 技能标签 | `skill_tags` | TEXT | JSON 数组字符串 |
| 平台来源 | `platform` | TEXT NOT NULL | "BOSS" / "JOBUI" |
| 平台原 job_id | `encrypt_job_id` | TEXT | BOSS encryptJobId |
| 抓取日期 | `snapshot_date` | TEXT NOT NULL | YYYY-MM-DD |

### 扩展字段（PRD 附录建议采纳）

| 扩展字段 | DB 列 | 类型 | 来源 |
|---------|-------|------|------|
| 年薪月数 | `year_multiplier` | INTEGER | PRD B.1 → 已纳入 |
| 薪资单位 | `salary_unit` | TEXT | 预研暴露日薪制岗位 → 已纳入 |

---

## 4. 数据量估算

| 表 | 单季度增量 | 一年累积 | 说明 |
|----|----------|---------|------|
| `cities` | 0（静态） | 5 行 | 5 城固定 |
| `keywords` | 0（静态） | 35 行 | PRD §3.1 全量关键词 |
| `snapshots` | 35 × 5 × 1 = 175 行 | 700 行 | 每关键词每城一次采集任务记录 |
| `job_snapshot` | ≤5000 行 | ≤20000 行 | 每关键词每城 ≤10 页 ≈ 300 条，35 关键词 × 5 城 ≈ 实际去重后约 3000-5000 |

**总数据量**：一年 4 个季度 < 30,000 行，SQLite 单文件 < 50MB，内存分析完全可行。

---

## 5. 迁移策略

| 版本 | 变更 | 文件 |
|------|------|------|
| v1 | 初始建表（4 表 + schema_version） | `storage/migrations/0001_initial.sql` |
| v2 (预留) | 日薪制岗位 `salary_unit` 字段 | 仅 DDL 补充，无数据迁移 |
| v3 (预留) | 职友集数据新增 `source_url` 字段 | ALTER TABLE ADD COLUMN |

迁移执行：`storage/migrations/` 目录按编号升序，由部署脚本 `python -m storage.migrate` 执行。

---

## 6. 研发可直接开工的代码

基于此 ERD，以下文件可立即编写：

- `storage/schema.py`：`create_tables(conn)` + `insert_seed_data(conn)`
- `storage/migrations/0001_initial.sql`：上述完整 DDL（直接复制）
- `storage/connection.py`：`get_connection(db_path)` 单例
- `storage/dao.py`：`insert_job()`, `get_jobs_by_date()`, `get_snapshot_stats()` 等