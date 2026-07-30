"""v4.1 Phase 2A — 测试 index_sync_service

覆盖:
  - 6 默认指数
  - monkeypatched akshare 拉数 (避免外网)
  - 失败分类 (success / partial_success / failed / skipped)
  - 限频 sleep 验证
"""
from __future__ import annotations

import pytest

from database import query_all


# ─────────────────────── Fixtures ───────────────────────


@pytest.fixture(autouse=True)
def _clean_tables(_test_db_session):
    """每个测试前清 7 张 Phase 2A 表."""
    for tbl in (
        "index_kline",
        "index_sync_runs",
        "index_sync_run_items",
        "etf_kline",
        "etf_sync_runs",
        "etf_sync_run_items",
        "drift_events",
        "factor_snapshot",
    ):
        try:
            from database import execute
            execute(f"DELETE FROM {tbl}")
        except Exception:
            pass


def _fake_index_data(symbol: str, n_rows: int = 5) -> dict:
    """构造伪造 akshare 返回的 dict."""
    base_date = "2024-01-01"
    dates = [f"2024-01-{i + 1:02d}" for i in range(n_rows)]
    closes = [3000.0 + i * 10 for i in range(n_rows)]
    return {
        "code": symbol,
        "dates": dates,
        "opens": [c - 5 for c in closes],
        "highs": [c + 5 for c in closes],
        "lows": [c - 10 for c in closes],
        "closes": closes,
        "volumes": [1e8] * n_rows,
    }


# ─────────────────────── Tests ───────────────────────


def test_init_db_creates_index_kline_and_sync_tables():
    from database import query_all as qa
    names = {r["name"] for r in qa("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "index_kline" in names
    assert "index_sync_runs" in names
    assert "index_sync_run_items" in names


def test_load_targets_returns_six_default_indices():
    from backend.services.index_sync_service import DEFAULT_INDICES, IndexSyncService

    svc = IndexSyncService()
    targets = svc.load_targets()
    assert len(targets) == 6
    codes = [t["code"] for t in targets]
    # 沪深300/中证500/创业板/上证50/中证1000/科创50
    assert "sh000300" in codes
    assert "sz399006" in codes
    for c in codes:
        assert c.startswith(("sh", "sz")), f"unexpected prefix: {c}"


def test_fetch_one_upserts_rows(monkeypatch):
    from backend.services.index_sync_service import IndexSyncService
    from database import execute

    svc = IndexSyncService()

    calls = {"count": 0}

    def fake_get(symbol, days):
        calls["count"] += 1
        return _fake_index_data(symbol, n_rows=3)

    monkeypatch.setattr(
        "backend.services.index_sync_service.get_index_kline",
        fake_get,
    )

    rows_written = svc._fetch_one("sh000300", days=10)
    assert rows_written == 3
    rows = query_all(
        "SELECT * FROM index_kline WHERE symbol = 'sh000300' ORDER BY trade_date"
    )
    assert len(rows) == 3
    assert rows[0]["name"] == "沪深300"
    assert abs(rows[0]["close"] - 3000.0) < 1e-6


def test_run_sync_happy_path_writes_audit(monkeypatch):
    """6 指数 × 5 行 = 30 行入表, runs 写 success_count=6."""
    from backend.services.index_sync_service import IndexSyncService, run_index_sync

    def fake_get(symbol, days):
        return _fake_index_data(symbol, n_rows=5)

    monkeypatch.setattr(
        "backend.services.index_sync_service.get_index_kline",
        fake_get,
    )
    # 强制极短 sleep, 避免测试变慢
    result = run_index_sync(run_type="full_seed", days_back=10, sleep_seconds=0.0)
    assert result["status"] == "success"
    assert result["success_count"] == 6
    assert result["failed_count"] == 0
    assert result["target_count"] == 6

    rows = query_all("SELECT COUNT(*) AS c FROM index_kline")
    assert rows[0]["c"] == 30  # 6 × 5

    run_rows = query_all(
        "SELECT * FROM index_sync_runs ORDER BY id DESC LIMIT 1"
    )
    assert run_rows[0]["status"] == "success"
    assert run_rows[0]["success_count"] == 6


def test_run_sync_partial_failure_classifies(monkeypatch):
    from backend.services.index_sync_service import run_index_sync

    def fake_get(symbol, days):
        # 前 2 失败, 后 4 OK
        if symbol in ("sh000300", "sh000905"):
            return {"error": "rate limit", "code": symbol}
        return _fake_index_data(symbol, n_rows=3)

    monkeypatch.setattr(
        "backend.services.index_sync_service.get_index_kline",
        fake_get,
    )
    result = run_index_sync(sleep_seconds=0.0)
    # 2/6 = 33% failed < 50% → partial_success, 不发 alert
    assert result["status"] == "partial_success"
    assert result["failed_count"] == 2
    assert result["success_count"] == 4
    assert result["alert_sent"] is False


def test_run_sync_rate_limit_sleeps(monkeypatch):
    """sleep_seconds 必须 >= 0.1 默认 (Phase 2A fixture)."""
    import time

    from backend.services.index_sync_service import IndexSyncService

    svc = IndexSyncService()
    sleep_calls = []

    monkeypatch.setattr(
        "backend.services.index_sync_service.get_index_kline",
        lambda s, d: _fake_index_data(s, n_rows=1),
    )

    def fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(
        "backend.services.base_vendor_sync.time.sleep",
        fake_sleep,
    )

    # 默认 sleep_seconds=0.2
    svc.run_sync(run_type="nightly", days_back=10)
    # 6 个 targets → 6 次 sleep
    assert len(sleep_calls) == 6
    assert all(s >= 0.1 for s in sleep_calls)


def test_get_index_kline_empty_returns_error(monkeypatch):
    """akshare 返回空 DataFrame → 走 fallback / error."""
    import pandas as pd

    from backend.services.akshare_adapter import get_index_kline

    def fake_ak_stock_zh_index_daily(**kwargs):
        return pd.DataFrame()  # 空

    monkeypatch.setattr(
        "akshare.stock_zh_index_daily",
        fake_ak_stock_zh_index_daily,
        raising=False,
    )
    result = get_index_kline("sh000300", days=10)
    assert "error" in result
    assert result["code"] == "sh000300"
