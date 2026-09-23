#!/usr/bin/env bash
# 季度发布一键脚本 — 06-website-architecture-v1.0.md §6.1
# 流程：采集（tracker 模块未实现则跳过，发布现有库数据）→ 生成 6 个发布 JSON → 提交并推送到 data 分支
# 用法：在仓库任意目录执行  bash scripts/quarterly_publish.sh
set -uo pipefail
cd "$(dirname "$0")/.."

# ① 采集：需本机 Chrome（CDP）；tracker 模块尚未实现，存在才执行，否则显式告警并继续发布现有库数据
echo "[1/3] 采集（CDP）..."
if python -c "import importlib; importlib.import_module('tracker')" 2>/dev/null; then
  python -m tracker collect
else
  echo "警告：tracker 模块未实现，跳过采集，将发布现有库数据" >&2
fi

# ② 发布：SQLite → data/publish/v1/*.json（含 format_check，校验不过退出码非 0）
echo "[2/3] 生成发布 JSON..."
python -m data.publish.cli || exit 1

# ③ 推送：无变更时跳过 commit 不报错；HEAD:data 从任意本地分支更新远端 data 分支（jsDelivr CDN 自动缓存）
echo "[3/3] 提交并推送 data 分支..."
git add data/publish/v1/
git diff --cached --quiet || git commit -m "publish: $(date +%YQ%m)" && git push origin HEAD:data
