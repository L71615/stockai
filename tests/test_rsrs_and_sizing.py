"""v4.1.1 新增模块单元测试

覆盖:
  - factor_rsrs: 正常 / 边界 / OLS 退化
  - risk_sizing: 4 种算法 + calc_win_rate_and_profit_factor
  - factor_lifecycle._notify_lifecycle_changes: 调用 + 失败不阻塞

不依赖 DB,纯函数测试。
"""
from unittest.mock import patch

import pytest

from services.factor_service import factor_rsrs
from services.risk_sizing import (
    SizingMethod,
    calc_win_rate_and_profit_factor,
    fixed_fraction_size,
    get_position_size,
    kelly_size,
    risk_parity_size,
    vol_target_size,
)


# ═══════════════════════════════════════════════════════════════
#  factor_rsrs
# ═══════════════════════════════════════════════════════════════


class TestFactorRsrs:
    def test_too_short_returns_none(self):
        """长度不足 → None"""
        assert factor_rsrs([10, 11], [9, 10]) is None
        assert factor_rsrs([10] * 10, [9] * 10) is None  # 只有 10 条,window=18 不足

    def test_normal_case_positive_zscore(self):
        """买方推力强 → 正 z-score"""
        # 30 天:high 几乎 = low + 0.5(买方主导)
        highs = [10.5 + i * 0.1 for i in range(30)]
        lows = [10.0 + i * 0.1 for i in range(30)]
        # 最近几天 high 突然拉开(买方推力强)
        highs[-3:] = [h + 2 for h in highs[-3:]]
        result = factor_rsrs(highs, lows, window=18)
        assert result is not None
        assert result > 0, f"买方推力强应为正 z-score,实际 {result}"

    def test_normal_case_negative_zscore(self):
        """卖方压制 → 负 z-score"""
        highs = [10.5 + i * 0.1 for i in range(30)]
        lows = [10.0 + i * 0.1 for i in range(30)]
        # 最近几天 high 收敛到 low(卖方压制)
        highs[-3:] = [lows[-3 + i] + 0.1 for i in range(3)]
        result = factor_rsrs(highs, lows, window=18)
        assert result is not None
        assert result < 0, f"卖方压制应为负 z-score,实际 {result}"

    def test_window_parameter(self):
        """window 参数生效"""
        highs = [10.5 + i * 0.1 for i in range(30)]
        lows = [10.0 + i * 0.1 for i in range(30)]
        r18 = factor_rsrs(highs, lows, window=18)
        r10 = factor_rsrs(highs, lows, window=10)
        # 两个都应返回数值(可能不同)
        assert r18 is not None and r10 is not None

    def test_zero_variance_returns_zero(self):
        """low 完全不变 → var=0 → 提前返回 0"""
        highs = [10.5 + i for i in range(30)]
        lows = [10.0] * 30  # 完全不变
        result = factor_rsrs(highs, lows, window=18)
        # variance = 0 → 因子函数返回 0.0
        assert result == 0.0 or result is None


# ═══════════════════════════════════════════════════════════════
#  risk_sizing — 各算法
# ═══════════════════════════════════════════════════════════════


class TestFixedFraction:
    def test_basic(self):
        assert fixed_fraction_size(0.1) == 0.1

    def test_clamp_upper(self):
        assert fixed_fraction_size(1.5) == 1.0

    def test_clamp_lower(self):
        assert fixed_fraction_size(-0.5) == 0.0


class TestKelly:
    def test_zero_win_rate_returns_min(self):
        """p=0 → f*=负 → 返回 min_fraction (默认 0.02)"""
        assert kelly_size(0.0, 2.0) == 0.02

    def test_half_kelly(self):
        """默认 half_kelly"""
        # p=0.55, b=2 → f* = (0.55*2 - 0.45)/2 = 0.325 → half = 0.1625
        result = kelly_size(0.55, 2.0)
        assert 0.15 < result < 0.20, f"实际 {result}"

    def test_full_kelly(self):
        result = kelly_size(0.55, 2.0, half=False)
        # full = 0.325, 但 max_fraction=0.25 → 返回 0.25
        assert result == 0.25

    def test_max_cap(self):
        result = kelly_size(0.9, 5.0, half=False, max_fraction=0.30)
        assert result == 0.30


class TestRiskParity:
    def test_basic(self):
        # target_risk=5%, vol=20% → 0.05/0.20 = 0.25
        result = risk_parity_size(0.05, 0.20)
        assert abs(result - 0.25) < 0.001

    def test_high_vol_low_position(self):
        result = risk_parity_size(0.05, 0.50)
        assert result < 0.15

    def test_max_cap(self):
        result = risk_parity_size(0.10, 0.05, max_fraction=0.5)
        assert result == 0.5


class TestVolTarget:
    def test_basic(self):
        # target=15%, realized=30% → 0.5
        result = vol_target_size(0.15, 0.30)
        assert abs(result - 0.5) < 0.001

    def test_leverage_capped(self):
        # target=15%, realized=5% → 应该是 3x,但 max_leverage=2 → 2.0
        result = vol_target_size(0.15, 0.05, max_leverage=2.0)
        assert result == 2.0


