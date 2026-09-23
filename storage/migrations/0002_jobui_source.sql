-- ============================================================
-- Migration 0002: job_snapshot 来源站字段（Week 4 职友集）
-- 组长裁决 2026-09-23：跨平台来源用独立列记录，不混入 platform
-- 兼容 SQLite 3.35+；由 storage/schema.py 按版本号自动执行，
-- 已应用版本记录在 schema_version，重复执行自动跳过
-- ============================================================

ALTER TABLE job_snapshot ADD COLUMN source_platform TEXT;
ALTER TABLE job_snapshot ADD COLUMN source_url TEXT;

INSERT OR IGNORE INTO schema_version (version, description)
VALUES (2, 'job_snapshot 来源站列: source_platform(域名) / source_url(详情页URL)');
