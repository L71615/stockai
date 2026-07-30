"""risk_guard 单元测试

覆盖:
  - 4 条规则按严重度触发
  - 边界:无效净值、0 持仓、全仓
  - 默认阈值 vs 自定义阈值
  - 全部 ALLOW 时不误报
  - LIQUIDATE_ALL > BLOCK_BUY 优先级
"""
import pytest

from services.risk_guard import RiskAction, RiskCheckResult, RiskLimits, check_risk


# ═══════════════════════════════════════════════════════════════
#  默认阈值 + 全部 OK
# ═══════════════════════════════════════════════════════════════


class TestAllow:
    def test_normal_healthy_portfolio(self):
        """健康组合:小幅盈利,合理仓位 → ALLOW"""
        result = check_risk(
            current_nav=105_000,
            positions={"600519": 20_000, "000001": 15_000},  # 总仓位 ~33%
            day_start_nav=100_000,
            peak_nav=110_000,
        )
        assert result.action == RiskAction.ALLOW
        assert result.reason == "OK"
        assert result.total_exposure_pct == pytest.approx(0.3333, abs=0.001)
        assert result.drawdown_pct < 0  # 离峰值有回撤

    def test_zero_positions(self):
        """空仓 → ALLOW"""
        result = check_risk(
            current_nav=100_000,
            positions={},
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.ALLOW
        assert result.total_exposure_pct == 0.0


# ═══════════════════════════════════════════════════════════════
#  规则 1: 最大回撤 → LIQUIDATE_ALL
# ═══════════════════════════════════════════════════════════════


class TestMaxDrawdown:
    def test_drawdown_exceeds_threshold_liquidates(self):
        """回撤 25% > 20% → LIQUIDATE_ALL"""
        result = check_risk(
            current_nav=82_000,  # 从 110k 跌到 82k → -25.5%
            positions={"600519": 20_000},
            day_start_nav=100_000,
            peak_nav=110_000,
        )
        assert result.action == RiskAction.LIQUIDATE_ALL
        assert "最大回撤" in result.reason
        assert result.drawdown_pct < -0.20

    def test_drawdown_at_exact_threshold_allows(self):
        """回撤恰好 = 阈值(20%)→ ALLOW(> 不是 >=)"""
        # 数据设计:day_start_nav = current_nav → 无日亏压力
        result = check_risk(
            current_nav=88_000,  # 110k * 0.80 = 88k → -20%
            positions={},
            day_start_nav=88_000,  # 等于 current → daily_loss=0
            peak_nav=110_000,
        )
        assert result.action == RiskAction.ALLOW
        assert result.drawdown_pct == pytest.approx(-0.20, abs=0.001)

    def test_drawdown_just_below_threshold_allows(self):
        """回撤 19% < 20% → ALLOW(单仓位不超限)"""
        # 用 3 个小仓位避免触发单品种规则
        result = check_risk(
            current_nav=89_100,  # 110k * 0.81 → -19%
            positions={"A": 8_000, "B": 8_000, "C": 8_000},  # 总 24_000,各 9%
            day_start_nav=89_100,
            peak_nav=110_000,
        )
        assert result.action == RiskAction.ALLOW
        assert -0.20 < result.drawdown_pct < -0.18


# ═══════════════════════════════════════════════════════════════
#  规则 2: 日亏损 → BLOCK_BUY
# ═══════════════════════════════════════════════════════════════


class TestDailyLoss:
    def test_daily_loss_6pct_blocks_buy(self):
        """当日亏 6% > 5% → BLOCK_BUY"""
        result = check_risk(
            current_nav=94_000,
            positions={"X": 30_000},
            day_start_nav=100_000,
            peak_nav=100_000,  # 无回撤压力
        )
        assert result.action == RiskAction.BLOCK_BUY
        assert "日亏损" in result.reason
        assert result.daily_loss_pct < -0.05

    def test_daily_profit_allows(self):
        """当日盈利 → ALLOW"""
        result = check_risk(
            current_nav=103_000,
            positions={"X": 30_000},
            day_start_nav=100_000,
            peak_nav=103_000,
        )
        assert result.action == RiskAction.ALLOW


# ═══════════════════════════════════════════════════════════════
#  规则 3: 单品种仓位 → BLOCK_BUY
# ═══════════════════════════════════════════════════════════════


class TestSinglePosition:
    def test_single_position_over_30pct_blocks(self):
        """单品种 35% > 30% → BLOCK_BUY"""
        result = check_risk(
            current_nav=100_000,
            positions={"600519": 35_000},  # 35%
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.BLOCK_BUY
        assert "600519" in result.reason
        assert "仓位超标" in result.reason
        assert result.max_position_symbol == "600519"
        assert result.max_position_pct_actual == pytest.approx(0.35, abs=0.001)

    def test_multiple_positions_one_over_blocks(self):
        """多品种,只有 1 个超标 → BLOCK_BUY"""
        result = check_risk(
            current_nav=100_000,
            positions={"A": 10_000, "B": 35_000, "C": 15_000},  # B 超标
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.BLOCK_BUY
        assert "B" in result.reason

    def test_all_under_limit_allows(self):
        """所有品种都 ≤ 30% → ALLOW"""
        result = check_risk(
            current_nav=100_000,
            positions={"A": 20_000, "B": 25_000, "C": 30_000},  # 都没超
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.ALLOW


# ═══════════════════════════════════════════════════════════════
#  规则 4: 总仓位 → BLOCK_BUY
# ═══════════════════════════════════════════════════════════════


class TestTotalExposure:
    def test_total_exposure_85pct_blocks(self):
        """总仓位 85% > 80% → BLOCK_BUY"""
        result = check_risk(
            current_nav=100_000,
            positions={"A": 30_000, "B": 30_000, "C": 25_000},  # 85k = 85%
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.BLOCK_BUY
        assert "总仓位" in result.reason
        assert result.total_exposure_pct == pytest.approx(0.85, abs=0.001)

    def test_total_exposure_at_80pct_allows(self):
        """总仓位 = 80% → ALLOW(> not >=)

        注意: 单品种仓位 ≤ 30%,所以用 4 个 20k 仓位才能让总仓位到 80%
        """
        result = check_risk(
            current_nav=100_000,
            positions={"A": 20_000, "B": 20_000, "C": 20_000, "D": 20_000},  # 80k = 80%
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.ALLOW
        assert result.total_exposure_pct == pytest.approx(0.80, abs=0.001)


# ═══════════════════════════════════════════════════════════════
#  优先级测试
# ═══════════════════════════════════════════════════════════════


class TestPriority:
    def test_max_drawdown_takes_priority_over_daily_loss(self):
        """最大回撤比日亏损严重 → LIQUIDATE_ALL 优先"""
        result = check_risk(
            current_nav=70_000,
            positions={"X": 30_000},
            day_start_nav=100_000,
            peak_nav=100_000,  # -30% 回撤
        )
        # 既触发日亏 (-30%) 又触发回撤 (-30%) → LIQUIDATE_ALL
        assert result.action == RiskAction.LIQUIDATE_ALL
        assert "最大回撤" in result.reason


# ═══════════════════════════════════════════════════════════════
#  自定义阈值 + 边界
# ═══════════════════════════════════════════════════════════════


class TestCustomLimits:
    def test_custom_strict_limits(self):
        """更严的阈值 → 更容易触发

        数据设计:X:25_000 of 100_000 = 25% > 20% max_position_pct
        """
        limits = RiskLimits(max_drawdown=0.05, max_daily_loss=0.02, max_position_pct=0.20)
        result = check_risk(
            current_nav=100_000,
            positions={"X": 25_000},  # 25% > 20%
            day_start_nav=100_000,
            peak_nav=100_000,
            limits=limits,  # ← 必须传!否则用默认 30% 阈值
        )
        # 默认阈值 (30%) 下 ALLOW,自定义严格 (20%) 下 BLOCK_BUY
        assert result.action == RiskAction.BLOCK_BUY
        assert "仓位超标" in result.reason
        assert result.max_position_pct_actual == pytest.approx(0.25, abs=0.001)


class TestInvalidNav:
    def test_zero_nav_liquidates(self):
        """nav=0 → LIQUIDATE_ALL(避免除零 + 极端情况)"""
        result = check_risk(
            current_nav=0,
            positions={},
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.LIQUIDATE_ALL
        assert "无效净值" in result.reason

    def test_negative_nav_liquidates(self):
        """nav < 0 → LIQUIDATE_ALL"""
        result = check_risk(
            current_nav=-100,
            positions={},
            day_start_nav=100_000,
            peak_nav=100_000,
        )
        assert result.action == RiskAction.LIQUIDATE_ALL