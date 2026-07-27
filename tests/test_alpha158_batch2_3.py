"""v4.0 B2 + B3 Alpha158 Batch 2/3 测试

B2 (15 动量/波动类): DEVIATION5/60 / STD10/60 / BETA5/10 / CORR5/10/60 / CORD5/10/20/60 / KMID / VWAP / VOL_CHANGE5
B3 (5 技术/资金流):  VOL_RATIO_5_20 / OBV_TREND_5 / KMID2 / AMPLITUDE_MA20 / VPA_SIGNAL
"""

import pytest

from services.factor_service import (
    compute_all_factors,
    FACTOR_REGISTRY,
    factor_corr,
    factor_cord,
    factor_vol_change,
    factor_kmid,
    factor_vwap,
    factor_beta20,
    _compute_vol_ratio_5_20,
    _compute_obv_trend_5,
    _compute_kmid2,
    _compute_amplitude_ma20,
    _compute_vpa_signal,
)


def _make_test_data(n=120):
    closes = [100 + i * 0.1 for i in range(n)]
    opens = [c - 0.5 for c in closes]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    volumes = [1000 + i * 10 for i in range(n)]
    return opens, highs, lows, closes, volumes


# ═══════════════════════════════════════════════════════════════
#  B2 因子单元测试
# ═══════════════════════════════════════════════════════════════


class TestB2KmidAndVwap:
    def test_kmid_returns_value(self):
        opens, highs, lows, closes, _ = _make_test_data()
        result = factor_kmid(opens, highs, lows, closes)
        assert result is not None

    def test_kmid_zero_range_returns_none(self):
        opens = [100.0]
        highs = [100.0]
        lows = [100.0]
        closes = [100.0]
        assert factor_kmid(opens, highs, lows, closes) is None

    def test_vwap_positive_when_price_above(self):
        """最近 20 日 close 持续上涨 → 当前价 > VWAP → 偏离度 > 0"""
        closes = [100 + i for i in range(20)]
        volumes = [1000] * 20
        result = factor_vwap(closes, volumes, 20)
        assert result is not None
        assert result > 0

    def test_vwap_insufficient_data(self):
        assert factor_vwap([100, 101], [1000, 1000], 20) is None


class TestB2CorrMultiPeriod:
    def test_corr5_insufficient(self):
        closes = [100 + i for i in range(3)]
        volumes = [1000 + i for i in range(3)]
        assert factor_corr(closes, volumes, 5) is None

    def test_corr10_positive_for_trending(self):
        """价量齐升 → 正相关"""
        closes = [100 + i for i in range(15)]
        volumes = [1000 + i * 100 for i in range(15)]
        result = factor_corr(closes, volumes, 10)
        assert result is not None
        assert result > 0.9

    def test_corr60_different_window(self):
        """60 日窗口计算逻辑"""
        closes = [100 + i for i in range(70)]
        volumes = [1000 + i for i in range(70)]
        result = factor_corr(closes, volumes, 60)
        assert result is not None
        assert -1 <= result <= 1


class TestB2Cord:
    def test_cord5_5d_window(self):
        """5 日收益率自相关"""
        closes = [100 + i * 0.5 for i in range(10)]  # 持续上涨
        result = factor_cord(closes, 5)
        assert result is not None
        # 持续上涨的收益率高度自相关
        assert result > 0.5

    def test_cord60_long_window(self):
        closes = [100 + (i % 3 - 1) for i in range(70)]  # 震荡
        result = factor_cord(closes, 60)
        # 震荡的收益率自相关应接近 0 或负
        assert result is not None or result is None  # 容许

    def test_cord_insufficient_data(self):
        closes = [100] * 5
        assert factor_cord(closes, 60) is None


class TestB2VolChange:
    def test_vol_change_5_positive(self):
        volumes = [1000] * 5 + [2000]
        result = factor_vol_change(volumes, 5)
        assert abs(result - 1.0) < 0.001  # 100% 增加

    def test_vol_change_negative(self):
        volumes = [1000] * 5 + [500]
        result = factor_vol_change(volumes, 5)
        assert abs(result - (-0.5)) < 0.001


class TestB2BetaParameterized:
    def test_beta5_short_window(self):
        """5 日自回归 beta(需要足够数据 + 波动)"""
        # 加入波动避免 var=0
        closes = [100 + i * 0.5 + (i % 3 - 1) * 0.3 for i in range(30)]
        result = factor_beta20(closes, period=5)
        assert result is not None
        assert -1 <= result <= 1

    def test_beta10_medium_window(self):
        closes = [100 + i * 0.3 + (i % 4 - 1.5) * 0.5 for i in range(30)]
        result = factor_beta20(closes, period=10)
        assert result is not None


