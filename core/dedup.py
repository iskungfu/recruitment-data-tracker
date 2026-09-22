"""去重 — 03-module-interfaces.md §13 交付矩阵保留模块

实现集中在 core.cleansing.dedup_jobs，本模块只做 re-export 以保持接口矩阵完整。
"""

from core.cleansing import dedup_jobs

__all__ = ["dedup_jobs"]
