"""因子排行榜 + 分位数收益 单元测试

P0-1 leaderboard:  复用 IC 计算,扁平排序输出
P0-2 quantile_returns: alphalens 风格分组累计收益

测试只用小股票池(hs300 5 只),避免冲撞 dev DB 上其他重查询。
"""
import pytest

from services.factor_lab import (
    compute_factor_leaderboard,
    compute_quantile_returns,
)


# ═══════════════════════════════════════════════════════════════
#  P0-1 Leaderboard
# ═══════════════════════════════════════════════════════════════


class TestFactorLeaderboard:
    def test_returns_flat_rows_with_required_fields(self):
        """排行榜返回扁平行 + 必备字段"""
        result = compute_factor_leaderboard(
            factors=["ret_5d", "rsi_14", "ma_disp_5"],
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        assert "rows" in result
        assert "total" in result
        assert result["total"] == len(result["rows"])

        if result["total"] > 0:
            row = result["rows"][0]
            required = {
                "name", "ic_mean", "ic_std", "ir", "win_rate",
                "turnover", "decay_score", "decay_status", "decay_color",
                "valid_days",
            }
            assert required.issubset(row.keys()), f"缺字段: {required - row.keys()}"

    def test_sorted_by_abs_ir_desc(self):
        """默认按 |IR| 降序(最强因子在前)"""
        result = compute_factor_leaderboard(
            factors=["ret_5d", "rsi_14", "volatility_20", "ma_disp_5"],
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        irs = [abs(r["ir"]) for r in result["rows"]]
        assert irs == sorted(irs, reverse=True), f"应按 |IR| 降序,实际: {irs}"

    def test_decay_color_one_of_valid_set(self):
        """decay_color 必须是 green / yellow / red / gray 之一"""
        result = compute_factor_leaderboard(
            factors=["ret_5d"],
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        valid = {"green", "yellow", "red", "gray", "unknown"}
        for row in result["rows"]:
            assert row["decay_color"] in valid, (
                f"无效 decay_color: {row['decay_color']} (factor={row['name']})"
            )

    def test_skips_factors_with_insufficient_data(self):
        """valid_days < 30 的因子应被跳过"""
        # 极短日期窗口 → 多数因子 IC 不足 30 天
        result = compute_factor_leaderboard(
            factors=["ret_5d", "rsi_14", "volatility_20"],
            stock_pool="hs300",
            start_date="2024-06-01",
            end_date="2024-06-15",  # ~10 个交易日
        )
        for row in result["rows"]:
            assert row["valid_days"] >= 30, (
                f"valid_days 应 ≥30,实际: {row['valid_days']} (factor={row['name']})"
            )

    def test_default_uses_all_factors(self):
        """factors=None 时应扫描全注册表"""
        result = compute_factor_leaderboard(
            factors=None,
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        # 应该有不少因子(55+ 注册因子)
        assert result["total"] >= 1  # 至少 1 个有足够数据


# ═══════════════════════════════════════════════════════════════
#  P0-2 Quantile Returns
# ═══════════════════════════════════════════════════════════════


class TestQuantileReturns:
    def test_returns_groups_and_long_short(self):
        """返回 5 组 + 多空对冲曲线"""
        result = compute_quantile_returns(
            factor_name="ret_5d",
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
            n_groups=5,
        )
        if "error" in result:
            pytest.skip(f"数据不足跳过: {result['error']}")

        assert "groups" in result
        assert "long_short" in result
        assert "dates" in result
        assert len(result["groups"]) == 5
        # 多空对冲必须有同长度
        ls = result["long_short"]
        assert len(ls["daily_ret"]) == len(ls["cumret"])
        assert len(ls["cumret"]) == len(result["dates"])

    def test_groups_have_consistent_length(self):
        """每组的 daily_ret / cumret 长度应等于 dates 数"""
        result = compute_quantile_returns(
            factor_name="ret_5d",
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
            n_groups=5,
        )
        if "error" in result:
            pytest.skip(f"数据不足: {result['error']}")

        n_dates = len(result["dates"])
        for g in result["groups"]:
            assert len(g["daily_ret"]) == n_dates, (
                f"组 {g['group']} daily_ret 长度不匹配"
            )
            assert len(g["cumret"]) == n_dates

    def test_cumret_starts_from_zero(self):
        """累计收益应从 0 起步(cumprod(1+r) - 1 在 r=0 时 = 0)"""
        result = compute_quantile_returns(
            factor_name="ret_5d",
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
            n_groups=5,
        )
        if "error" in result:
            pytest.skip(f"数据不足: {result['error']}")

        for g in result["groups"]:
            assert abs(g["cumret"][0]) < 1e-6, (
                f"cumret[0] 应 ≈ 0,实际 {g['cumret'][0]} (group={g['group']})"
            )

    def test_long_short_is_qn_minus_q1(self):
        """多空对冲 = QN 收益 - Q1 收益(每日)"""
        result = compute_quantile_returns(
            factor_name="ret_5d",
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
            n_groups=5,
        )
        if "error" in result:
            pytest.skip(f"数据不足: {result['error']}")

        q1 = result["groups"][0]["daily_ret"]
        q5 = result["groups"][4]["daily_ret"]
        ls = result["long_short"]["daily_ret"]

        for i, (l, s, expected) in enumerate(zip(q5, q1, ls)):
            actual = round(l - s, 6)
            assert abs(actual - expected) < 1e-5, (
                f"第 {i} 天多空对冲 = Q5-Q1 应为 {actual}, 实际 {expected}"
            )

    def test_summary_has_monotonic_flag(self):
        """summary 应包含 monotonic 单调性标志"""
        result = compute_quantile_returns(
            factor_name="ret_5d",
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
            n_groups=5,
        )
        if "error" in result:
            pytest.skip(f"数据不足: {result['error']}")

        summary = result["summary"]
        assert "monotonic" in summary
        assert "long_short_cumret" in summary
        assert "long_short_sharpe" in summary
        assert isinstance(summary["monotonic"], bool)

    def test_unknown_factor_returns_error(self):
        """未知因子应返回 error,不抛异常"""
        result = compute_quantile_returns(
            factor_name="definitely_not_a_real_factor_xyz",
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        assert "error" in result
        assert "未知因子" in result["error"]

    def test_custom_n_groups(self):
        """支持 2-10 自定义分组数"""
        result = compute_quantile_returns(
            factor_name="ret_5d",
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
            n_groups=3,
        )
        if "error" not in result:
            assert result["n_groups"] == 3
            assert len(result["groups"]) == 3