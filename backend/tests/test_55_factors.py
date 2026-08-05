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


# ── 组 2: 55 因子分发 (6 个) ──────────────────────────


def test_compute_returns_55_factors_default(test_db, monkeypatch, fake_daily_rows):
    """默认 factor_names=None → 算全部 MINUTE_FACTOR_REGISTRY (55+)"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows):
        (closes, highs, lows, opens, volumes), _ = fetch_recent_bars("600519", 240)
        factors = compute_factors_with_cache(
            code="600519", closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
        )
    # MINUTE_FACTOR_REGISTRY 55 因子 + compute_minute_factors 注入 close/open/high/low 等辅助字段
    assert len(factors) >= 55
    assert "ma5" in factors
    assert "rsrs" in factors  # needs_highs_lows 因子
    assert "vol_ma5" in factors  # needs_volume 因子
    assert "klen" in factors  # needs_opens + highs_lows 因子


def test_compute_needs_volume_factor(test_db, monkeypatch, fake_daily_rows):
    """needs_volume 因子(如 vol_ma5) 应正确传 volumes"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows):
        (closes, highs, lows, opens, volumes), _ = fetch_recent_bars("600519", 240)
        factors = compute_factors_with_cache(
            code="600519", closes=closes, highs=highs, lows=lows, opens=opens,
            volumes=volumes, factor_names=["vol_ma5"],
        )
    assert "vol_ma5" in factors
    assert factors["vol_ma5"] is not None


def test_compute_needs_hilo_factor(test_db, monkeypatch, fake_daily_rows):
    """needs_highs_lows 因子(如 rsrs, atr_14) 应正确传 highs/lows"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows):
        (closes, highs, lows, opens, volumes), _ = fetch_recent_bars("600519", 240)
        factors = compute_factors_with_cache(
            code="600519", closes=closes, highs=highs, lows=lows, opens=opens,
            volumes=volumes, factor_names=["rsrs", "atr_14"],
        )
    assert "rsrs" in factors
    assert "atr_14" in factors


def test_compute_needs_open_factor(test_db, monkeypatch, fake_daily_rows):
    """needs_opens 因子(如 klen) 应正确传 opens"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows):
        (closes, highs, lows, opens, volumes), _ = fetch_recent_bars("600519", 240)
        factors = compute_factors_with_cache(
            code="600519", closes=closes, highs=highs, lows=lows, opens=opens,
            volumes=volumes, factor_names=["klen"],
        )
    assert "klen" in factors


def test_compute_unknown_factor_raises():
    """factor_names 含未知因子 → ValueError"""
    from services.factor_service import compute_minute_factors
    with pytest.raises(ValueError, match="未知因子名"):
        compute_minute_factors(
            code="600519", closes=[10.0]*30, factor_names=["nonexistent_factor"],
        )


