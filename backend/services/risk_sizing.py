"""仓位管理 — 每次开仓该买多少?

设计移植自 quant-trading-system (D:\some-oss\quant-trading-system)
的 risk/sizing.py,适配 StockAI 的纯函数调用风格(无状态对象)。

四种模型:
  FixedFractionSizer — 固定比例 (最简单,StockAI 现有默认)
  KellySizer          — Kelly 公式 (理论最优,实践中打折扣)
  RiskParitySizer     — 风险平价 (每份头寸承担相同风险)
  VolTargetSizer      — 波动率目标 (动态调整维持目标波动率)

核心认知 (摘自 OSS):
  - 等权是基准,任何优化必须比等权好才有意义
  - 波动率倒数 = 让每份头寸贡献相同的波动,鲁棒性最好
  - Kelly 公式理论最优但波动大,half_kelly 是工业实践
  - Markowitz 容易过拟合:过去协方差 ≠ 未来协方差

用法:
    from services.risk_sizing import get_position_size, SizingMethod

    # 简单调用
    pct = get_position_size(
        method="kelly",
        win_rate=0.45,
        profit_factor=2.0,
    )

    # 或者基于波动率
    pct = get_position_size(
        method="vol_target",
        realized_vol=0.30,  # 30% 年化
    )
"""
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class SizingMethod(str, Enum):
    FIXED = "fixed"
    KELLY = "kelly"
    RISK_PARITY = "risk_parity"
    VOL_TARGET = "vol_target"


# ═══════════════════════════════════════════════════════════════
#  各仓位算法(纯函数)
# ═══════════════════════════════════════════════════════════════


def fixed_fraction_size(fraction: float = 0.1) -> float:
    """固定比例 — 每次用 X% 资金(StockAI 默认 10%)

    Args:
        fraction: 0~1 之间的比例

    Returns:
        仓位比例(0~1)
    """
    return max(0.0, min(fraction, 1.0))


def kelly_size(
    win_rate: float,
    profit_factor: float,
    half: bool = True,
    max_fraction: float = 0.25,
    min_fraction: float = 0.02,
) -> float:
    """Kelly 公式 — 理论最优下注比例

    f* = (p × b - (1-p)) / b
      p = 胜率
      b = 盈亏比 (盈利均值 / 亏损均值)

    Args:
        win_rate: 胜率 (0~1, 如 0.45)
        profit_factor: 盈亏比 (avg_win / avg_loss, 如 2.0)
        half: 是否用 half_kelly(标准做法,推荐 True)
        max_fraction: 上限(默认 25%,防 f* 过高)
        min_fraction: 下限(默认 2%,防 f* 为负或 0)

    Returns:
        仓位比例(0~1)
    """
    if win_rate <= 0 or profit_factor <= 0:
        return min_fraction
    try:
        # f* = (p*b - (1-p)) / b
        f_star = max(0.0, (win_rate * profit_factor - (1 - win_rate)) / profit_factor)
        if half:
            f_star /= 2.0
        return max(min_fraction, min(f_star, max_fraction))
    except Exception:
        logger.debug("kelly_size: 计算失败,返回 min_fraction", exc_info=True)
        return min_fraction


def risk_parity_size(target_risk: float, volatility: float, max_fraction: float = 0.5) -> float:
    """风险平价 — 让每个头寸贡献相同的波动

    高波动品种买少,低波动品种买多
    position_pct = target_risk / vol

    Args:
        target_risk: 每笔交易目标承担的年化波动(如 0.05 = 5%)
        volatility:  该品种的年化波动率
        max_fraction: 上限(默认 50%)

    Returns:
        仓位比例(0~1)
    """
    if volatility <= 0:
        return 0.1
    try:
        pct = target_risk / volatility
        return max(0.0, min(pct, max_fraction))
    except Exception:
        logger.debug("risk_parity_size: 计算失败,返回 0.1", exc_info=True)
        return 0.1


def vol_target_size(
    target_vol: float,
    realized_vol: float,
    max_leverage: float = 2.0,
    min_fraction: float = 0.02,
) -> float:
    """波动率目标 — 动态调整仓位维持目标波动

    最近波动大 → 自动减仓
    最近波动小 → 自动加仓
    position = target_vol / realized_vol

    Args:
        target_vol:   目标年化波动率 (如 0.15 = 15%)
        realized_vol: 实际年化波动率
        max_leverage: 最大杠杆倍数(默认 2x)
        min_fraction: 下限(默认 2%)

    Returns:
        仓位比例(0~1,可大于 1 表示加杠杆,默认 max=2x)
    """
    if realized_vol <= 0:
        return 0.2
    try:
        pct = target_vol / realized_vol
        return max(min_fraction, min(pct, max_leverage))
    except Exception:
        logger.debug("vol_target_size: 计算失败,返回 0.2", exc_info=True)
        return 0.2


