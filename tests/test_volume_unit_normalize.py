"""_normalize_volume_unit 防护测试 — v4.2.4

背景:
  historical_kline.volume 不同数据源单位不一致:
  - build_history.py (baostock) → "股"
  - futu_ingest_service (futu)  → "股"
  - akshare/sina 同步脚本        → "手"

  2026-07-06/07 之间曾因混用写入导致 vol_ratio 计算异常。
  v4.2.4 加 _normalize_volume_unit 自动检测 + 转换防护。

测试覆盖 (不依赖 prod DB, 全部用 monkeypatch):
  - 正常 volume (历史范围内) → 原样返回
  - 缩量 20x+ (akshare 手) → 自动 × 100
  - 放量 20x+ (反向) → 自动 ÷ 100
  - 0 volume → 原样返回
  - 不存在的股票 → 原样返回
  - 异常 stock_code → graceful fallback
"""
import pytest
from unittest.mock import patch

from services.futu_sync_service import _normalize_volume_unit


# 固定测试用历史平均 volume = 100M (代表 baostock "股" 单位)
MOCK_HIST_AVG = 100_000_000


def _mock_query_all_empty(*args, **kwargs):
    """Mock: 返回空 (没历史)"""
    return []


def _mock_query_all_with_history(*args, **kwargs):
    """Mock: 返回 [{avg_v: 100_000_000}]"""
    return [{"avg_v": MOCK_HIST_AVG}]


def test_normal_volume_unchanged(monkeypatch):
    """历史 100M 量级, 写入 50M (50%) → 原样返回"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_with_history)
    result = _normalize_volume_unit("000001", 50_000_000, "2026-08-05")
    assert result == 50_000_000, "normal range should not transform"


def test_unit_mismatch_hand_to_stock(monkeypatch):
    """akshare 手 写到 baostock 股 历史 (1M vs 100M, ratio=0.01) → 自动 × 100"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_with_history)
    result = _normalize_volume_unit("000001", 1_000_000, "2026-08-05")
    assert result == 100_000_000, f"hand→stock should × 100, got {result}"


def test_unit_mismatch_stock_to_hand(monkeypatch):
    """反向 (罕见): 股写到"手"历史 (10B vs 100M, ratio=100) → 自动 ÷ 100"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_with_history)
    result = _normalize_volume_unit("000001", 10_000_000_000, "2026-08-05")
    assert result == 100_000_000, f"stock→hand should ÷ 100, got {result}"


def test_zero_volume_returns_zero(monkeypatch):
    """volume = 0 → 返回 0 (不触发转换)"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_with_history)
    result = _normalize_volume_unit("000001", 0, "2026-08-05")
    assert result == 0


def test_nonexistent_stock_unchanged(monkeypatch):
    """不存在的股票 (query_all 空) → 原样返回"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_empty)
    result = _normalize_volume_unit("999999_NONEXIST", 5_000_000, "2026-08-05")
    assert result == 5_000_000


def test_negative_volume_returns_zero(monkeypatch):
    """负数 volume → 返回 0"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_with_history)
    result = _normalize_volume_unit("000001", -100, "2026-08-05")
    assert result == 0


def test_three_orders_of_magnitude_diff(monkeypatch):
    """差 1000 倍 (手 vs 股) → 触发自动 × 100"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_with_history)
    # hist_avg = 100M, 千分之一 = 100K, 应该 × 100 → 10M
    result = _normalize_volume_unit("000001", 100_000, "2026-08-05")
    assert result == 10_000_000, f"千分之一 → × 100 should be 10M, got {result}"


def test_just_below_threshold_unchanged(monkeypatch):
    """ratio = 0.05 (边界, hist_avg × 5%) → 不转换"""
    monkeypatch.setattr("services.futu_sync_service.query_all", _mock_query_all_with_history)
    # hist_avg = 100M, 5% = 5M, 应该不转换 (ratio > 0.05)
    result = _normalize_volume_unit("000001", 5_000_000, "2026-08-05")
    assert result == 5_000_000, f"边界 5% 不应该转换, got {result}"