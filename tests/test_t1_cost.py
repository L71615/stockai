"""C2 T+1 持仓成本计算器单元测试 — v4.0

覆盖:
  - 正常参数(基础计算)
  - 各种边界(空/零/负数)
  - 滑点应用
  - 持仓风险溢价按天数缩放
  - 净收益率计算
  - 报告格式化
"""

import pytest

from services.t1_cost import (
    calc_t1_holding_cost,
    calc_t1_net_return,
    format_t1_cost_report,
    DEFAULT_DAILY_RISK_PREMIUM_BPS,
)


class TestCalcT1HoldingCostBasic:
    def test_basic_positive_return(self):
        """100 买入, 101 卖出(T+1, 无溢价),净收益应 > 0"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=101.0,
            shares=100,
            hold_days=1,
        )
        assert "error" not in result
        # 100 → 101 涨幅 1%,扣滑点 0.1% → 0.9%,扣卖费 ~0.13% + 溢价 0.05% → ~0.72%
        assert result["gross_pnl"] > 0
        assert result["net_pnl"] > 0
        # 净利润 = 税前 - 卖费 - 溢价
        assert result["net_pnl"] < result["gross_pnl"]
        # 净收益率应比税前收益率低
        assert result["net_return_pct"] < result["gross_return_pct"]

    def test_basic_negative_return(self):
        """100 买入, 99 卖出,净收益应 < 0"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=99.0,
            shares=100,
            hold_days=1,
        )
        assert "error" not in result
        assert result["net_pnl"] < 0
        assert result["net_return_pct"] < 0

    def test_break_even(self):
        """100 买入, 100 卖出(平价),净收益应略亏(滑点+卖费+溢价)"""
        # 100 × 0.999 (slippage 10bps) = 99.9
        # 卖费: 9990 × 0.001 (印花税) + 最低 5 (佣金, 因为 9990 × 0.0003 = 2.997 < 5) + 0.0999 (过户费) ≈ 15.09
        # 溢价: 10000 × 0.0005 = 5
        # 净利润 = -10 (滑点) - 15.09 (卖费) - 5 (溢价) = -30.09
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=100.0,
            shares=100,
            hold_days=1,
        )
        # 略亏
        assert result["net_pnl"] < 0
        # 实际亏损 ~30 元(由佣金最低 5 + 印花税 10 + 滑点 10 + 溢价 5 构成)
        assert -50.0 < result["net_pnl"] < -20.0


class TestSlippageApplication:
    def test_exit_price_reduced_by_slippage(self):
        """100 卖出, 默认 10bps 滑点 → slipped_exit_price = 99.90"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=100.0,
            shares=100,
            hold_days=1,
        )
        assert abs(result["slipped_exit_price"] - 99.90) < 0.01

    def test_slippage_zero_keeps_price(self):
        """slippage_bps=0 → slipped_exit_price = exit_price"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=100.0,
            shares=100,
            slippage_bps=0,
        )
        assert result["slipped_exit_price"] == 100.0

    def test_slippage_30bps(self):
        """slippage_bps=30 → 100 × 0.997 = 99.70"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=100.0,
            shares=100,
            slippage_bps=30,
        )
        assert abs(result["slipped_exit_price"] - 99.70) < 0.01


class TestHoldingRiskPremium:
    def test_default_premium_5bps_per_day(self):
        """默认 daily_risk_premium_bps=5 → 100 × 100 × 0.0005 × 1 = 5 元"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=100.0,
            shares=100,
            hold_days=1,
        )
        assert result["holding_risk_premium"] == 5.0

    def test_premium_scales_with_hold_days(self):
        """T+2 持仓 = 2 × T+1 溢价"""
        r1 = calc_t1_holding_cost(entry_price=100.0, exit_price=100.0, shares=100, hold_days=1)
        r2 = calc_t1_holding_cost(entry_price=100.0, exit_price=100.0, shares=100, hold_days=2)
        assert r2["holding_risk_premium"] == 2 * r1["holding_risk_premium"]

    def test_premium_zero_for_zero_days(self):
        """hold_days=0 → 无持仓风险溢价"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=100.0,
            shares=100,
            hold_days=0,
        )
        assert result["holding_risk_premium"] == 0

    def test_custom_premium_bps(self):
        """自定义 daily_risk_premium_bps=10 → 100 × 100 × 0.001 × 1 = 10 元"""
        result = calc_t1_holding_cost(
            entry_price=100.0,
            exit_price=100.0,
            shares=100,
            hold_days=1,
            daily_risk_premium_bps=10.0,
        )
        assert result["holding_risk_premium"] == 10.0


class TestEdgeCases:
    def test_zero_entry_price_returns_error(self):
        result = calc_t1_holding_cost(entry_price=0, exit_price=100.0)
        assert "error" in result

    def test_negative_exit_price_returns_error(self):
        result = calc_t1_holding_cost(entry_price=100.0, exit_price=-1.0)
        assert "error" in result

    def test_zero_shares_returns_error(self):
        result = calc_t1_holding_cost(entry_price=100.0, exit_price=100.0, shares=0)
        assert "error" in result

    def test_negative_hold_days_returns_error(self):
        result = calc_t1_holding_cost(entry_price=100.0, exit_price=100.0, hold_days=-1)
        assert "error" in result


class TestCalcT1NetReturn:
    def test_returns_percentage_value(self):
        pct = calc_t1_net_return(entry_price=100.0, exit_price=101.0, shares=100)
        assert isinstance(pct, float)
        assert pct > 0

    def test_returns_none_on_error(self):
        pct = calc_t1_net_return(entry_price=0, exit_price=100.0)
        assert pct is None

    def test_passes_kwargs_through(self):
        """kwargs 应透传 hold_days / daily_risk_premium_bps / slippage_bps"""
        pct_no_premium = calc_t1_net_return(
            entry_price=100.0, exit_price=100.0, daily_risk_premium_bps=0, slippage_bps=0,
        )
        pct_with_premium = calc_t1_net_return(
            entry_price=100.0, exit_price=100.0, daily_risk_premium_bps=10, slippage_bps=10,
        )
        # 有溢价时净收益更低
        assert pct_with_premium < pct_no_premium


class TestFormatT1CostReport:
    def test_positive_return_format(self):
        cost = calc_t1_holding_cost(entry_price=100.0, exit_price=105.0, shares=100)
        report = format_t1_cost_report(cost)
        assert "T+1 净收益" in report
        assert "+" in report  # 正收益有 + 号
        assert "%" in report

    def test_negative_return_format(self):
        cost = calc_t1_holding_cost(entry_price=100.0, exit_price=95.0, shares=100)
        report = format_t1_cost_report(cost)
        assert "T+1 净收益" in report
        assert "-" in report  # 负收益有 - 号

    def test_error_format(self):
        report = format_t1_cost_report({"error": "bad input"})
        assert "失败" in report
        assert "bad input" in report

    def test_none_format(self):
        report = format_t1_cost_report(None)
        assert "失败" in report
