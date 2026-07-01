"""Futu P1 同步系统测试 — 状态表 / 目标集合 / 编排 / 告警 / 脚本 / 调度。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db, query_one


def test_init_db_creates_futu_sync_tables(db):
    init_db()

    runs_table = query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='futu_sync_runs'"
    )
    items_table = query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='futu_sync_run_items'"
    )

    assert runs_table is not None
    assert items_table is not None
