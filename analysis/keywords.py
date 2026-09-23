"""词频分析 — Week 3

对 job_snapshot.jd_fulltext 做 jieba 分词，输出高频技术词。
注意：JD 字段名为 jd_fulltext（不是 jd），见 0001_initial.sql。
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

import jieba

#: 停用词：任务指定（的/了/在/是/和/与/及/或/等）+ 高频虚词
STOPWORDS: frozenset[str] = frozenset(
    {
        "的", "了", "在", "是", "和", "与", "及", "或", "等",
        "有", "无", "为", "对", "到", "于", "你", "我", "他", "她", "它",
        "我们", "他们", "以及", "或者", "并且", "以上", "以下", "之", "其",
        "将", "会", "能", "可以", "需要", "进行", "相关", "工作", "负责",
    }
)

#: 至少含一个中日韩文字或拉丁字母才计为有效词（过滤纯标点 / 纯数字）
_VALID_TOKEN_RE = re.compile(r"[一-鿿A-Za-z]")


def _iter_jd_texts(db_path: str | Path) -> list[str]:
    """读出全部非空 JD 全文。"""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT jd_fulltext FROM job_snapshot "
            "WHERE jd_fulltext IS NOT NULL AND jd_fulltext != ''"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def tokenize(text: str) -> list[str]:
    """单条文本 → 有效词列表（过滤单字、标点、纯数字、停用词）。"""
    tokens: list[str] = []
    for word in jieba.cut(text):
        w = word.strip()
        if len(w) < 2:
            continue
        if w in STOPWORDS:
            continue
        if not _VALID_TOKEN_RE.search(w):
            continue
        tokens.append(w)
    return tokens


def analyze_keywords(db_path: str | Path, top_n: int = 50) -> list[tuple[str, int]]:
    """JD 词频统计：返回 [(词, 频次), ...]，按频次降序，最多 top_n 条。

    数据源为 job_snapshot.jd_fulltext 全量非空记录；分词用 jieba.cut。
    过滤规则：单字、停用词（的/了/在/是/和/与/及/或/等 等）、
    纯标点与纯数字。结果确定性：同频次按词面字典序（Counter.most_common
    不保证次序稳定，这里显式排序）。

    Raises:
        FileNotFoundError: db_path 不存在时抛出（不静默创建空库文件）。
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")
    counter: Counter[str] = Counter()
    for jd in _iter_jd_texts(db_path):
        counter.update(tokenize(jd))
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:top_n]
