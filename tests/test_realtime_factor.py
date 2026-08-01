"""v5.0-alpha M2 — 盘中因子计算 + 缓存 + REST 测试

覆盖:
  - compute_realtime_factors: 基本算 / 序列不足 / 单因子失败 / 提取标量
  - realtime_factor_cache: 5m TTL / 往返 / 过期 / invalidate
  - compute_factors_with_cache: 缓存命中 / 写回
  - REST: GET /api/realtime/factor/{code} / POST /invalidate
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


# ─────────────────────── compute_realtime_factors ───────────────────────


class TestComputeRealtimeFactors:
    def test_returns_empty_when_closes_too_short(self):
        from services.realtime_factor_cache import compute_realtime_factors
        result = compute_realtime_factors(code="000725", closes=[1.0, 2.0, 3.0])
        assert result == {}

    def test_computes_all_factors_by_default(self):
        from services.realtime_factor_cache import compute_realtime_factors
        closes = [4.0 + i * 0.1 for i in range(60)]  # 60 根递增 close
        volumes = [1000000] * 60
        result = compute_realtime_factors(code="000725", closes=closes, volumes=volumes)
        # 至少应该算出一些 ma/rsi/ret 等
        assert len(result) > 0
        # ma5 应该非空(递增序列)
        if "ma5" in result:
            assert result["ma5"] is not None

    def test_returns_none_for_unknown_factor(self):
        from services.realtime_factor_cache import compute_realtime_factors
        closes = [4.0] * 60
        result = compute_realtime_factors(code="000725", closes=closes, factor_names=["nonexistent_factor"])
        assert result.get("nonexistent_factor") is None

    def test_single_factor_failure_does_not_break_others(self):
        """坏因子抛异常时, 其他因子仍能算出来"""
        from services.realtime_factor_cache import compute_realtime_factors
        from services import factor_lab
        closes = [4.0 + i * 0.1 for i in range(60)]

        # 备份原注册表
        original = factor_lab.FACTOR_REGISTRY.copy()
        # 注入一个会抛异常的因子 (使用 lambda 延迟求值避免 import 时崩溃)
        factor_lab.FACTOR_REGISTRY["bad_factor"] = (lambda c, v: 1 / 0, False)
        try:
            result = compute_realtime_factors(code="000725", closes=closes)
            # 其他正常因子应当算出来
            assert "ma5" in result
            assert result["ma5"] is not None
            # 坏因子应被兜底成 None
            assert result.get("bad_factor") is None
        finally:
            factor_lab.FACTOR_REGISTRY.clear()
            factor_lab.FACTOR_REGISTRY.update(original)

    def test_extract_scalar_handles_ndarray(self):
        import numpy as np
        from services.realtime_factor_cache import _extract_scalar
        assert _extract_scalar(np.array([1.0, 2.0, 3.0]), []) == 3.0
        assert _extract_scalar(np.array([1.0, np.nan, 3.0]), []) == 3.0  # NaN 跳过

    def test_extract_scalar_handles_none(self):
        from services.realtime_factor_cache import _extract_scalar
        assert _extract_scalar(None, []) is None

    def test_extract_scalar_handles_nan_inf(self):
        import math
        from services.realtime_factor_cache import _extract_scalar
        assert _extract_scalar(float("nan"), []) is None
        assert _extract_scalar(float("inf"), []) is None
        assert _extract_scalar(0.0, []) == 0.0  # 0.0 是有效值


# ─────────────────────── 缓存层 ───────────────────────
# 注意: 缓存层测试需要 _test_db_session 已初始化 schema.
# 通过 _test_db_session fixture 参数触发 (即使不直接使用 db 对象).


class TestRealtimeFactorCache:
    def test_set_then_get(self, _test_db_session):
        from services.realtime_factor_cache import set_cached_factor, get_cached_factor
        from services.realtime_factor_cache import invalidate
        invalidate("000725")
        set_cached_factor("000725", "ma5", 4.56)
        v = get_cached_factor("000725", "ma5")
        assert v == 4.56

    def test_set_none_skipped(self, _test_db_session):
        from services.realtime_factor_cache import set_cached_factor, get_cached_factor
        from services.realtime_factor_cache import invalidate
        invalidate("000725")
        # 写 None 不入库
        set_cached_factor("000725", "ma10", None)
        from database import query_one
        row = query_one(
            "SELECT value FROM realtime_factor_cache WHERE stock_code=? AND factor_name=?",
            ("000725", "ma10"),
        )
        assert row is None
        # get_cached_factor 也应该返回 None
        assert get_cached_factor("000725", "ma10") is None

    def test_cache_expires_after_5_minutes(self, _test_db_session):
        from services.realtime_factor_cache import set_cached_factor, get_cached_factor
        from services.realtime_factor_cache import invalidate
        invalidate("000725")
        # 写入真实时间戳
        set_cached_factor("000725", "rsi_14", 65.0)
        # 模拟 6m40s 之后
        future_ts = time.time() + 400
        with patch("services.realtime_factor_cache.time.time", return_value=future_ts):
            assert get_cached_factor("000725", "rsi_14") is None

    def test_get_all_cached_skips_expired(self, _test_db_session):
        from services.realtime_factor_cache import set_cached_factor, get_all_cached
        from services.realtime_factor_cache import invalidate
        invalidate("000725")
        set_cached_factor("000725", "ma5", 4.0)
        set_cached_factor("000725", "ma10", 4.1)
        # 模拟过期
        future_ts = time.time() + 400
        with patch("services.realtime_factor_cache.time.time", return_value=future_ts):
            cached = get_all_cached("000725")
            assert cached == {}

    def test_invalidate_clears_all(self, _test_db_session):
        from services.realtime_factor_cache import set_cached_factor, invalidate, get_all_cached
        invalidate("000725")
        set_cached_factor("000725", "ma5", 4.0)
        set_cached_factor("000725", "ma10", 4.1)
        assert len(get_all_cached("000725")) == 2
        invalidate("000725")
        assert get_all_cached("000725") == {}


# ─────────────────────── compute_factors_with_cache ───────────────────────


class TestComputeFactorsWithCache:
    def test_first_call_computes_and_caches(self, _test_db_session):
        from services.realtime_factor_cache import (
            compute_factors_with_cache, invalidate, get_all_cached,
        )
        invalidate("000725")  # 确保干净
        closes = [4.0 + i * 0.1 for i in range(60)]
        result = compute_factors_with_cache(code="000725", closes=closes)
        assert len(result) > 0
        cached = get_all_cached("000725")
        assert len(cached) > 0

    def test_second_call_uses_cache(self, _test_db_session):
        """缓存命中后, 已缓存的因子不应被再次计算

        注: 缓存只存非 None 值, 所以验证 ma5 (一定成功) 被跳过即可.
        限定 factor_names=["ma5"] 让目标集=1, 缓存命中后无需重算任何因子.
        """
        from services.realtime_factor_cache import (
            compute_factors_with_cache, invalidate, get_all_cached,
        )
        from services import factor_lab

        invalidate("000725")
        closes = [4.0 + i * 0.1 for i in range(60)]

        # 第一次: 写入 ma5 缓存
        compute_factors_with_cache(code="000725", closes=closes, factor_names=["ma5"])
        # 确保 ma5 在缓存中
        cached = get_all_cached("000725")
        assert "ma5" in cached, "首次计算后 ma5 应入缓存"

        # spy ma5
        original_ma5 = factor_lab.FACTOR_REGISTRY["ma5"]
        call_count = {"n": 0}

        def spy_ma5(c, v):
            call_count["n"] += 1
            return original_ma5[0](c, v)

        factor_lab.FACTOR_REGISTRY["ma5"] = (spy_ma5, original_ma5[1])
        try:
            # 第二次: ma5 已缓存, 函数不应被调用
            compute_factors_with_cache(code="000725", closes=closes, factor_names=["ma5"])
        finally:
            factor_lab.FACTOR_REGISTRY["ma5"] = original_ma5

        assert call_count["n"] == 0, f"缓存命中时应不调用 ma5, 实际调用 {call_count['n']} 次"


# ─────────────────────── REST API ───────────────────────


class TestRestApi:
    def test_factor_endpoint_returns_factors(self, client):
        from services.realtime_factor_cache import invalidate
        from database import execute
        from datetime import date, timedelta
        # 插入测试 K 线数据 (无 source 列)
        base = date(2026, 7, 1)
        for i in range(60):
            d = (base + timedelta(days=i)).isoformat()
            execute(
                """INSERT OR IGNORE INTO historical_kline
                   (stock_code, trade_date, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("000725", d, 4.0 + i * 0.01, 4.5 + i * 0.01, 3.9 + i * 0.01,
                 4.2 + i * 0.01, 1000000),
            )
        invalidate("000725")
        resp = client.get("/api/realtime/factor/000725?names=ma5,ma10")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == "000725"
        assert "ma5" in data["factors"]
        assert "ma10" in data["factors"]
        assert data["bar_count"] >= 30

    def test_factor_endpoint_no_data_404(self, client):
        from services.realtime_factor_cache import invalidate
        invalidate("NOSUCHCODE")
        resp = client.get("/api/realtime/factor/NOSUCHCODE")
        assert resp.status_code == 404

    def test_invalidate_endpoint(self, client):
        from services.realtime_factor_cache import set_cached_factor, get_all_cached
        from services.realtime_factor_cache import invalidate
        invalidate("000725")
        set_cached_factor("000725", "ma5", 4.0)
        assert "ma5" in get_all_cached("000725")
        resp = client.post("/api/realtime/factor/000725/invalidate")
        assert resp.status_code == 200, resp.text
        assert resp.json()["invalidated"] is True
        assert get_all_cached("000725") == {}