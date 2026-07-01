"""Futu 数据接入测试 — 数据库 schema / ingest / fallback / API smoke test

当前阶段先覆盖 Task 1：init_db 应创建 Futu raw 表与唯一索引。
后续任务会继续把 ingest、fallback、API 兼容测试补到这个文件里。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db, query_one



def test_init_db_creates_futu_raw_tables(db):
    init_db()

    quote_table = query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='futu_raw_quote'"
    )
    kline_table = query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='futu_raw_kline'"
    )
    unique_index = query_one(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='uq_futu_raw_kline_bar'"
    )

    assert quote_table is not None
    assert kline_table is not None
    assert unique_index is not None
