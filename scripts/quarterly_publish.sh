#!/usr/bin/env bash
# 季度发布一键脚本 — 06-website-architecture-v1.0.md §6.1
# 流程：采集（失败不阻断）→ 生成 6 个发布 JSON → 提交并推送到 data 分支
# 用法：在仓库任意目录执行  bash scripts/quarterly_publish.sh
set -uo pipefail
cd "$(dirname "$0")/.."

# ① 采集：需本机 Chrome（CDP）；tracker 模块缺失或采集失败时沿用现有库数据继续发布
python -m tracker collect || true
# ② 发布：SQLite → data/publish/v1/*.json（含 format_check，校验不过退出码非 0）
python -m data.publish.cli || exit 1
# ③ 推送：HEAD:data 从任意本地分支更新远端 data 分支（jsDelivr CDN 自动缓存）
git add data/publish/v1/ && git commit -m "publish: $(date +%YQ%m)" && git push origin HEAD:data