# ═══════════════════════════════════════════════════════════════
#  统一入口
# ═══════════════════════════════════════════════════════════════


def get_position_size(
    method: str | SizingMethod = SizingMethod.FIXED,
    *,
    fraction: float = 0.1,
    win_rate: Optional[float] = None,
    profit_factor: Optional[float] = None,
    volatility: Optional[float] = None,
    target_risk: float = 0.05,
    target_vol: float = 0.15,
    realized_vol: Optional[float] = None,
    max_fraction: float = 0.5,
) -> dict:
    """统一仓位计算入口(返回 dict 便于审计/日志)

    Args:
        method: "fixed" | "kelly" | "risk_parity" | "vol_target"
        fraction: 固定比例(仅 fixed 用)
        win_rate / profit_factor: 仅 kelly 用
        volatility: 仅 risk_parity 用
        target_risk: 仅 risk_parity 用
        target_vol / realized_vol: 仅 vol_target 用
        max_fraction: 上限(risk_parity / vol_target 共用)

    Returns:
        {
            "method": "kelly",
            "position_pct": 0.125,         # 最终仓位(0~1)
            "params": {所有入参},            # 便于审计
            "diagnostic": "...",            # 人类可读说明
        }
    """
    method_str = method.value if isinstance(method, SizingMethod) else str(method).lower()

    if method_str == "fixed":
        pct = fixed_fraction_size(fraction)
        diagnostic = f"固定 {pct*100:.1f}% 资金"
        params = {"fraction": fraction}

    elif method_str == "kelly":
        if win_rate is None or profit_factor is None:
            raise ValueError("kelly 需要 win_rate + profit_factor")
        pct = kelly_size(win_rate, profit_factor)
        diagnostic = f"Kelly(WR={win_rate}, PF={profit_factor}) = {pct*100:.1f}%"
        params = {"win_rate": win_rate, "profit_factor": profit_factor}

    elif method_str == "risk_parity":
        if volatility is None:
            raise ValueError("risk_parity 需要 volatility")
        pct = risk_parity_size(target_risk, volatility, max_fraction)
        diagnostic = f"风险平价(target={target_risk*100:.1f}%, vol={volatility*100:.1f}%) = {pct*100:.1f}%"
        params = {"target_risk": target_risk, "volatility": volatility, "max_fraction": max_fraction}

    elif method_str == "vol_target":
        if realized_vol is None:
            raise ValueError("vol_target 需要 realized_vol")
        pct = vol_target_size(target_vol, realized_vol, max_fraction)
        diagnostic = f"波动目标(target={target_vol*100:.1f}%, realized={realized_vol*100:.1f}%) = {pct*100:.1f}%"
        params = {"target_vol": target_vol, "realized_vol": realized_vol, "max_fraction": max_fraction}

    else:
        raise ValueError(f"未知 method: {method_str},可选: fixed/kelly/risk_parity/vol_target")

    return {
        "method": method_str,
        "position_pct": round(pct, 4),
        "params": params,
        "diagnostic": diagnostic,
    }


# ═══════════════════════════════════════════════════════════════
#  历史交易 → 胜率/盈亏比 统计(用于 Kelly 输入)
# ═══════════════════════════════════════════════════════════════


def calc_win_rate_and_profit_factor(trades: list[dict]) -> dict:
    """从历史交易记录计算 Kelly 输入参数

    Args:
        trades: [{direction, pnl, ...}, ...]  只统计卖出且 pnl 不为空的

    Returns:
        {
            "num_trades": N,
            "win_rate": 0.45,         # 胜率
            "profit_factor": 2.0,     # 盈亏比 (avg_win / avg_loss)
            "avg_win": 100.0,
            "avg_loss": -50.0,
            "kelly_fraction": 0.10,   # 直接用 half_kelly
        }
    """
    sell_trades = [t for t in trades if t.get("direction") == "sell" and t.get("pnl") is not None]
    if not sell_trades:
        return {
            "num_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "kelly_fraction": 0.0,
        }

    wins = [t["pnl"] for t in sell_trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in sell_trades if t["pnl"] < 0]

    win_rate = len(wins) / len(sell_trades)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else (10.0 if avg_win > 0 else 0.0)

    # half_kelly
    if profit_factor > 0:
        f_star = max(0.0, (win_rate * profit_factor - (1 - win_rate)) / profit_factor)
        kelly_fraction = f_star / 2.0
    else:
        kelly_fraction = 0.0

    return {
        "num_trades": len(sell_trades),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "kelly_fraction": round(min(kelly_fraction, 0.25), 4),  # 上限 25%
    }