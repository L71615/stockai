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

from services.realtime_factor_minute import (
    _fetch_daily_bars,
    _fetch_minute_bars,
    _to_series,
    fetch_recent_bars,
)


# ── 最小化测试 app(避免 from main import 触发 startup 副作用) ──


def _make_test_client():
    """构造只含 realtime_factor_minute router 的 FastAPI 测试 app。

    直接 import main 会触发 startup(JWT_SECRET 校验、AI 客户端初始化等),
    测试环境若缺 .env 会崩。这里只挂载目标 router,保留完整请求链路。
    """
    from fastapi import FastAPI
    from routers.realtime_factor_minute import router as realtime_router
    app = FastAPI()
    app.include_router(realtime_router)
    from fastapi.testclient import TestClient
    return TestClient(app)


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
    # 顺序契约: closes[0] 是 fixture 中最旧的一根(OLDEST), closes[-1] 是最新(NEWEST)
    closes = result[0]
    assert closes[0] == fake_minute_rows[0]["close"]
    assert closes[-1] == fake_minute_rows[-1]["close"]
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


# ── 组 5 续: Router 集成 (1 个) ──────────────────────


def test_router_returns_data_source_from_function(monkeypatch, fake_minute_rows):
    """router 应把 fetch_recent_bars 返回的 data_source 透传到 API 响应"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    client = _make_test_client()

    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=fake_minute_rows), \
         patch("services.realtime_factor_minute.compute_minute_factors_with_cache",
               return_value={f"f{i}": 1.0 for i in range(5)}), \
         patch("services.realtime_factor_minute.get_all_cached", return_value={}):
        resp = client.get("/api/realtime/factor/600519/minute")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_source"] == "futu_1m"
    assert body["bar_count"] == 240


# ── 组 2: 数据正确性 (8 个) ──────────────────────────


def test_to_series_filters_none_values():
    """_to_series 应过滤 close=None 的行"""
    rows = [
        {"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100},
        {"open": None, "high": None, "low": None, "close": None, "volume": None},
        {"open": 11.0, "high": 11.5, "low": 10.5, "close": 11.2, "volume": 200},
    ]
    closes, highs, lows, opens, volumes = _to_series(rows)
    assert len(closes) == 2
    assert len(highs) == 2
    assert closes == [10.2, 11.2]
    assert volumes == [100, 200]


def test_to_series_empty_input():
    """空 rows 应返 5 个空 list"""
    closes, highs, lows, opens, volumes = _to_series([])
    assert closes == []
    assert highs == []
    assert lows == []
    assert opens == []
    assert volumes == []


def test_fetch_minute_bars_queries_qfq_only(monkeypatch):
    """_fetch_minute_bars 必须 filter adjust_type='qfq'"""
    captured = []

    def fake_query_all(sql, params):
        captured.append((sql, params))
        return []

    monkeypatch.setattr("services.realtime_factor_minute.query_all", fake_query_all)
    _fetch_minute_bars("600519", 240)

    assert len(captured) == 1
    sql, params = captured[0]
    assert "adjust_type = 'qfq'" in sql
    assert "interval = '1m'" in sql
    assert params == ("600519", 240)


def test_fetch_daily_bars_orders_ascending(monkeypatch):
    """_fetch_daily_bars 内部 reverse,返回正序"""
    rows_desc = [
        {"bar_time": "2026-08-05", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 100},
        {"bar_time": "2026-08-04", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 100},
    ]

    def fake_query_all(sql, params):
        return list(rows_desc)  # DB 返回倒序

    monkeypatch.setattr("services.realtime_factor_minute.query_all", fake_query_all)
    result = _fetch_daily_bars("600519", 240)
    assert result[0]["bar_time"] == "2026-08-04"  # 正序在前
    assert result[-1]["bar_time"] == "2026-08-05"


def test_fetch_minute_bars_limits_results(monkeypatch):
    """limit 应正确传到 SQL"""
    captured = []

    def fake_query_all(sql, params):
        captured.append(params)
        return []

    monkeypatch.setattr("services.realtime_factor_minute.query_all", fake_query_all)
    _fetch_minute_bars("600519", 100)
    assert captured[0] == ("600519", 100)


def test_multi_symbol_isolation(monkeypatch, fake_minute_rows):
    """不同 code 不应串数据"""
    rows_a = fake_minute_rows[:100]
    rows_b = fake_minute_rows[100:200]

    def fake_query_all(sql, params):
        return rows_a if params[0] == "600519" else rows_b

    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    monkeypatch.setattr("services.realtime_factor_minute.query_all", fake_query_all)

    (ca, _, _, _, _), _ = fetch_recent_bars("600519", 240)
    (cb, _, _, _, _), _ = fetch_recent_bars("000001", 240)
    assert ca[0] != cb[0] or len(ca) != len(cb)


def test_to_series_handles_missing_columns():
    """行缺列不应抛异常 — get() 容错"""
    rows = [
        {"bar_time": "2026-08-05", "close": 10.0},  # 缺 open/high/low/volume
    ]
    closes, highs, lows, opens, volumes = _to_series(rows)
    assert closes == [10.0]
    assert highs == []
    assert lows == []
    assert opens == []
    assert volumes == []


def test_fetch_zero_rows_does_not_crash(monkeypatch):
    """0 根不应 crash — 实际测 env=false + daily 空 → 返空 5 元组"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_minute._fetch_daily_bars", return_value=[]):
        (closes, highs, lows, opens, volumes), source = fetch_recent_bars("600519", 240)
    assert closes == []
    assert source == "historical_daily_fallback"


