"""v4.0 B6 多策略组合回测单元测试

覆盖:
  - run_combined_backtest 三种合并模式 (union/intersect/majority)
  - 边界: 空策略列表 / 无效模式
  - 组合 vs 单策略 metrics 对比
  - trade_attribution 统计
  - per_strategy 排序
"""

from unittest.mock import patch

import pytest

from services.strategy_backtest_service import run_combined_backtest


# ═══════════════════════════════════════════════════════════════
#  基础结构
# ═══════════════════════════════════════════════════════════════


class TestCombinedBacktestStructure:
    def test_empty_strategies_returns_error(self, db):
        result = run_combined_backtest(strategy_ids=[])
        assert "error" in result

    def test_invalid_mode_returns_error(self, db):
        result = run_combined_backtest(
            strategy_ids=["turtle_s1", "momentum"],
            combination_mode="invalid_mode",
        )
        assert "error" in result
        assert "available" in result
        assert set(result["available"]) == {"union", "intersect", "majority"}

    def test_returns_expected_keys(self, db):
        """返回结构应包含 combination_mode / strategy_count / combined / per_strategy"""
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value={
                       "strategies": [
                           {"strategy_id": "s1", "strategy_name": "S1",
                            "metrics": {"total_return": 0.1, "sharpe": 1.2, "max_drawdown": 0.05, "win_rate": 0.6, "num_trades": 10},
                            "trades": []}
                       ],
                       "ranking": [],
                   }):
            result = run_combined_backtest(strategy_ids=["s1"])
        assert "combination_mode" in result
        assert "strategy_count" in result
        assert "combined" in result
        assert "per_strategy" in result

    def test_strategy_count_matches(self, db):
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value={
                       "strategies": [
                           {"strategy_id": f"s{i}", "strategy_name": f"S{i}",
                            "metrics": {"total_return": 0.1}, "trades": []}
                           for i in range(3)
                       ],
                       "ranking": [],
                   }):
            result = run_combined_backtest(strategy_ids=["s1", "s2", "s3"])
        assert result["strategy_count"] == 3


# ═══════════════════════════════════════════════════════════════
#  合并模式
# ═══════════════════════════════════════════════════════════════


class TestCombinationModes:
    def _make_strategies(self, signal_patterns):
        """signal_patterns: [{strategy_id, signals: [(date, code)]}]"""
        strategies = []
        for sp in signal_patterns:
            trades = [
                {"id": i, "date": d, "code": c, "direction": "buy",
                 "price": 100.0, "shares": 100, "pnl": None, "pnl_pct": None,
                 "name": c}
                for i, (d, c) in enumerate(sp["signals"])
            ]
            strategies.append({
                "strategy_id": sp["strategy_id"],
                "strategy_name": sp["strategy_id"].upper(),
                "metrics": {"total_return": 0.1, "sharpe": 1.0, "max_drawdown": 0.05, "win_rate": 0.6, "num_trades": len(trades)},
                "trades": trades,
            })
        return {"strategies": strategies, "ranking": []}

    def test_union_includes_any_signal(self, db):
        """union: 任一策略触发即入选"""
        # 3 个策略,A 触发 X,B 触发 Y(都不重合)→ union 入选 2 个
        signal_patterns = [
            {"strategy_id": "A", "signals": [("2024-01-02", "000001")]},
            {"strategy_id": "B", "signals": [("2024-01-02", "000002")]},
            {"strategy_id": "C", "signals": []},
        ]
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value=self._make_strategies(signal_patterns)):
            result = run_combined_backtest(
                strategy_ids=["A", "B", "C"], combination_mode="union",
            )
        assert result["combined"]["metrics"]["num_trades"] == 2
        codes = {t["code"] for t in result["combined"]["trades"]}
        assert codes == {"000001", "000002"}

    def test_intersect_requires_all(self, db):
        """intersect: 所有策略同时触发才入选"""
        # 3 个策略,A 和 B 都触发 X → intersect 入选 1 个
        signal_patterns = [
            {"strategy_id": "A", "signals": [("2024-01-02", "000001")]},
            {"strategy_id": "B", "signals": [("2024-01-02", "000001")]},
            {"strategy_id": "C", "signals": [("2024-01-02", "000001")]},
        ]
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value=self._make_strategies(signal_patterns)):
            result = run_combined_backtest(
                strategy_ids=["A", "B", "C"], combination_mode="intersect",
            )
        assert result["combined"]["metrics"]["num_trades"] == 1
        # 触发策略列表应包含所有 3 个
        assert sorted(result["combined"]["trades"][0]["triggering_strategies"]) == ["A", "B", "C"]

    def test_majority_2_of_3(self, db):
        """majority: 3 策略中 ≥2 触发才入选"""
        # A 和 B 都触发 X(2/3),C 不触发 → majority 入选 X
        # D 单独触发(1/3)→ 不入选
        signal_patterns = [
            {"strategy_id": "A", "signals": [("2024-01-02", "000001")]},
            {"strategy_id": "B", "signals": [("2024-01-02", "000001"), ("2024-01-02", "000003")]},
            {"strategy_id": "C", "signals": [("2024-01-02", "000001")]},
        ]
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value=self._make_strategies(signal_patterns)):
            result = run_combined_backtest(
                strategy_ids=["A", "B", "C"], combination_mode="majority",
            )
        codes = {t["code"] for t in result["combined"]["trades"]}
        # 000001 出现 3 次(过 majority),000003 出现 1 次(未过)
        assert "000001" in codes
        assert "000003" not in codes

    def test_majority_with_2_strategies_requires_both(self, db):
        """majority 在 2 个策略时 = intersect(2/2+1=2)"""
        signal_patterns = [
            {"strategy_id": "A", "signals": [("2024-01-02", "000001")]},
            {"strategy_id": "B", "signals": []},  # 不触发
        ]
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value=self._make_strategies(signal_patterns)):
            result = run_combined_backtest(
                strategy_ids=["A", "B"], combination_mode="majority",
            )
        # A 单独触发 → 未达 2/2 → 不入选
        assert result["combined"]["metrics"]["num_trades"] == 0


