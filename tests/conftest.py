"""pytest 公共 fixture"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# 保证仓库根目录在 sys.path（未安装包时也能 import core/storage/...）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import Settings  # noqa: E402
from core.models import City  # noqa: E402
from storage.connection import get_connection  # noqa: E402
from storage.schema import create_tables  # noqa: E402

FAKE_SCRAPER_ENTRY = Path(__file__).parent / "fixtures" / "fake_boss_cdp_raw.py"

CITY_NAMES = ("北京", "上海", "深圳", "杭州", "成都")


@pytest.fixture()
def city_lookup() -> dict[str, City]:
    return {
        name: City(id=i + 1, name=name, province=f"{name}省") for i, name in enumerate(CITY_NAMES)
    }


@pytest.fixture()
def city_id_lookup() -> dict[str, int]:
    return {name: i + 1 for i, name in enumerate(CITY_NAMES)}


@pytest.fixture()
def db_conn(tmp_path):
    """内存级临时库：4 表 + schema_version + 种子数据"""
    conn = get_connection(tmp_path / "test.db")
    create_tables(conn)
    yield conn
    conn.close()


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        raw_output_dir=Path("data/raw"),
        scraper_entry=str(FAKE_SCRAPER_ENTRY),
        python_bin=sys.executable,
        scraper_timeout=5,
        batch_delay_sec=0,
    )


@pytest.fixture()
def sample_scraper_json(tmp_path) -> Path:
    """真实 scraper 格式的 JSON 文件（经仿真 CLI 产出结构）"""
    import json

    payload = {
        "keyword": "后端",
        "city": "北京",
        "total": 3,
        "jobs": [
            {
                "title": "后端开发工程师",
                "salary": "30-60K·15薪",
                "location": "北京·朝阳区·望京",
                "tags": "3-5年 | 本科",
                "boss_name": "示例科技有限公司",
                "skills": "Java | Spring",
                "encrypt_job_id": "sample-encrypt-0001",
                "job_link": "https://www.zhipin.com/job_detail/sample-encrypt-0001.html",
            },
            {
                "title": "Java 开发",
                "salary": "15-16K·14薪",
                "location": "北京·海淀区",
                "tags": "1-3年 | 大专",
                "boss_name": "某公司",
                "skills": "Java",
                "encrypt_job_id": "sample-encrypt-0002",
                "job_link": "",
            },
            {
                "title": "后端实习生",
                "salary": "500-550元/天",
                "location": "北京·朝阳区",
                "tags": "在校生 | 学历不限",
                "boss_name": "实习公司",
                "skills": "",
                "encrypt_job_id": "sample-encrypt-0003",
                "job_link": "",
            },
        ],
    }
    path = tmp_path / "boss_jobs_北京_后端_20260923.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


SNAPSHOT_DATE = date(2026, 9, 23)
