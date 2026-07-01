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


def test_load_sync_targets_merges_watchlist_and_holdings(monkeypatch):
    from services import futu_sync_service
    from services.futu_sync_service import _load_sync_targets

    def fake_query_all(sql, params=()):
        if "FROM watchlist" in sql:
            return [{"stock_code": "600519"}, {"stock_code": "000001"}]
        if "FROM holdings" in sql:
            return [{"stock_code": "000001"}, {"stock_code": "300750"}]
        return []

    monkeypatch.setattr(futu_sync_service, "query_all", fake_query_all)
    result = _load_sync_targets("watchlist+holdings")

    assert result == [
        {"code": "000001", "from_watchlist": True, "from_holdings": True},
        {"code": "300750", "from_watchlist": False, "from_holdings": True},
        {"code": "600519", "from_watchlist": True, "from_holdings": False},
    ]


def test_summarize_run_status_values():
    from services.futu_sync_service import _summarize_run

    assert _summarize_run(3, 3, 0) == "success"
    assert _summarize_run(3, 2, 1) == "partial_success"
    assert _summarize_run(3, 0, 3) == "failed"
    assert _summarize_run(0, 0, 0) == "skipped"
