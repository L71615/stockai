"""Futu P1 同步系统测试 — 状态表 / 目标集合 / 编排 / 告警 / 脚本 / 调度。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db, query_one
from services.futu_sync_service import _load_sync_targets, _summarize_run


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
    assert _summarize_run(3, 3, 0) == "success"
    assert _summarize_run(3, 2, 1) == "partial_success"
    assert _summarize_run(3, 0, 3) == "failed"
    assert _summarize_run(0, 0, 0) == "skipped"


def test_run_intraday_sync_calls_quote_and_minute(monkeypatch):
    from services import futu_sync_service
    from services.futu_sync_service import run_intraday_sync
    calls = []

    monkeypatch.setattr(futu_sync_service, "_load_sync_targets", lambda scope: [
        {"code": "600519", "from_watchlist": True, "from_holdings": False}
    ])
    monkeypatch.setattr(futu_sync_service, "sync_quote", lambda code: calls.append(("quote", code)) or {"code": code, "source": "futu"})
    monkeypatch.setattr(futu_sync_service, "sync_minute_kline", lambda code, count=240: calls.append(("minute", code)) or {"code": code, "source": "futu"})
    monkeypatch.setattr(futu_sync_service, "_record_run", lambda *args, **kwargs: 1)
    monkeypatch.setattr(futu_sync_service, "_record_item_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(futu_sync_service, "_finalize_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(futu_sync_service, "_maybe_alert", lambda *args, **kwargs: False)

    result = run_intraday_sync()

    assert calls == [("quote", "600519"), ("minute", "600519")]
    assert result["status"] == "success"


def test_run_nightly_sync_calls_daily(monkeypatch):
    from services import futu_sync_service
    from services.futu_sync_service import run_nightly_sync
    calls = []

    monkeypatch.setattr(futu_sync_service, "_load_sync_targets", lambda scope: [
        {"code": "600519", "from_watchlist": True, "from_holdings": True}
    ])
    monkeypatch.setattr(futu_sync_service, "sync_daily_kline", lambda code, count=200: calls.append(("daily", code)) or {"code": code, "source": "futu"})
    monkeypatch.setattr(futu_sync_service, "_record_run", lambda *args, **kwargs: 2)
    monkeypatch.setattr(futu_sync_service, "_record_item_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(futu_sync_service, "_finalize_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(futu_sync_service, "_maybe_alert", lambda *args, **kwargs: False)

    result = run_nightly_sync()

    assert calls == [("daily", "600519")]
    assert result["status"] == "success"
