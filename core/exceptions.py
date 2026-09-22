"""异常体系 — 03-module-interfaces.md §12

v1.1 变更：
- 新增 ScraperError / ScraperTimeoutError / SchemaIncompatibleError（采集层）
- 移除 FetchError / AntiCrawlError / AccountBannedError（不再直调 BOSS API，
  反爬逻辑由 boss-zhipin-scraper 内部处理）
"""

from __future__ import annotations


class TrackerError(Exception):
    """基类"""


class ConfigError(TrackerError):
    """配置错误（YAML 格式、缺失字段）"""


class SalaryParseError(TrackerError):
    """薪资解析失败，raw 字段保留原文"""

    def __init__(self, raw: str, message: str = ""):
        self.raw = raw
        super().__init__(f"薪资解析失败: {raw!r} {message}".strip())


class SourceNotConfiguredError(TrackerError):
    """平台城市编码未配置（如 TODO_W2_BOSS_BEIJING 未替换）"""


class DBConstraintError(TrackerError):
    """UNIQUE 约束冲突（理论上 dedup 已处理，仅 debug 出现）"""


# ── 采集层（v1.1）──


class ScraperError(TrackerError):
    """boss-zhipin-scraper CLI 执行失败（非零退出码 / 输出为空）"""


class ScraperTimeoutError(ScraperError):
    """scraper 子进程超时（>300s 无响应）"""


class SchemaIncompatibleError(TrackerError):
    """scraper JSON 输出字段不兼容——上游输出格式变更"""
