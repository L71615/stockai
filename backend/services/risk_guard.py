"""独立风控守护 — 4 条规则的纯函数评估器

移植自 quant-trading-system (D:\some-oss\quant-trading-system)
的 execution/risk_guard.py,适配 StockAI:
  - 改 dataclass 风格 + 枚举 RiskAction
  - 纯函数 check_risk() 不持有状态(状态由调用方传入)
  - 与 discipline_service.py 互补:本模块是"实时风控硬拦截",
    discipline_service 是"用户纪律规则配置"。

核心原则 (引自 OSS):
  - 策略代码不能裁判自己 → 风控必须独立
  - 4 条规则按严重度递增:
    1. 单品种仓位 → BLOCK_BUY(只拒绝新单)
    2. 总仓位     → BLOCK_BUY
    3. 日亏损     → BLOCK_BUY(锁仓,只允许平)
    4. 最大回撤   → LIQUIDATE_ALL(最严重,全平)

用法:
    from services.risk_guard import check_risk, RiskAction, RiskLimits

    action, reason = check_risk(
        current_nav=95_000,
        positions={"600519": 25_000},
        day_start_nav=100_000,
        peak_nav=110_000,
        limits=RiskLimits(),
    )
    if action == RiskAction.LIQUIDATE_ALL:
        # 全部平仓
    elif action == RiskAction.BLOCK_BUY:
        # 只允许平仓,不允许新单
"""
import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class RiskAction(str, Enum):
    """风控动作 — 严重度递增"""
    ALLOW = "allow"               # 通过
    BLOCK_BUY = "block_buy"       # 锁仓(只允许平仓,不允许新单)
    LIQUIDATE_ALL = "liquidate"   # 全部平仓(最严重)


@dataclass
class RiskLimits:
    """风控阈值(默认 A 股散户保守值)"""
    max_daily_loss: float = 0.05         # 日亏损上限 5%
    max_drawdown: float = 0.20           # 最大回撤 20%
    max_position_pct: float = 0.30       # 单品种仓位 30%
    max_total_exposure: float = 0.80     # 总仓位 80%


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    action: RiskAction
    reason: str
    daily_loss_pct: float = 0.0
    drawdown_pct: float = 0.0
    total_exposure_pct: float = 0.0
    max_position_pct_actual: float = 0.0
    max_position_symbol: str = ""


def check_risk(
    *,
    current_nav: float,
    positions: dict[str, float],      # {symbol: market_value}
    day_start_nav: float,
    peak_nav: float,
    limits: Optional[RiskLimits] = None,
    today: Optional[date] = None,
) -> RiskCheckResult:
    """独立风控检查 — 纯函数

    Args:
        current_nav:    当前总净值(cash + position_value)
        positions:      {symbol: position_market_value}
        day_start_nav:  当日开盘净值(用于算日亏损)
        peak_nav:       历史最高净值(用于算回撤)
        limits:         风控阈值(默认保守值)
        today:          当前日期(可选,目前未用,留给日内切换逻辑)

    Returns:
        RiskCheckResult — action + reason + 各指标快照(便于审计/通知)
    """
    if limits is None:
        limits = RiskLimits()

    # 防御性:无效净值
    if current_nav <= 0:
        return RiskCheckResult(
            action=RiskAction.LIQUIDATE_ALL,
            reason=f"无效净值: {current_nav} (≤ 0)",
        )

    drawdown_pct = (current_nav - peak_nav) / peak_nav if peak_nav > 0 else 0.0
    daily_loss_pct = (
        (current_nav - day_start_nav) / day_start_nav if day_start_nav > 0 else 0.0
    )

    # ── 规则 1 (最严重): 最大回撤 → 全平 ──
    if abs(drawdown_pct) > limits.max_drawdown:
        return RiskCheckResult(
            action=RiskAction.LIQUIDATE_ALL,
            reason=f"最大回撤触发: {drawdown_pct*100:.1f}% > {limits.max_drawdown*100:.0f}%",
            drawdown_pct=round(drawdown_pct, 4),
        )

    # ── 规则 2: 日亏损上限 → 锁仓 ──
    if daily_loss_pct < -limits.max_daily_loss:
        return RiskCheckResult(
            action=RiskAction.BLOCK_BUY,
            reason=f"日亏损触发: {daily_loss_pct*100:.1f}% < -{limits.max_daily_loss*100:.0f}%",
            daily_loss_pct=round(daily_loss_pct, 4),
            drawdown_pct=round(drawdown_pct, 4),
        )

    # ── 规则 3: 单品种仓位 → 锁仓(标出超限品种) ──
    max_pos_pct = 0.0
    max_pos_sym = ""
    for sym, value in positions.items():
        pct = value / current_nav
        if pct > max_pos_pct:
            max_pos_pct = pct
            max_pos_sym = sym
        if pct > limits.max_position_pct:
            return RiskCheckResult(
                action=RiskAction.BLOCK_BUY,
                reason=f"{sym} 仓位超标: {pct*100:.1f}% > {limits.max_position_pct*100:.0f}%",
                max_position_pct_actual=round(pct, 4),
                max_position_symbol=sym,
                drawdown_pct=round(drawdown_pct, 4),
                daily_loss_pct=round(daily_loss_pct, 4),
            )

    # ── 规则 4: 总仓位 → 锁仓 ──
    total_exposure = sum(positions.values()) / current_nav
    if total_exposure > limits.max_total_exposure:
        return RiskCheckResult(
            action=RiskAction.BLOCK_BUY,
            reason=f"总仓位超标: {total_exposure*100:.1f}% > {limits.max_total_exposure*100:.0f}%",
            total_exposure_pct=round(total_exposure, 4),
            drawdown_pct=round(drawdown_pct, 4),
            daily_loss_pct=round(daily_loss_pct, 4),
        )

    return RiskCheckResult(
        action=RiskAction.ALLOW,
        reason="OK",
        drawdown_pct=round(drawdown_pct, 4),
        daily_loss_pct=round(daily_loss_pct, 4),
        total_exposure_pct=round(total_exposure, 4),
        max_position_pct_actual=round(max_pos_pct, 4),
        max_position_symbol=max_pos_sym,
    )