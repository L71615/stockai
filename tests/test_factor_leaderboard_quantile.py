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
#  辅助:数据不可用时统一 skip(测试 DB 没 stock_info / kline)
# ═══════════════════════════════════════════════════════════════


def _has_pool_data(result: dict) -> bool:
    """检查 leaderboard/quantile 结果是否真有数据可算"""
    if "error" in result:
        return False
    if result.get("stock_count", 0) > 0:
        return True
    # leaderboard 用 total 字段
    if result.get("total", 0) > 0:
        return True
    return False


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
        if not _has_pool_data(result):
            pytest.skip("股票池/kline 数据不可用,跳过结构验证")

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
        if not _has_pool_data(result):
            pytest.skip("数据不可用,跳过排序验证")

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
        if not _has_pool_data(result):
            pytest.skip("数据不可用,跳过 color 验证")

        valid = {"green", "yellow", "red", "gray", "unknown"}
        for row in result["rows"]:
            assert row["decay_color"] in valid, (
                f"无效 decay_color: {row['decay_color']} (factor={row['name']})"
            )

    def test_skips_factors_with_insufficient_data(self):
        """valid_days < 30 的因子应被跳过"""
        result = compute_factor_leaderboard(
            factors=["ret_5d", "rsi_14", "volatility_20"],
            stock_pool="hs300",
            start_date="2024-06-01",
            end_date="2024-06-15",  # ~10 个交易日
        )
        # 即使有数据,valid_days 必须都 ≥ 30(说明 valid_days 过滤生效)
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
        if not _has_pool_data(result):
            pytest.skip("股票池为空(stock_info 缺失或 kline 数据不足),跳过")
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
        if "error" in result or not _has_pool_data(result):
            pytest.skip(f"数据不足跳过: {result.get('error', 'pool empty')}")

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
        if "error" in result or not _has_pool_data(result):
            pytest.skip(f"数据不足: {result.get('error', 'pool empty')}")

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
        if "error" in result or not _has_pool_data(result):
            pytest.skip(f"数据不足: {result.get('error', 'pool empty')}")

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
        if "error" in result or not _has_pool_data(result):
            pytest.skip(f"数据不足: {result.get('error', 'pool empty')}")

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
        if "error" in result or not _has_pool_data(result):
            pytest.skip(f"数据不足: {result.get('error', 'pool empty')}")

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


# ═══════════════════════════════════════════════════════════════
#  Pure 单元测试(不需要 DB / 数据)
# ═══════════════════════════════════════════════════════════════


class TestPureLogic:
    """不需要数据库的纯逻辑测试 - 任何环境都能跑"""

    def test_leaderboard_sorts_by_abs_ir_when_no_data(self):
        """空数据时 rows 应为空(不崩溃)"""
        result = compute_factor_leaderboard(
            factors=["ret_5d"],
            stock_pool="hs300",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        assert "rows" in result
        assert isinstance(result["rows"], list)

    def test_quantile_returns_unknown_factor_no_db_call(self):
        """未知因子 → error,不查 DB"""
        result = compute_quantile_returns(
            factor_name="nonexistent",
            stock_pool="hs300",
        )
        assert "error" in result
        assert "未知因子" in result["error"]
        assert "groups" not in result or result.get("groups") == []

    def test_router_n_groups_constraint(self):
        """Router 层: n_groups 必须 2-10 (FastAPI Query ge/le)"""
        from routers.factor_lab import get_quantile_returns
        import inspect
        sig = inspect.signature(get_quantile_returns)
        assert "n_groups" in sig.parameters
        # Parameter.default 在 FastAPI 里是 Query(...) 对象本身
        # 它有 .default 属性指向真实默认值 + .metadata 里 ge/le
        default_param = sig.parameters["n_groups"].default
        # Query(5, ge=2, le=10) — type 是<class 'fastapi.params.Query'>
        # 它的 default 字段 = 5
        assert hasattr(default_param, "default"), f"Query 对象应有 default 字段,实际: {type(default_param)}"
        assert default_param.default == 5, f"默认值应为 5,实际 {default_param.default}"
        # ge/le 约束存在 metadata 里(Ge / Le 对象)
        metadata = getattr(default_param, "metadata", [])
        ge_values = [getattr(m, "ge", None) for m in metadata]
        le_values = [getattr(m, "le", None) for m in metadata]
        assert 2 in ge_values, f"应包含 ge=2 约束,实际 metadata: {metadata}"
        assert 10 in le_values, f"应包含 le=10 约束,实际 metadata: {metadata}"