def test_compute_factor_names_filter(test_db, monkeypatch, fake_daily_rows):
    """factor_names 指定子集 → 只算子集"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows):
        (closes, highs, lows, opens, volumes), _ = fetch_recent_bars("600519", 240)
        factors = compute_factors_with_cache(
            code="600519", closes=closes, highs=highs, lows=lows, opens=opens,
            volumes=volumes, factor_names=["ma5", "ma10"],
        )
    assert set(factors.keys()) == {"ma5", "ma10"}


# ── 组 3: Cache 迁移 (4 个) ───────────────────────────


def test_cache_hit_skips_compute(test_db, monkeypatch):
    """cache 全命中 → 不调 compute_realtime_factors"""
    cached = {"ma5": 11.0, "ma10": 10.5, "ma20": 10.0}
    with patch("services.realtime_factor_cache.get_all_cached", return_value=cached), \
         patch("services.realtime_factor_cache.compute_realtime_factors") as m_compute:
        result = compute_factors_with_cache(
            code="600519", closes=[10.0]*30, factor_names=["ma5", "ma10", "ma20"],
        )
    m_compute.assert_not_called()
    assert result["ma5"] == 11.0
    assert result["ma10"] == 10.5


def test_cache_empty_triggers_compute(test_db, monkeypatch):
    """cache 空 → 调 compute_realtime_factors + 写回"""
    with patch("services.realtime_factor_cache.get_all_cached", return_value={}), \
         patch("services.realtime_factor_cache.compute_realtime_factors",
               return_value={"ma5": 11.0}) as m_compute, \
         patch("services.realtime_factor_cache.set_cached_factor") as m_set:
        result = compute_factors_with_cache(
            code="600519", closes=[10.0]*30, factor_names=["ma5"],
        )
    m_compute.assert_called_once()
    m_set.assert_called_once_with("600519", "ma5", 11.0)
    assert result["ma5"] == 11.0


def test_cache_partial_hit_merges(test_db, monkeypatch):
    """cache 部分命中 → 补全缺失的"""
    cached = {"ma5": 11.0}  # ma10 缺失
    with patch("services.realtime_factor_cache.get_all_cached", return_value=cached), \
         patch("services.realtime_factor_cache.compute_realtime_factors",
               return_value={"ma10": 10.5}) as m_compute:
        result = compute_factors_with_cache(
            code="600519", closes=[10.0]*30, factor_names=["ma5", "ma10"],
        )
    assert m_compute.called
    assert result["ma5"] == 11.0
    assert result["ma10"] == 10.5


def test_cache_skips_none_values(test_db, monkeypatch):
    """compute 返 None 的因子: 上层调 set_cached_factor(code, name, None),由 set_cached_factor 内部短路(测传参约定)"""
    with patch("services.realtime_factor_cache.get_all_cached", return_value={}), \
         patch("services.realtime_factor_cache.compute_realtime_factors",
               return_value={"ma5": None}), \
         patch("services.realtime_factor_cache.set_cached_factor") as m_set:
        result = compute_factors_with_cache(
            code="600519", closes=[10.0]*30, factor_names=["ma5"],
        )
    assert result["ma5"] is None
    # 上层传 None 给 set_cached_factor,内部短路由 set_cached_factor 自己负责(M6 已覆盖)
    m_set.assert_called_once_with("600519", "ma5", None)


# ── 组 4: Router 兼容 (4 个) ──────────────────────────


def _make_test_client():
    """最小 FastAPI app,挂 realtime_factor router(无需 JWT middleware)"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.realtime_factor import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_router_returns_data_source_field(monkeypatch, fake_minute_rows):
    """router 应把 data_source 透传到 API 响应"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    client = _make_test_client()
    with patch("services.realtime_factor_cache._fetch_minute_bars", return_value=fake_minute_rows), \
         patch("services.realtime_factor_cache.compute_factors_with_cache",
               return_value={"ma5": 11.0}):
        resp = client.get("/api/realtime/factor/600519")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_source"] == "futu_1m"
    assert "factors" in body


def test_router_data_source_fallback(monkeypatch, fake_daily_rows):
    """env=false → router data_source 应是 'historical_daily_fallback'"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    client = _make_test_client()
    with patch("services.realtime_factor_cache._fetch_daily_bars", return_value=fake_daily_rows), \
         patch("services.realtime_factor_cache.compute_factors_with_cache",
               return_value={"ma5": 11.0}):
        resp = client.get("/api/realtime/factor/600519")
    assert resp.status_code == 200
    assert resp.json()["data_source"] == "historical_daily_fallback"


def test_router_404_when_no_data(monkeypatch):
    """bar_count == 0 → router 抛 404"""
    client = _make_test_client()
    with patch("services.realtime_factor_cache._fetch_daily_bars", return_value=[]):
        resp = client.get("/api/realtime/factor/600519")
    assert resp.status_code == 404


def test_router_503_on_fetch_failure(monkeypatch):
    """fetch_recent_bars 抛异常 → router 503"""
    client = _make_test_client()
    # router 用 `from services.realtime_factor_cache import fetch_recent_bars` 导入到 router 命名空间
    # 必须 patch router 模块的 import,不是原模块
    with patch("routers.realtime_factor.fetch_recent_bars",
               side_effect=RuntimeError("DB 故障")):
        resp = client.get("/api/realtime/factor/600519")
    assert resp.status_code == 503


# ── 组 5: 错误降级 (2 个) ────────────────────────────


def test_factor_compute_exception_isolated():
    """单只 factor 抛异常不影响其它只 — compute_minute_factors 内部 try/except"""
    from services.factor_service import compute_minute_factors, MINUTE_FACTOR_REGISTRY

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    # 临时替换 ma5 的 fn,保留其它元组字段
    original = MINUTE_FACTOR_REGISTRY["ma5"]
    new_entry = (boom, *original[1:])
    with patch.dict(MINUTE_FACTOR_REGISTRY, {"ma5": new_entry}):
        factors = compute_minute_factors(
            code="600519", closes=[10.0]*30, factor_names=["ma5", "ma10"],
        )
    assert factors["ma5"] is None  # 异常被捕获
    assert "ma10" in factors  # 其它因子照算


def test_close_too_short_returns_empty():
    """closes < 5 根 → compute_realtime_factors 返空 dict"""
    factors = compute_realtime_factors(
        code="600519", closes=[10.0, 10.5, 11.0], volumes=[100, 200, 300],
    )
    assert factors == {}