"""v4.0 B5 冲击成本模型单元测试

覆盖:
  - _calc_impact_cost_bps 纯函数(各种边界)
  - run_strategy_backtest impact_bps 透传
  - 平方根模型:order_size / ADV 比例越大,冲击越大
  - 上限保护(最大 5x 基础值)
  - 0 关闭时,价格不变
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from services.strategy_backtest_service import (
    run_strategy_backtest,
    _calc_impact_cost_bps,
)


# ═══════════════════════════════════════════════════════════════
#  _calc_impact_cost_bps 纯函数
# ═══════════════════════════════════════════════════════════════


class TestCalcImpactCostBps:
    def test_zero_impact_bps_returns_zero(self):
        """impact_bps=0 → 永远返回 0"""
        result = _calc_impact_cost_bps("600519", 100, 100.0, impact_bps=0)
        assert result == 0.0

    def test_zero_shares_returns_zero(self):
        result = _calc_impact_cost_bps("600519", 0, 100.0, impact_bps=10.0)
        assert result == 0.0

    def test_zero_price_returns_zero(self):
        result = _calc_impact_cost_bps("600519", 100, 0, impact_bps=10.0)
        assert result == 0.0

    def test_no_kline_data_returns_zero(self, db):
        """无 K 线数据 → 返回 0(不应用冲击)"""
        result = _calc_impact_cost_bps("999999", 100, 100.0, impact_bps=10.0)
        assert result == 0.0

    def test_small_order_relative_to_adv_low_impact(self, db):
        """order_size << ADV → 冲击接近 0"""
        # 插入 20 天 K 线,ADV = 100 × 10000 = 1,000,000
        from database import execute
        for i in range(20):
            date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            execute(
                """INSERT INTO historical_kline
                   (stock_code, trade_date, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("888888", date, 100.0, 100.0, 100.0, 100.0, 10000),
            )
        # 买 10 股 @ 100 元 = 1000 元(ADV 的 0.1%)
        # impact = 10 × sqrt(0.001) = 0.316 bps
        result = _calc_impact_cost_bps("888888", 10, 100.0, impact_bps=10.0)
        assert result is not None
        assert 0 < result < 1  # 影响极小

    def test_large_order_higher_impact(self, db):
        """order_size = ADV → 冲击 = base × 1.0 = base"""
        from database import execute
        for i in range(20):
            date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            execute(
                """INSERT INTO historical_kline
                   (stock_code, trade_date, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("777777", date, 100.0, 100.0, 100.0, 100.0, 10000),
            )
        # 买 10000 股 @ 100 元 = 1,000,000 元(ADV 的 100%)
        # impact = 10 × sqrt(1) = 10 bps
        result = _calc_impact_cost_bps("777777", 10000, 100.0, impact_bps=10.0)
        assert result is not None
        # 允许 5% 误差
        assert 9.5 <= result <= 10.5

    def test_impact_capped_at_5x_base(self, db):
        """order_size >> ADV → 冲击封顶 5x base"""
        from database import execute
        for i in range(20):
            date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            execute(
                """INSERT INTO historical_kline
                   (stock_code, trade_date, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("666666", date, 100.0, 100.0, 100.0, 100.0, 10000),
            )
        # 买 10000000 股(100x ADV)→ 理论 impact = 10 × sqrt(100) = 100 bps,但上限 50 bps
        result = _calc_impact_cost_bps("666666", 10000000, 100.0, impact_bps=10.0)
        assert result is not None
        assert result <= 50.0  # 5x 10 = 50


# ═══════════════════════════════════════════════════════════════
#  run_strategy_backtest 集成
# ═══════════════════════════════════════════════════════════════


class TestImpactBacktestIntegration:
    def test_impact_bps_in_config(self, db):
        """config 中包含 impact_bps 字段"""
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
                strategy_ids=["turtle_s1"], stock_codes=["000001"],
                start_date="2024-01-01", end_date="2024-01-02",
                initial_cash=100000, hold_days=1, max_positions=0,
                impact_bps=20.0,
            )
            assert result["config"]["impact_bps"] == 20.0
            assert result["config"]["adv_window"] == 20

    def test_impact_zero_default(self, db):
        """默认 impact_bps=0"""
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
                strategy_ids=["turtle_s1"], stock_codes=["000001"],
                start_date="2024-01-01", end_date="2024-01-02",
                initial_cash=100000, hold_days=1, max_positions=0,
            )
            assert result["config"]["impact_bps"] == 0.0

    def test_impact_higher_means_worse_pnl(self, db):
        """冲击成本越高,净利润越差"""
        def run_with_impact(impact):
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
                       }.get((code, date, ptype), None)), \
                 patch("services.strategy_backtest_service._calc_impact_cost_bps",
                       return_value=impact):  # 强制 mock 返回固定 impact
                return run_strategy_backtest(
                    strategy_ids=["turtle_s1"], stock_codes=["000001"],
                    start_date="2024-01-01", end_date="2024-01-04",
                    initial_cash=100000, hold_days=1,
                    max_positions=1, position_size_pct=1.0,
                    slippage_bps=0, impact_bps=10.0,  # impact_bps 触发调用
                )

        r_low = run_with_impact(5.0)   # 5bps impact
        r_high = run_with_impact(20.0)  # 20bps impact

        sell_low = [t for t in r_low["trades"] if t["direction"] == "sell"]
        sell_high = [t for t in r_high["trades"] if t["direction"] == "sell"]

        # 20bps impact 卖出价应更低
        assert sell_high[0]["price"] < sell_low[0]["price"]


# ═══════════════════════════════════════════════════════════════
#  Agent 工具透传
# ═══════════════════════════════════════════════════════════════


class TestImpactAgentToolSchema:
    def test_run_backtest_schema_includes_impact(self):
        from services.agent_tools import TOOL_RUN_BACKTEST
        params = TOOL_RUN_BACKTEST["function"]["parameters"]
        assert "impact_bps" in params["properties"]
        assert params["properties"]["impact_bps"]["default"] == 0.0