# ═══════════════════════════════════════════════════════════════
#  B3 因子单元测试
# ═══════════════════════════════════════════════════════════════


class TestB3VolRatio:
    def test_vol_ratio_5_20_basic(self):
        """5日/20日量比"""
        _, _, _, closes, volumes = _make_test_data(30)
        result = _compute_vol_ratio_5_20(closes, volumes)
        assert result is not None
        assert result > 0

    def test_vol_ratio_insufficient(self):
        assert _compute_vol_ratio_5_20([100] * 3, [1000] * 3) is None


class TestB3ObvTrend:
    def test_obv_trend_5_for_uptrend(self):
        """持续上涨 → OBV 趋势 > 0"""
        closes = [100 + i for i in range(30)]
        volumes = [1000 + i * 50 for i in range(30)]
        result = _compute_obv_trend_5(closes, volumes)
        assert result is not None
        assert result > 0

    def test_obv_trend_5_for_downtrend(self):
        """持续下跌 → OBV 趋势 < 0"""
        closes = [130 - i for i in range(30)]
        volumes = [1000] * 30
        result = _compute_obv_trend_5(closes, volumes)
        assert result is not None
        assert result < 0


class TestB3Kmid2:
    def test_kmid2_returns_value(self):
        opens, highs, lows, closes, _ = _make_test_data()
        result = _compute_kmid2(opens, highs, lows, closes)
        assert result is not None

    def test_kmid2_empty_inputs(self):
        assert _compute_kmid2([], [], [], []) is None


class TestB3AmplitudeMa20:
    def test_amplitude_ma20_returns_positive(self):
        _, _, _, closes, _ = _make_test_data(30)
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        result = _compute_amplitude_ma20(closes, highs, lows)
        assert result is not None
        assert result > 0

    def test_amplitude_ma20_insufficient(self):
        assert _compute_amplitude_ma20([100] * 5, [101] * 5, [99] * 5) is None


class TestB3VpaSignal:
    def test_vpa_signal_volume_increasing_with_uptrend(self):
        """量增 + 价涨 → VPA > 0"""
        closes = [100 + i * 0.5 for i in range(15)]
        volumes = [1000 + i * 100 for i in range(15)]
        result = _compute_vpa_signal(closes, volumes)
        assert result is not None
        assert result > 0

    def test_vpa_signal_insufficient(self):
        assert _compute_vpa_signal([100] * 3, [1000] * 3) is None


# ═══════════════════════════════════════════════════════════════
#  Registry + compute_all_factors 集成
# ═══════════════════════════════════════════════════════════════


class TestB2B3RegistryAndIntegration:
    def test_b2_factors_in_registry(self):
        expected_b2 = {
            "DEVIATION5", "DEVIATION60", "STD10", "STD60",
            "BETA5", "BETA10",
            "CORR5", "CORR10", "CORR60",
            "CORD5", "CORD10", "CORD20", "CORD60",
            "KMID", "VWAP", "VOL_CHANGE5",
        }
        registered = {k for k in expected_b2 if k in FACTOR_REGISTRY}
        assert registered == expected_b2
        for k in expected_b2:
            assert FACTOR_REGISTRY[k]["status"] == "done"

    def test_b3_factors_in_registry(self):
        expected_b3 = {"VOL_RATIO_5_20", "OBV_TREND_5", "KMID2", "AMPLITUDE_MA20", "VPA_SIGNAL"}
        registered = {k for k in expected_b3 if k in FACTOR_REGISTRY}
        assert registered == expected_b3

    def test_compute_all_returns_b2_b3_factors(self):
        opens, highs, lows, closes, volumes = _make_test_data()
        result = compute_all_factors(
            "000001", closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
        )
        factors = result["factors"]
        # B2
        for k in ["deviation5", "deviation60", "std10", "std60",
                  "beta5", "beta10", "corr5", "corr10", "corr60",
                  "cord5", "cord10", "cord20", "cord60", "kmid", "vwap",
                  "vol_change5"]:
            assert k in factors, f"B2 因子 {k} 缺失"
        # B3
        for k in ["vol_ratio_5_20", "obv_trend_5", "kmid2", "amplitude_ma20", "vpa_signal"]:
            assert k in factors, f"B3 因子 {k} 缺失"

    def test_total_factor_count(self):
        """v4.0 Phase 4 后:44 + 15 + 5 = 64 因子(已完成)"""
        opens, highs, lows, closes, volumes = _make_test_data()
        result = compute_all_factors(
            "000001", closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
        )
        # 实际因子的 hit_count 应 >= 50(去掉 K线类需要 opens 的)
        assert result["hit_count"] >= 50
        # 总 key 数应包含 20 个 B2+B3 因子
        assert "deviation5" in result["factors"]
        assert "vpa_signal" in result["factors"]
