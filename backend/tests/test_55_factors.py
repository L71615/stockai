"""v5.0-beta M7 — 55 因子完整接入测试 (20 个 mock 测试)

5 组:
  1. 5 元组解包 (4 个)
  2. 55 因子分发 (6 个)
  3. Cache 迁移 (4 个)
  4. Router 兼容 (4 个)
  5. 错误降级 (2 个)
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from services.realtime_factor_cache import (
    compute_factors_with_cache,
    compute_realtime_factors,
    fetch_recent_bars,
    get_all_cached,
)


# ── 公共 fixture ──────────────────────────────────────


@pytest.fixture
def fake_minute_rows():
    """futu_raw_kline fixture — 240 根 1m K 线"""
    return [
        {"bar_time": f"2026-08-05 14:{(i // 60):02d}:{(i % 60):02d}",
         "open": 10.0 + i * 0.01,
         "high": 10.5 + i * 0.01,
         "low":  9.5 + i * 0.01,
         "close": 10.2 + i * 0.01,
         "volume": 1000 + i}
        for i in range(240)
    ]


@pytest.fixture
def fake_daily_rows():
    """historical_kline fixture — 240 根日 K 线"""
    return [
        {"bar_time": f"2026-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}",
         "open": 10.0 + i * 0.05,
         "high": 10.5 + i * 0.05,
         "low":  9.5 + i * 0.05,
         "close": 10.2 + i * 0.05,
         "volume": 50000 + i * 100}
        for i in range(240)
    ]


@pytest.fixture
def all_55_factor_names():
    """MINUTE_FACTOR_REGISTRY 的 55 因子名清单"""
    from services.factor_service import MINUTE_FACTOR_REGISTRY
    return list(MINUTE_FACTOR_REGISTRY.keys())


# ── 组 1: 5 元组解包 (4 个) ──────────────────────────


def test_fetch_returns_5_tuple_when_env_false(monkeypatch, fake_daily_rows):
    """env=false → 返 ((closes, highs, lows, opens, volumes), 'historical_daily_fallback')"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_cache._fetch_minute_bars") as m_m, \
         patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows) as m_d:
        result, source = fetch_recent_bars("600519", limit=240)
    assert source == "historical_daily_fallback"
    assert isinstance(result, tuple)
    assert len(result) == 5  # (closes, highs, lows, opens, volumes)
    closes, highs, lows, opens, volumes = result
    assert len(closes) == 240
    assert len(highs) == 240
    assert len(lows) == 240
    assert len(opens) == 240
    assert len(volumes) == 240
    m_m.assert_not_called()
    m_d.assert_called_once_with("600519", 240)


def test_fetch_returns_5_tuple_when_env_true(monkeypatch, fake_minute_rows):
    """env=true + minute 有数据 → 返 ((5 元组), 'futu_1m')"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_cache._fetch_minute_bars", return_value=fake_minute_rows), \
         patch("services.realtime_factor_cache._fetch_daily_bars") as m_d:
        result, source = fetch_recent_bars("600519", limit=240)
    assert source == "futu_1m"
    closes, highs, lows, opens, volumes = result
    assert len(closes) == 240
    assert len(highs) == 240
    m_d.assert_not_called()


def test_fetch_fallback_to_5_tuple_when_minute_empty(monkeypatch, fake_daily_rows, caplog):
    """env=true 但 minute 空 → fallback 日级 + 5 元组"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_cache._fetch_minute_bars", return_value=[]), \
         patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows):
        with caplog.at_level(logging.WARNING, logger="services.realtime_factor_cache"):
            result, source = fetch_recent_bars("600519", limit=240)
    assert source == "historical_daily_fallback"
    closes, highs, lows, opens, volumes = result
    assert len(closes) == 240
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


def test_to_series_filters_none_values():
    """_to_series 应过滤 close=None 的行 + 5 元组顺序"""
    from services.realtime_factor_cache import _to_series
    rows = [
        {"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100},
        {"open": None, "high": None, "low": None, "close": None, "volume": None},
        {"open": 11.0, "high": 11.5, "low": 10.5, "close": 11.2, "volume": 200},
    ]
    closes, highs, lows, opens, volumes = _to_series(rows)
    assert closes == [10.2, 11.2]
    assert highs == [10.5, 11.5]
    assert lows == [9.5, 10.5]
    assert opens == [10.0, 11.0]
    assert volumes == [100, 200]