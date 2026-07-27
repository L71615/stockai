"""B4 滑点模型单元测试 — v4.0

验证:
  - run_strategy_backtest 接受 slippage_bps 参数,默认 10bps
  - 买入价 = 原始价 × (1 + slippage_bps/10000)
  - 卖出价 = 原始价 × (1 - slippage_bps/10000)
  - config 字段包含 slippage_bps
  - slippage_bps=0 时,价格不调整(向后兼容)
"""

import pytest
from unittest.mock import patch

from services.strategy_backtest_service import run_strategy_backtest


# ═══════════════════════════════════════════════════════════════
#  Slippage 在工具 / schema 层的暴露
# ═══════════════════════════════════════════════════════════════


class TestSlippageSchemaExposure:
    def test_run_backtest_schema_includes_slippage(self):
        from services.agent_tools import TOOL_RUN_BACKTEST
        params = TOOL_RUN_BACKTEST["function"]["parameters"]
        assert "slippage_bps" in params["properties"]
        assert params["properties"]["slippage_bps"]["default"] == 10.0
        assert params["properties"]["slippage_bps"]["type"] == "number"

    def test_run_backtest_schema_description_mentions_slippage(self):
        from services.agent_tools import TOOL_RUN_BACKTEST
        desc = TOOL_RUN_BACKTEST["function"]["description"]
        assert "滑点" in desc
        assert "10bps" in desc


# ═══════════════════════════════════════════════════════════════
#  Slippage 参数传递
# ═══════════════════════════════════════════════════════════════


class TestSlippagePassthrough:
    """用 mock 验证 slippage_bps 被正确传递并出现在 config 中"""

    def test_slippage_default_10bps_in_config(self, db):
        """不传 slippage_bps → config 中应为默认 10.0"""
        # 用一个简单的回测,检查 config.slippage_bps 字段
        # 这里不调真实 DB,直接 patch 数据源
        with patch("services.strategy_backtest_service._get_trading_dates",
                   return_value=["2024-01-01", "2024-01-02", "2024-01-03"]), \
             patch("services.strategy_backtest_service._get_benchmark_curve",
                   return_value=[]), \
             patch("services.strategy_backtest_service._load_strategy_conditions",
                   return_value={"type": "and", "children": []}), \
             patch("services.strategy_backtest_service._filter_rebalance_dates",
                   return_value=["2024-01-01"]), \
             patch("services.strategy_backtest_service._screen_stocks",
                   return_value=[]):
            result = run_strategy_backtest(
                strategy_ids=["turtle_s1"],
                stock_codes=["000001"],
                start_date="2024-01-01",
                end_date="2024-01-03",
                initial_cash=100000,
                hold_days=1,
                max_positions=0,  # 不实际买入
            )
            assert "config" in result
            assert result["config"]["slippage_bps"] == 10.0

    def test_slippage_custom_value_in_config(self, db):
        """显式传 slippage_bps=20 → config 中应为 20.0"""
        with patch("services.strategy_backtest_service._get_trading_dates",
                   return_value=["2024-01-01", "2024-01-02"]), \
             patch("services.strategy_backtest_service._get_benchmark_curve",
                   return_value=[]), \
             patch("services.strategy_backtest_service._load_strategy_conditions",
                   return_value={"type": "and", "children": []}), \
             patch("services.strategy_backtest_service._filter_rebalance_dates",
                   return_value=["2024-01-01"]), \
             patch("services.strategy_backtest_service._screen_stocks",
                   return_value=[]):
            result = run_strategy_backtest(
                strategy_ids=["turtle_s1"],
                stock_codes=["000001"],
                start_date="2024-01-01",
                end_date="2024-01-02",
                initial_cash=100000,
                hold_days=1,
                max_positions=0,
                slippage_bps=20.0,
            )
            assert result["config"]["slippage_bps"] == 20.0

    def test_slippage_zero_keeps_prices_unchanged(self, db):
        """slippage_bps=0 → 价格不变(向后兼容)"""
        with patch("services.strategy_backtest_service._get_trading_dates",
                   return_value=["2024-01-01", "2024-01-02"]), \
             patch("services.strategy_backtest_service._get_benchmark_curve",
                   return_value=[]), \
             patch("services.strategy_backtest_service._load_strategy_conditions",
                   return_value={"type": "and", "children": []}), \
             patch("services.strategy_backtest_service._filter_rebalance_dates",
                   return_value=["2024-01-01"]), \
             patch("services.strategy_backtest_service._screen_stocks",
                   return_value=[]):
            result = run_strategy_backtest(
                strategy_ids=["turtle_s1"],
                stock_codes=["000001"],
                start_date="2024-01-01",
                end_date="2024-01-02",
                initial_cash=100000,
                hold_days=1,
                max_positions=0,
                slippage_bps=0,
            )
            assert result["config"]["slippage_bps"] == 0
            # 无交易 → 但 config 字段已正确


# ═══════════════════════════════════════════════════════════════
#  Slippage 价格调整逻辑 — 单元测试(直接验证 _slip_factor 行为)
# ═══════════════════════════════════════════════════════════════


