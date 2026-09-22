-- ============================================================
-- 招聘数据采集与分析系统 — 数据库 Schema v1
-- 兼容 SQLite 3.35+
-- 来源：docs/architecture/02-database-erd.md §2（原样落地）
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

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_status ON snapshots(status);

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
CREATE INDEX IF NOT EXISTS idx_job_city      ON job_snapshot(city_id);
CREATE INDEX IF NOT EXISTS idx_job_date      ON job_snapshot(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_job_direction ON job_snapshot(job_name);  -- 辅助按方向筛选
CREATE INDEX IF NOT EXISTS idx_job_salary    ON job_snapshot(salary_min, salary_max);