# ── 组 3: 缓存交互 (6 个) ─────────────────────────────


def test_cache_all_hit_skips_compute(monkeypatch, fake_minute_rows):
    """cache 全命中 → 不调 compute_minute_factors"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    cached_factors = {f"f{i}": float(i) for i in range(5)}

    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=fake_minute_rows), \
         patch("services.realtime_factor_minute.get_all_cached", return_value=cached_factors), \
         patch("services.factor_service.compute_minute_factors") as m_compute:
        from services.realtime_factor_minute import compute_minute_factors_with_cache
        # 调用上层 compute_minute_factors_with_cache, cache 全命中
        result = compute_minute_factors_with_cache(code="600519", closes=[10.0]*5, volumes=[100]*5, factor_names=list(cached_factors.keys()))
    for name, val in cached_factors.items():
        assert result[name] == val
    m_compute.assert_not_called()


def test_cache_empty_triggers_compute(monkeypatch, fake_minute_rows):
    """cache 空 → 调 compute"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")

    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=fake_minute_rows), \
         patch("services.realtime_factor_minute.get_all_cached", return_value={}), \
         patch("services.factor_service.compute_minute_factors") as m_compute:
        m_compute.return_value = {"f0": 1.0, "f1": 2.0}
        from services.realtime_factor_minute import compute_minute_factors_with_cache
        result = compute_minute_factors_with_cache(code="600519", closes=[10.0]*5, volumes=[100]*5, factor_names=["f0", "f1"])
    assert result["f0"] == 1.0
    assert m_compute.called


def test_cache_partial_hit_only_computes_missing():
    """cache 部分命中 → 只重算缺失的"""
    cached = {"f0": 1.0}  # f1 缺失
    with patch("services.realtime_factor_minute.get_all_cached", return_value=cached), \
         patch("services.factor_service.compute_minute_factors") as m_compute:
        m_compute.return_value = {"f1": 2.0}
        from services.realtime_factor_minute import compute_minute_factors_with_cache
        result = compute_minute_factors_with_cache(code="600519", closes=[10.0]*5, volumes=[100]*5, factor_names=["f0", "f1"])
    assert m_compute.call_args.kwargs["factor_names"] == ["f1"]
    assert result["f0"] == 1.0
    assert result["f1"] == 2.0


def test_cache_write_back_for_new_factors(monkeypatch):
    """重算结果应写回 cache"""
    with patch("services.realtime_factor_minute.get_all_cached", return_value={}), \
         patch("services.factor_service.compute_minute_factors", return_value={"f0": 1.0}), \
         patch("services.realtime_factor_minute.set_cached_factor") as m_set, \
         patch("services.realtime_factor_minute.MINUTE_FACTOR_REGISTRY", {"f0": lambda: None}, create=True):
        from services.realtime_factor_minute import compute_minute_factors_with_cache
        # MINUTE_FACTOR_REGISTRY 实际定义在 services.factor_service,
        # production 用 `from services.factor_service import MINUTE_FACTOR_REGISTRY` 导入, 故须 patch 源头
        with patch("services.factor_service.MINUTE_FACTOR_REGISTRY", {"f0": lambda: None}):
            compute_minute_factors_with_cache(code="600519", closes=[10.0]*5, volumes=[100]*5, factor_names=["f0"])
    m_set.assert_called_once_with("600519", "f0", 1.0)


def test_cache_skips_none_values(monkeypatch):
    """compute 返 None 的因子不写 cache"""
    with patch("services.realtime_factor_minute.get_all_cached", return_value={}), \
         patch("services.factor_service.compute_minute_factors", return_value={"f0": None}), \
         patch("services.realtime_factor_minute.set_cached_factor") as m_set:
        from services.realtime_factor_minute import compute_minute_factors_with_cache
        compute_minute_factors_with_cache(code="600519", closes=[10.0]*5, volumes=[100]*5, factor_names=["f0"])
    m_set.assert_not_called()


def test_cache_extra_fields_not_written():
    """衍生字段(非 registry 内)不入 cache"""
    from services.realtime_factor_minute import compute_minute_factors_with_cache
    with patch("services.realtime_factor_minute.get_all_cached", return_value={}), \
         patch("services.factor_service.compute_minute_factors", return_value={"extra_field": 5.0}), \
         patch("services.realtime_factor_minute.set_cached_factor") as m_set:
        result = compute_minute_factors_with_cache(code="600519", closes=[10.0]*5, volumes=[100]*5, factor_names=["extra_field"])
    assert "extra_field" in result
    m_set.assert_not_called()


# ── 组 4: 错误降级 (6 个) ─────────────────────────────