# ═══════════════════════════════════════════════════════════════
#  Attribution + per_strategy
# ═══════════════════════════════════════════════════════════════


class TestAttributionAndPerStrategy:
    def test_trade_attribution_counts(self, db):
        """trade_attribution 统计每个策略触发的交易数"""
        # A 触发 2 次,B 触发 1 次,union 全部入选 → A=2, B=1
        signal_patterns = [
            {"strategy_id": "A", "signals": [("2024-01-02", "000001"), ("2024-01-03", "000002")]},
            {"strategy_id": "B", "signals": [("2024-01-02", "000003")]},
        ]
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value={
                       "strategies": [
                           {"strategy_id": sp["strategy_id"], "strategy_name": sp["strategy_id"],
                            "metrics": {"total_return": 0.1, "sharpe": 1.0, "max_drawdown": 0.05, "win_rate": 0.6, "num_trades": 0},
                            "trades": [{"id": i, "date": d, "code": c, "direction": "buy",
                                        "price": 100.0, "shares": 100, "pnl": None, "pnl_pct": None, "name": c}
                                       for i, (d, c) in enumerate(sp["signals"])]}
                           for sp in signal_patterns
                       ],
                       "ranking": [],
                   }):
            result = run_combined_backtest(
                strategy_ids=["A", "B"], combination_mode="union",
            )
        attr = result["combined"]["trade_attribution"]
        assert attr["A"] == 2
        assert attr["B"] == 1

    def test_per_strategy_metrics(self, db):
        """per_strategy 包含每个策略的独立指标"""
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value={
                       "strategies": [
                           {"strategy_id": "A", "strategy_name": "Turtle",
                            "metrics": {"total_return": 0.15, "sharpe": 1.5, "max_drawdown": 0.08, "win_rate": 0.7, "num_trades": 20},
                            "trades": []},
                           {"strategy_id": "B", "strategy_name": "Momentum",
                            "metrics": {"total_return": 0.10, "sharpe": 1.0, "max_drawdown": 0.10, "win_rate": 0.6, "num_trades": 15},
                            "trades": []},
                       ],
                       "ranking": [],
                   }):
            result = run_combined_backtest(strategy_ids=["A", "B"])
        per = result["per_strategy"]
        assert len(per) == 2
        a = next(s for s in per if s["strategy_id"] == "A")
        assert a["strategy_name"] == "Turtle"
        assert a["total_return"] == 0.15

    def test_combined_metrics_average(self, db):
        """combined metrics 是各策略的算术平均(交易数计 combined 实际通过数)"""
        # A 触发 1 次 X,B 触发 1 次 X(同票)→ union 通过 1 个
        signal_patterns = [
            {"strategy_id": "A", "signals": [("2024-01-02", "000001")]},
            {"strategy_id": "B", "signals": [("2024-01-02", "000001")]},
        ]
        with patch("services.strategy_backtest_service.compare_strategies",
                   return_value={
                       "strategies": [
                           {"strategy_id": "A", "strategy_name": "A",
                            "metrics": {"total_return": 0.20, "sharpe": 1.0, "max_drawdown": 0.10, "win_rate": 0.6, "num_trades": 1},
                            "trades": [{"id": 1, "date": "2024-01-02", "code": "000001", "direction": "buy", "price": 100, "shares": 100, "pnl": None, "pnl_pct": None, "name": "X"}]},
                           {"strategy_id": "B", "strategy_name": "B",
                            "metrics": {"total_return": 0.10, "sharpe": 0.5, "max_drawdown": 0.05, "win_rate": 0.5, "num_trades": 1},
                            "trades": [{"id": 1, "date": "2024-01-02", "code": "000001", "direction": "buy", "price": 100, "shares": 100, "pnl": None, "pnl_pct": None, "name": "X"}]},
                       ],
                       "ranking": [],
                   }):
            result = run_combined_backtest(strategy_ids=["A", "B"], combination_mode="union")
        cm = result["combined"]["metrics"]
        # 平均: (0.20 + 0.10) / 2 = 0.15
        assert cm["total_return"] == 0.15
        # combined 通过 1 个交易(A 和 B 都触发,union 去重)
        assert cm["num_trades"] == 1
