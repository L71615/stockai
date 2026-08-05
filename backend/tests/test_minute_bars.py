"""v5.0-beta M6 — 分钟级 K 线接入测试 (30 个 mock 测试)

5 组:
  1. 分支开关 (4 个)
  2. 数据正确性 (8 个)
  3. 缓存交互 (6 个)
  4. 错误降级 (6 个)
  5. 性能 + 边界 (6 个)
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from services.realtime_factor_minute import fetch_recent_bars


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
    """historical_kline fixture — 60 根日 K 线"""
    return [
        {"bar_time": f"2026-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}",
         "open": 10.0 + i * 0.05,
         "high": 10.5 + i * 0.05,
         "low":  9.5 + i * 0.05,
         "close": 10.2 + i * 0.05,
         "volume": 50000 + i * 100}
        for i in range(60)
    ]


# ── 组 1: 分支开关 (4 个) ─────────────────────────────


def test_fetch_returns_daily_when_env_false(monkeypatch, fake_daily_rows):
    """env=false → 走 historical_kline → data_source='historical_daily_fallback'"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_minute._fetch_minute_bars") as m_m, \
         patch("services.realtime_factor_minute._fetch_daily_bars", return_value=fake_daily_rows) as m_d:
        result, source = fetch_recent_bars("600519", limit=240)
    assert source == "historical_daily_fallback"
    assert len(result) == 5  # (closes, highs, lows, opens, volumes)
    assert len(result[0]) == 60
    m_m.assert_not_called()
    m_d.assert_called_once_with("600519", 240)


def test_fetch_returns_minute_when_env_true(monkeypatch, fake_minute_rows):
    """env=true → 走 futu_raw_kline → data_source='futu_1m'"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=fake_minute_rows), \
         patch("services.realtime_factor_minute._fetch_daily_bars") as m_d:
        result, source = fetch_recent_bars("600519", limit=240)
    assert source == "futu_1m"
    assert len(result[0]) == 240
    m_d.assert_not_called()


def test_fetch_env_unset_returns_daily(monkeypatch, fake_daily_rows):
    """env 未设置 → 默认走 daily（alpha 行为）"""
    monkeypatch.delenv("REALTIME_USE_MINUTE_BARS", raising=False)
    with patch("services.realtime_factor_minute._fetch_minute_bars") as m_m, \
         patch("services.realtime_factor_minute._fetch_daily_bars", return_value=fake_daily_rows) as m_d:
        result, source = fetch_recent_bars("600519", limit=240)
    assert source == "historical_daily_fallback"
    m_m.assert_not_called()


def test_fetch_fallback_when_minute_empty(monkeypatch, fake_daily_rows, caplog):
    """env=true 但 minute 表空 → 自动 fallback daily + warning"""
    import logging
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=[]), \
         patch("services.realtime_factor_minute._fetch_daily_bars", return_value=fake_daily_rows):
        with caplog.at_level(logging.WARNING):
            result, source = fetch_recent_bars("600519", limit=240)
    assert source == "historical_daily_fallback"
    assert "fallback" in caplog.text.lower()