class TestSlippagePriceAdjustment:
    """通过 mock 内部数据流,验证买卖价调整的正确性"""

    def test_buy_price_adjusted_upward_by_slippage(self, db):
        """买入价 = 原始价 × (1 + 0.001) = 100.0 × 1.001 = 100.10"""
        with patch("services.strategy_backtest_service._get_trading_dates",
                   return_value=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]), \
             patch("services.strategy_backtest_service._get_benchmark_curve",
                   return_value=[]), \
             patch("services.strategy_backtest_service._load_strategy_conditions",
                   return_value={"type": "and", "children": []}), \
             patch("services.strategy_backtest_service._filter_rebalance_dates",
                   return_value=["2024-01-01", "2024-01-02", "2024-01-03"]), \
             patch("services.strategy_backtest_service._screen_stocks",
                   side_effect=[
                       # 第 1 次:返回 1 只候选 → 触发买入
                       [{"code": "000001", "name": "测试"}],
                       # 第 2 次:返回空 → 已有持仓
                       [],
                       # 第 3 次:返回空 → 触发卖出
                       [],
                   ]), \
             patch("services.strategy_backtest_service._get_price_on_date",
                   side_effect=lambda code, date, ptype: {
                       ("000001", "2024-01-02", "open"): 100.0,  # 买入日开盘
                       ("000001", "2024-01-04", "open"): 110.0,  # 卖出日开盘
                   }.get((code, date, ptype), None)):
            result = run_strategy_backtest(
                strategy_ids=["turtle_s1"],
                stock_codes=["000001"],
                start_date="2024-01-01",
                end_date="2024-01-04",
                initial_cash=100000,
                hold_days=1,
                max_positions=1,
                position_size_pct=1.0,
                slippage_bps=10.0,  # 10bps = 0.1%
            )

            assert "error" not in result
            trades = result.get("trades", [])
            assert len(trades) >= 2  # 至少 1 买 + 1 卖

            # 找买入交易
            buy_trades = [t for t in trades if t["direction"] == "buy"]
            assert len(buy_trades) >= 1
            # 100.0 × (1 + 0.001) = 100.10
            assert abs(buy_trades[0]["price"] - 100.10) < 0.01

            # 找卖出交易
            sell_trades = [t for t in trades if t["direction"] == "sell"]
            assert len(sell_trades) >= 1
            # 110.0 × (1 - 0.001) = 109.89
            assert abs(sell_trades[0]["price"] - 109.89) < 0.01

    def test_buy_price_unchanged_when_slippage_zero(self, db):
        """slippage_bps=0 → 买入价不变"""
        with patch("services.strategy_backtest_service._get_trading_dates",
                   return_value=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]), \
             patch("services.strategy_backtest_service._get_benchmark_curve",
                   return_value=[]), \
             patch("services.strategy_backtest_service._load_strategy_conditions",
                   return_value={"type": "and", "children": []}), \
             patch("services.strategy_backtest_service._filter_rebalance_dates",
                   return_value=["2024-01-01", "2024-01-02", "2024-01-03"]), \
             patch("services.strategy_backtest_service._screen_stocks",
                   side_effect=[[{"code": "000001", "name": "测试"}], [], []]), \
             patch("services.strategy_backtest_service._get_price_on_date",
                   side_effect=lambda code, date, ptype: {
                       ("000001", "2024-01-02", "open"): 100.0,
                       ("000001", "2024-01-04", "open"): 110.0,
                   }.get((code, date, ptype), None)):
            result = run_strategy_backtest(
                strategy_ids=["turtle_s1"],
                stock_codes=["000001"],
                start_date="2024-01-01",
                end_date="2024-01-04",
                initial_cash=100000,
                hold_days=1,
                max_positions=1,
                position_size_pct=1.0,
                slippage_bps=0,
            )

            trades = result.get("trades", [])
            buy_trades = [t for t in trades if t["direction"] == "buy"]
            assert abs(buy_trades[0]["price"] - 100.0) < 0.01

            sell_trades = [t for t in trades if t["direction"] == "sell"]
            assert abs(sell_trades[0]["price"] - 110.0) < 0.01

    def test_higher_slippage_means_worse_pnl(self, db):
        """滑点越高,净利润越差(对比 0bps vs 20bps)"""
        def run_with_slippage(slip):
            with patch("services.strategy_backtest_service._get_trading_dates",
                       return_value=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]), \
                 patch("services.strategy_backtest_service._get_benchmark_curve",
                       return_value=[]), \
                 patch("services.strategy_backtest_service._load_strategy_conditions",
                       return_value={"type": "and", "children": []}), \
                 patch("services.strategy_backtest_service._filter_rebalance_dates",
                       return_value=["2024-01-01", "2024-01-02", "2024-01-03"]), \
                 patch("services.strategy_backtest_service._screen_stocks",
                       side_effect=[[{"code": "000001", "name": "测试"}], [], []]), \
                 patch("services.strategy_backtest_service._get_price_on_date",
                       side_effect=lambda code, date, ptype: {
                           ("000001", "2024-01-02", "open"): 100.0,
                           ("000001", "2024-01-04", "open"): 110.0,
                       }.get((code, date, ptype), None)):
                return run_strategy_backtest(
                    strategy_ids=["turtle_s1"],
                    stock_codes=["000001"],
                    start_date="2024-01-01",
                    end_date="2024-01-04",
                    initial_cash=100000,
                    hold_days=1,
                    max_positions=1,
                    position_size_pct=1.0,
                    slippage_bps=slip,
                )

        r0 = run_with_slippage(0)
        r20 = run_with_slippage(20)

        sell_trades_0 = [t for t in r0["trades"] if t["direction"] == "sell"]
        sell_trades_20 = [t for t in r20["trades"] if t["direction"] == "sell"]

        pnl_0 = sell_trades_0[0]["pnl"]
        pnl_20 = sell_trades_20[0]["pnl"]

        # 20bps 滑点应比 0bps 净利润少
        assert pnl_20 < pnl_0