class TestGetPositionSize:
    def test_dispatch_fixed(self):
        r = get_position_size(method="fixed", fraction=0.15)
        assert r["method"] == "fixed"
        assert r["position_pct"] == 0.15

    def test_dispatch_kelly(self):
        r = get_position_size(method=SizingMethod.KELLY, win_rate=0.55, profit_factor=2.0)
        assert r["method"] == "kelly"
        assert 0 < r["position_pct"] < 0.3

    def test_dispatch_risk_parity(self):
        r = get_position_size(method="risk_parity", volatility=0.20)
        assert r["method"] == "risk_parity"
        assert "20.0%" in r["diagnostic"]
        assert "5.0%" in r["diagnostic"]

    def test_dispatch_vol_target(self):
        r = get_position_size(method="vol_target", realized_vol=0.20)
        assert r["method"] == "vol_target"

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="未知 method"):
            get_position_size(method="invalid")

    def test_kelly_missing_params_raises(self):
        with pytest.raises(ValueError, match="win_rate"):
            get_position_size(method="kelly", win_rate=None, profit_factor=2.0)


class TestCalcWinRatePF:
    def test_empty_trades(self):
        r = calc_win_rate_and_profit_factor([])
        assert r["num_trades"] == 0
        assert r["kelly_fraction"] == 0

    def test_all_winning(self):
        trades = [{"direction": "sell", "pnl": 100}] * 5
        r = calc_win_rate_and_profit_factor(trades)
        assert r["win_rate"] == 1.0
        # 全部盈利, profit_factor = 10.0 (无 loss 时 fallback)
        assert r["profit_factor"] == 10.0
        assert r["kelly_fraction"] == 0.25  # 上限 25%

    def test_mixed(self):
        trades = [
            {"direction": "sell", "pnl": 100},  # win
            {"direction": "sell", "pnl": -50},  # loss
            {"direction": "sell", "pnl": 200},  # win
            {"direction": "sell", "pnl": -50},  # loss
            {"direction": "buy", "pnl": None},   # ignore
            {"direction": "sell", "pnl": 50},   # win
        ]
        r = calc_win_rate_and_profit_factor(trades)
        assert r["num_trades"] == 5  # buy 忽略
        assert r["win_rate"] == 0.6  # 3/5
        # profit_factor = avg_win / avg_loss = (350/3) / 50 = 2.3333
        assert r["profit_factor"] == round((100 + 200 + 50) / 3 / 50, 4)

    def test_all_losing(self):
        trades = [{"direction": "sell", "pnl": -50}] * 3
        r = calc_win_rate_and_profit_factor(trades)
        assert r["win_rate"] == 0.0
        assert r["profit_factor"] == 0.0
        assert r["kelly_fraction"] == 0.0


# ═══════════════════════════════════════════════════════════════
#  factor_lifecycle._notify_lifecycle_changes
# ═══════════════════════════════════════════════════════════════


class TestNotifyLifecycle:
    def test_empty_lists_no_call(self):
        """retired + warnings 都为空 → 不调 notify_service"""
        from services.factor_lifecycle import _notify_lifecycle_changes

        with patch("services.notify_service.send_notification") as mock_send:
            _notify_lifecycle_changes([], [], "v1.0")
            mock_send.assert_not_called()

    def test_retired_triggers_notification(self):
        from services.factor_lifecycle import _notify_lifecycle_changes

        with patch("services.notify_service.send_notification") as mock_send:
            mock_send.return_value = {"status": "ok"}
            _notify_lifecycle_changes(["VOL_RATIO"], [], "v1.0")
            mock_send.assert_called_once()
            body, title = mock_send.call_args.args[:2]
            assert "VOL_RATIO" in body
            assert "已退役" in body
            assert "v1.0" in body
            assert "1 退役" in title

    def test_warning_triggers_notification(self):
        from services.factor_lifecycle import _notify_lifecycle_changes

        with patch("services.notify_service.send_notification") as mock_send:
            mock_send.return_value = {"status": "ok"}
            _notify_lifecycle_changes([], ["MACD"], "v1.0")
            mock_send.assert_called_once()
            body = mock_send.call_args.args[0]
            assert "MACD" in body
            assert "新增警告" in body

    def test_notify_failure_does_not_raise(self):
        """通知失败 → 异常被吞,不阻塞主流程"""
        from services.factor_lifecycle import _notify_lifecycle_changes

        with patch("services.notify_service.send_notification",
                   side_effect=Exception("network error")):
            # 应该不抛异常
            _notify_lifecycle_changes(["F1"], [], "v1.0")

    def test_notify_service_missing_does_not_raise(self):
        """notify_service 不可用(测试场景)→ 不抛异常"""
        from services.factor_lifecycle import _notify_lifecycle_changes

        with patch.dict("sys.modules", {"services.notify_service": None}):
            # 应该不抛
            _notify_lifecycle_changes(["F1"], [], "v1.0")