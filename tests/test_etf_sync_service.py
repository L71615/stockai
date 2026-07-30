"""v4.1 Phase 2A — 测试 etf_sync_service

覆盖:
  - 11 默认 ETF
  - monkeypatched fund_etf_hist_em 拉数 (避免外网 + 中文列)
  - 失败分类 (success / partial_success / failed / skipped)
  - 空 universe + 全成功路径
"""
from __future__ import annotations

import pandas as pd
import pytest

from database import query_all


# ─────────────────────── Fixtures ───────────────────────

@pytest.fixture(autouse=True)
def _clean_tables(_test_db_session):
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


def _fake_etf_df(code: str, n_rows: int = 5) -> "pd.DataFrame":
    """构造 fund_etf_hist_em 风格返回 — 中文列名."""
    dates = [f"2024-01-{i + 1:02d}" for i in range(n_rows)]
    closes = [3.5 + i * 0.01 for i in range(n_rows)]
    return pd.DataFrame({
        "日期": dates,
        "开盘": [c - 0.005 for c in closes],
        "最高": [c + 0.005 for c in closes],
        "最低": [c - 0.01 for c in closes],
        "收盘": closes,
        "成交量": [1e6] * n_rows,
    })


# ─────────────────────── Tests ───────────────────────


def test_init_db_creates_etf_kline_and_sync_tables():
    names = {r["name"] for r in query_all(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "etf_kline" in names
    assert "etf_sync_runs" in names
    assert "etf_sync_run_items" in names


def test_load_targets_returns_eleven_default_etfs():
    from backend.services.etf_sync_service import DEFAULT_ETFS, ETFSyncService

    svc = ETFSyncService()
    targets = svc.load_targets()
    assert len(targets) == 11
    codes = [t["code"] for t in targets]
    assert "510300" in codes
    assert "159915" in codes
    assert "518880" in codes  # 黄金ETF


def test_fetch_one_upserts_via_chinese_columns(monkeypatch):
    """fund_etf_hist_em 中文列名('日期'/'开盘'/)写入 + name 正确."""
    from backend.services.etf_sync_service import ETFSyncService

    svc = ETFSyncService()

    monkeypatch.setattr(
        "backend.services.etf_sync_service.get_etf_kline",
        lambda c, days: {
            "code": c,
            "dates": _fake_etf_df(c, 3)["日期"].astype(str).tolist(),
            "opens": _fake_etf_df(c, 3)["开盘"].astype(float).tolist(),
            "highs": _fake_etf_df(c, 3)["最高"].astype(float).tolist(),
            "lows":  _fake_etf_df(c, 3)["最低"].astype(float).tolist(),
            "closes": _fake_etf_df(c, 3)["收盘"].astype(float).tolist(),
            "volumes": _fake_etf_df(c, 3)["成交量"].astype(float).tolist(),
        },
    )

    rows = svc._fetch_one("510300", days=10)
    assert rows == 3
    rs = query_all(
        "SELECT * FROM etf_kline WHERE code='510300' ORDER BY trade_date"
    )
    assert len(rs) == 3
    assert rs[0]["name"] == "沪深300ETF"
    assert abs(rs[0]["close"] - 3.5) < 1e-6


def test_run_sync_full_seed_writes_audit(monkeypatch):
    """11 ETF × 任意行 → 至少 audit 写成功."""
    from backend.services.etf_sync_service import run_etf_sync

    def fake_get(code, days):
        return {
            "code": code,
            "dates": [f"2024-01-{i + 1:02d}" for i in range(3)],
            "opens": [3.4] * 3,
            "highs": [3.6] * 3,
            "lows":  [3.3] * 3,
            "closes": [3.5] * 3,
            "volumes": [1e6] * 3,
        }

    monkeypatch.setattr(
        "backend.services.etf_sync_service.get_etf_kline",
        fake_get,
    )

    result = run_etf_sync(run_type="full_seed", days_back=10, sleep_seconds=0.0)
    assert result["status"] == "success"
    assert result["success_count"] == 11

    rows = query_all("SELECT COUNT(*) AS c FROM etf_kline")
    assert rows[0]["c"] == 33  # 11 × 3

    audit = query_all(
        "SELECT * FROM etf_sync_runs ORDER BY id DESC LIMIT 1"
    )
    assert audit[0]["status"] == "success"
    assert audit[0]["run_type"] == "full_seed"


def test_run_sync_partial_failure(monkeypatch):
    """3/11 失败 → partial_success, alert < 50% 不发."""
    from backend.services.etf_sync_service import run_etf_sync

    failed_codes = {"510300", "510500", "159915"}

    def fake_get(code, days):
        if code in failed_codes:
            return {"error": "akshare rate limit", "code": code}
        return {
            "code": code,
            "dates": ["2024-01-01"],
            "opens": [3.4], "highs": [3.6], "lows": [3.3],
            "closes": [3.5], "volumes": [1e6],
        }

    monkeypatch.setattr(
        "backend.services.etf_sync_service.get_etf_kline",
        fake_get,
    )

    result = run_etf_sync(sleep_seconds=0.0)
    assert result["status"] == "partial_success"
    assert result["failed_count"] == 3
    assert result["success_count"] == 8
    # 3/11 ≈ 27% < 50% → 不告警
    assert result["alert_sent"] is False


def test_run_sync_zero_targets_returns_skipped():
    """空 universe → status='skipped', 不调 AK."""
    from backend.services.etf_sync_service import ETFSyncService

    svc = ETFSyncService(etfs=[])
    result = svc.run_sync(run_type="nightly", days_back=10, sleep_seconds=0.0)
    assert result["status"] == "skipped"
    assert result["target_count"] == 0
    assert result["success_count"] == 0
