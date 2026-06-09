"""因子计算引擎测试 — 25 因子纯函数验证

每个因子函数都是纯数学计算，测试重点：
1. 正常输入 → 预期输出
2. 数据不足 → 返回 None
3. 边界值 → 不抛异常
"""

import math
import pytest
from services.factor_service import (
    factor_ret_5d, factor_ret_20d, factor_ret_60d,
    factor_rsi, factor_macd_signal, factor_ma_disposition,
    factor_hist_vol, factor_atr, factor_amplitude, factor_downside_vol,
    factor_vol_ratio, factor_turnover_rate, factor_obv_divergence,
    factor_price_volume_corr, factor_avg_amount,
    factor_pe, factor_pb, factor_roe, factor_eps_growth,
    factor_market_cap, factor_dividend_yield,
    factor_strength, factor_momentum_score,
    compute_all_factors, normalize_factors,
    _returns, _safe_div, _safe_mean, _safe_std, _ema,
)


# ═══════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════

class TestHelpers:
    def test_returns_basic(self):
        prices = [10, 11, 12, 10, 13]
        r = _returns(prices)
        assert len(r) == 4
        assert r[0] == pytest.approx(0.1)      # (11-10)/10
        assert r[2] == pytest.approx(-2 / 12)  # (10-12)/12

    def test_returns_insufficient(self):
        assert _returns([10]) == []
        assert _returns([]) == []

    def test_safe_div_normal(self):
        assert _safe_div(10, 2) == 5.0

    def test_safe_div_by_zero(self):
        assert _safe_div(10, 0) is None

    def test_safe_mean(self):
        assert _safe_mean([1, 2, 3]) == 2.0
        assert _safe_mean([]) is None
        assert _safe_mean([None, 2, 4]) == 3.0

    def test_safe_std(self):
        assert _safe_std([1, 2, 3]) == pytest.approx(1.0)
        assert _safe_std([1]) is None


# ═══════════════════════════════════════════════
# 动量因子
# ═══════════════════════════════════════════════

class TestMomentumFactors:
    """5日/20日/60日收益率"""

    def test_ret_5d_normal(self):
        closes = [10.0] * 5 + [11.0]  # 6 values, 10→11 = 10%
        assert factor_ret_5d(closes) == pytest.approx(0.1)

    def test_ret_5d_insufficient(self):
        assert factor_ret_5d([10, 11]) is None

    def test_ret_20d(self):
        closes = [10.0] * 21
        closes[-1] = 12.0  # 20% up
        assert factor_ret_20d(closes) == pytest.approx(0.2)

    def test_ret_60d(self):
        closes = [10.0] * 61
        closes[-1] = 9.0  # 10% down
        assert factor_ret_60d(closes) == pytest.approx(-0.1)

    def test_rsi_oversold(self):
        # 连续下跌 → RSI 应很低
        closes = [100.0]
        for _ in range(20):
            closes.append(closes[-1] * 0.98)  # 每天跌 2%
        rsi = factor_rsi(closes)
        assert rsi is not None
        assert rsi < 30  # 超卖

    def test_rsi_overbought(self):
        closes = [100.0]
        for _ in range(20):
            closes.append(closes[-1] * 1.02)  # 每天涨 2%
        rsi = factor_rsi(closes)
        assert rsi is not None
        assert rsi > 70  # 超买

    def test_rsi_insufficient(self):
        assert factor_rsi([100, 101, 102]) is None

    def test_macd_signal_bullish(self):
        # 持续上涨 → MACD 应为正
        closes = [10.0 + i * 0.1 for i in range(60)]
        sig = factor_macd_signal(closes)
        assert sig is not None
        assert sig > 0

    def test_macd_insufficient(self):
        assert factor_macd_signal([10, 11]) is None

    def test_ma_disposition_bullish(self):
        # 持续上涨 → 均线多头排列
        closes = [10.0 + i * 0.05 for i in range(80)]
        disp = factor_ma_disposition(closes)
        assert disp is not None
        assert disp > 0  # 多头

    def test_ma_disposition_bearish(self):
        # 持续下跌 → 均线空头排列
        closes = [100.0 - i * 0.05 for i in range(80)]
        disp = factor_ma_disposition(closes)
        assert disp is not None
        assert disp < 0  # 空头