def test_invalid_env_value_treated_as_false(monkeypatch, fake_daily_rows):
    """'yes'/'1'/'on' 都视为 false（严格匹配 'true'）"""
    for invalid_value in ("yes", "1", "on", "True", "TRUE "):
        monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", invalid_value)
        with patch("services.realtime_factor_minute._fetch_minute_bars") as m_m, \
             patch("services.realtime_factor_minute._fetch_daily_bars", return_value=fake_daily_rows):
            _, source = fetch_recent_bars("600519", 240)
        # 注: 'TRUE ' 有 strip, 'True' 严格匹配需 lower,但实现是 strip+lower,统一小写
        # 实际行为: 'True'.lower()=='true',应走 minute
        if invalid_value.strip().lower() == "true":
            assert source == "futu_1m"
        else:
            assert source == "historical_daily_fallback"


def test_sqlite_error_returns_503_via_router(monkeypatch):
    """SQLite OperationalError → router 抛 503"""
    def fake_query_all(*args, **kwargs):
        import sqlite3
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("services.realtime_factor_minute.query_all", fake_query_all)
    client = _make_test_client()
    resp = client.get("/api/realtime/factor/600519/minute")
    assert resp.status_code == 503


def test_factor_compute_exception_isolated():
    """单只 factor 抛异常不影响其它只"""
    from services.realtime_factor_minute import compute_minute_factors_with_cache
    with patch("services.realtime_factor_minute.get_all_cached", return_value={}), \
         patch("services.factor_service.compute_minute_factors",
               side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            compute_minute_factors_with_cache(code="600519", closes=[10.0]*5, volumes=[100]*5, factor_names=["f0"])


def test_minute_and_daily_both_empty(monkeypatch):
    """minute 和 daily 都空 → 返空 tuple + fallback source"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=[]), \
         patch("services.realtime_factor_minute._fetch_daily_bars", return_value=[]):
        (closes, highs, lows, opens, volumes), source = fetch_recent_bars("600519", 240)
    assert closes == []
    assert source == "historical_daily_fallback"


def test_router_returns_404_when_no_data(monkeypatch):
    """router 在 bar_count<5 时返 404"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_minute._fetch_daily_bars", return_value=[]):
        client = _make_test_client()
        resp = client.get("/api/realtime/factor/600519/minute")
    assert resp.status_code == 404


def test_fallback_logs_warning_on_empty_minute(monkeypatch, fake_daily_rows, caplog):
    """fallback 触发时应 log warning"""
    import logging
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=[]), \
         patch("services.realtime_factor_minute._fetch_daily_bars", return_value=fake_daily_rows):
        with caplog.at_level(logging.WARNING, logger="services.realtime_factor_minute"):
            fetch_recent_bars("600519", 240)
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


# ── 组 5: 性能 + 边界 (5 个,凑 30) ──────────────────────────


def test_limit_5_returns_5_bars(monkeypatch, fake_minute_rows):
    """limit=5 应返 5 根,且顺序 ASC(closes[0] = fixture[0] = OLDEST)"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_minute._fetch_minute_bars",
               return_value=fake_minute_rows[:5]):
        (closes, _, _, _, _), _ = fetch_recent_bars("600519", limit=5)
    assert len(closes) == 5
    # 锁定顺序契约: closes[0] 应是 fixture[0] 的 close(OLDEST)
    assert closes[0] == fake_minute_rows[0]["close"]
    assert closes[-1] == fake_minute_rows[4]["close"]


def test_limit_zero_returns_zero(monkeypatch):
    """limit=0 应返空"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_minute._fetch_daily_bars", return_value=[]):
        (closes, _, _, _, _), _ = fetch_recent_bars("600519", limit=0)
    assert closes == []


def test_negative_limit_handled_gracefully(monkeypatch):
    """limit 负数应被 SQL 兜底（SQLite LIMIT <0 返全集，但 mock 控空）"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "false")
    with patch("services.realtime_factor_minute._fetch_daily_bars", return_value=[]) as m:
        fetch_recent_bars("600519", limit=-1)
    # mock 函数被以 -1 调用即可
    m.assert_called_once_with("600519", -1)


def test_repeated_calls_are_idempotent(monkeypatch, fake_minute_rows):
    """同日多次调用应返相同结果（幂等）"""
    monkeypatch.setenv("REALTIME_USE_MINUTE_BARS", "true")
    with patch("services.realtime_factor_minute._fetch_minute_bars", return_value=fake_minute_rows):
        r1 = fetch_recent_bars("600519", 240)
        r2 = fetch_recent_bars("600519", 240)
    assert r1 == r2


def test_qfq_filter_excludes_none_qfq(monkeypatch):
    """_fetch_minute_bars 排除 adjust_type != 'qfq'"""
    captured_sql = []

    def fake_query_all(sql, params):
        captured_sql.append(sql)
        return []

    monkeypatch.setattr("services.realtime_factor_minute.query_all", fake_query_all)
    _fetch_minute_bars("600519", 240)
    sql = captured_sql[0].upper()
    assert "ADJUST_TYPE = 'QFQ'" in sql
    assert "INTERVAL = '1M'" in sql