# ═══════════════════════════════════════════════
# 波动因子
# ═══════════════════════════════════════════════

class TestVolatilityFactors:
    def test_hist_vol_flat(self):
        # 价格完全不变 → 波动率为 0
        closes = [100.0] * 25
        from services.factor_service import _returns as _r
        rets = _r(closes)
        vol = factor_hist_vol(rets)
        assert vol is not None
        assert vol == pytest.approx(0.0, abs=0.01)

    def test_hist_vol_insufficient(self):
        assert factor_hist_vol([0.01, -0.02]) is None

    def test_atr_normal(self):
        n = 20
        # Price stays constant → true range = high-low = 10 each day
        closes = [100.0] * n
        highs = [105.0] * n
        lows = [95.0] * n
        atr = factor_atr(highs, lows, closes)
        assert atr is not None
        assert atr == pytest.approx(10.0, abs=0.1)

    def test_downside_vol(self):
        # 交替涨跌 → 下行波动只看下跌日
        rets = [0.02, -0.03, 0.01, -0.04, 0.02] * 15  # 75 days
        dvol = factor_downside_vol(rets)
        assert dvol is not None
        assert dvol > 0  # 有下跌，下行波动 > 0


# ═══════════════════════════════════════════════
# 量价因子
# ═══════════════════════════════════════════════

class TestVolumeFactors:
    def test_vol_ratio_expanding(self):
        # 最近 5 天放量
        vols = [1000.0] * 15 + [2000.0] * 5
        ratio = factor_vol_ratio(vols)
        assert ratio is not None
        assert ratio > 1.5  # 量比 >1

    def test_vol_ratio_contracting(self):
        vols = [2000.0] * 15 + [1000.0] * 5
        ratio = factor_vol_ratio(vols)
        assert ratio is not None
        assert ratio < 0.8  # 缩量

    def test_vol_ratio_insufficient(self):
        assert factor_vol_ratio([1000] * 10) is None

    def test_price_volume_corr_positive(self):
        n = 25
        closes = [10 + i * 0.1 for i in range(n)]
        vols = [1000 + i * 50 for i in range(n)]  # 价量同涨
        corr = factor_price_volume_corr(closes, vols)
        assert corr is not None
        assert corr > 0.5

    def test_obv_divergence_bullish(self):
        n = 25
        closes = [10 + i * 0.1 for i in range(n)]
        vols = [1000] * n
        div = factor_obv_divergence(closes, vols)
        assert div is not None

    def test_avg_amount(self):
        closes = [50.0] * 20
        vols = [10000.0] * 20  # avg_amount = 50 * 10000 = 500000, log10 ≈ 5.7
        amt = factor_avg_amount(vols, closes)
        assert amt is not None
        assert amt > 5.0


# ═══════════════════════════════════════════════
# 基本面因子
# ═══════════════════════════════════════════════

class TestFundamentalFactors:
    def test_pe_inverse(self):
        # PE=20 → 盈利率 = 1/20 = 5%
        assert factor_pe(20.0) == pytest.approx(0.05)

    def test_pe_negative(self):
        assert factor_pe(-5.0) is None  # 亏损公司

    def test_pe_none(self):
        assert factor_pe(None) is None

    def test_pb_inverse(self):
        assert factor_pb(2.0) == pytest.approx(0.5)

    def test_roe(self):
        assert factor_roe(15.0) == pytest.approx(0.15)  # 15% → 0.15

    def test_eps_growth(self):
        assert factor_eps_growth(1.2, 1.0) == pytest.approx(0.2)

    def test_eps_growth_prev_zero(self):
        assert factor_eps_growth(1.2, 0.0) is None

    def test_market_cap(self):
        # 1000亿 → log10(1000) = 3
        assert factor_market_cap(1000.0) == pytest.approx(3.0, abs=0.01)

    def test_dividend_yield(self):
        # 每股分红 0.5，股价 10 → 5%
        assert factor_dividend_yield(0.5, 10.0) == pytest.approx(0.05)


# ═══════════════════════════════════════════════
# 情绪因子
# ═══════════════════════════════════════════════

class TestSentimentFactors:
    def test_strength_positive(self):
        closes = [10.0] * 21
        closes[-1] = 12.0  # 20% up, flat volatility → high strength
        s = factor_strength(closes)
        assert s is not None
        assert s > 0

    def test_momentum_composite_up(self):
        closes = [10.0] * 61
        for i in range(1, len(closes)):
            closes[i] = closes[i - 1] * 1.005  # 0.5% daily up
        m = factor_momentum_score(closes)
        assert m is not None
        assert m > 0


# ═══════════════════════════════════════════════
# compute_all_factors 集成测试
# ═══════════════════════════════════════════════

class TestComputeAllFactors:
    def test_complete_input(self):
        """正常输入应返回全部 25 个因子名 + hit_count"""
        closes = [10.0 + i * 0.05 for i in range(120)]
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.98 for c in closes]
        vols = [10000.0] * 120
        fundamentals = {"pe": 15.0, "roe": 12.0, "eps": 2.0, "market_cap_billion": 500.0}

        result = compute_all_factors("600519", closes, highs, lows, vols, fundamentals)

        assert result["code"] == "600519"
        assert "factors" in result
        assert result["hit_count"] > 10  # 大部分因子应有值
        # 检查关键因子存在
        for key in ["ret_5d", "roe", "pe_inverse", "rsi_14", "strength_20d"]:
            assert key in result["factors"]

    def test_minimal_input(self):
        """只有收盘价也应返回结果，但 hit_count 较低"""
        closes = [10.0 + i * 0.02 for i in range(120)]
        result = compute_all_factors("000001", closes)

        assert result["code"] == "000001"
        # 没有量和基本面，量价和基本面因子应为 None
        assert result["factors"]["pe_inverse"] is None
        assert result["factors"]["turnover_rate"] is None
        # 但有动量因子
        assert result["factors"]["ret_20d"] is not None

    def test_empty_volumes_handled(self):
        closes = [10.0] * 120
        result = compute_all_factors("test", closes, [], [], [])
        # 不应抛异常
        assert result["code"] == "test"

    def test_insufficient_data(self):
        """数据不够 60 天 → 很多因子返回 None"""
        closes = [10.0] * 30
        result = compute_all_factors("test", closes)
        assert result["factors"]["ret_60d"] is None  # 需要 61 条
        assert result["factors"]["rsi_14"] is not None  # 14 条就够


# ═══════════════════════════════════════════════
# normalize_factors
# ═══════════════════════════════════════════════

class TestNormalizeFactors:
    def test_basic_normalization(self):
        """标准化后每个因子的截面均值应接近 0"""
        stocks = []
        for i in range(20):
            closes = [10.0 + i * 0.1 + j * 0.02 for j in range(120)]
            stocks.append(compute_all_factors(f"stock{i}", closes))

        normalized = normalize_factors(stocks)
        assert len(normalized) == 20

        # 取 ret_20d 因子，截面均值应接近 0
        vals = [n["factors"].get("ret_20d") for n in normalized if n["factors"].get("ret_20d") is not None]
        if vals:
            mean_val = sum(vals) / len(vals)
            assert abs(mean_val) < 0.01  # 接近 0

    def test_empty_input(self):
        assert normalize_factors([]) == []
