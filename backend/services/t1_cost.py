"""T+1 持仓成本计算器 — v4.0 C2

T+1/T+2 短线预测场景: 前晚收盘价买入, 次日开盘价卖出(规避 T+1 持仓成本)。
本模块计算 T+1 持仓期间的全部成本:
  1. 卖出手续费(佣金 + 印花税 + 过户费) — 复用 fees.calc_sell_fee()
  2. 持仓风险溢价(隔夜跳空 + 流动性折价) — 按 (entry × daily_risk_premium_bps × hold_days) 估算

公开 API:
  - calc_t1_holding_cost(entry_price, exit_price, shares, hold_days=1, daily_risk_premium_bps=5.0)
    → {sell_fee, holding_risk_premium, total_cost, gross_pnl, net_pnl, net_return_pct, ...}
  - calc_t1_net_return(entry_price, exit_price, shares, **kwargs)
    → 直接返回净收益率(%),便于多 Agent 决策时快速比较
"""

from __future__ import annotations

from services.fees import calc_sell_fee


# v4.0 持仓风险溢价默认参数(可被调用方覆盖)
DEFAULT_DAILY_RISK_PREMIUM_BPS = 5.0  # 5bps/天 ≈ 0.05%/天 的隔夜跳空 + 流动性折价


def calc_t1_holding_cost(
    entry_price: float,
    exit_price: float,
    shares: int = 100,
    hold_days: int = 1,
    daily_risk_premium_bps: float = DEFAULT_DAILY_RISK_PREMIUM_BPS,
    slippage_bps: float = 10.0,
) -> dict:
    """T+1 持仓成本计算

    Args:
        entry_price: 买入价(元/股)
        exit_price: 卖出价(元/股,次日开盘价或模拟成交价)
        shares: 持股数(默认 100,A 股最小单位)
        hold_days: 持仓天数(T+1 = 1,T+2 = 2)
        daily_risk_premium_bps: 每日持仓风险溢价(bps,默认 5bps = 0.05%/天)
                               含隔夜跳空风险 + 流动性折价
        slippage_bps: 滑点(bps,默认 10bps = 0.1%)— 对卖出价 ×(1 - slippage)

    Returns:
        {
            "entry_price": 原始买入价,
            "exit_price": 原始卖出价,
            "slipped_exit_price": 滑点后卖出价,
            "shares": 持股数,
            "hold_days": 持仓天数,
            "sell_fee": {commission, stamp_tax, transfer_fee, total},
            "holding_risk_premium": 持仓风险溢价金额,
            "total_cost": 总成本(卖出手续费 + 持仓风险溢价),
            "gross_pnl": 税前盈亏,
            "net_pnl": 净盈亏(扣费后),
            "gross_return_pct": 税前收益率(%),
            "net_return_pct": 净收益率(%,扣费后),
        }
    """
    if entry_price is None or entry_price <= 0:
        return {"error": "entry_price 必须为正数"}
    if exit_price is None or exit_price <= 0:
        return {"error": "exit_price 必须为正数"}
    if shares is None or shares <= 0:
        return {"error": "shares 必须为正数"}
    if hold_days is None or hold_days < 0:
        return {"error": "hold_days 必须为非负数"}

    # ── 1. 应用滑点到卖出价 ──
    slip_factor = slippage_bps / 10000.0
    slipped_exit_price = exit_price * (1 - slip_factor)

    # ── 2. 计算卖出手续费(基于滑点后价 × 股数) ──
    sell_amount = slipped_exit_price * shares
    sell_fee = calc_sell_fee(sell_amount)
    total_sell_fee = sell_fee["total"]

    # ── 3. 计算持仓风险溢价(基于买入价 × 天数) ──
    daily_risk_factor = daily_risk_premium_bps / 10000.0
    holding_risk_premium = round(entry_price * shares * daily_risk_factor * hold_days, 2)

    # ── 4. 汇总成本与盈亏 ──
    total_cost = round(total_sell_fee + holding_risk_premium, 2)
    entry_amount = entry_price * shares
    gross_pnl = round(slipped_exit_price * shares - entry_amount, 2)
    net_pnl = round(gross_pnl - total_sell_fee - holding_risk_premium, 2)

    gross_return_pct = round((slipped_exit_price - entry_price) / entry_price * 100, 4)
    net_return_pct = round(net_pnl / entry_amount * 100, 4)

    return {
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "slipped_exit_price": round(slipped_exit_price, 4),
        "shares": shares,
        "hold_days": hold_days,
        "sell_fee": sell_fee,
        "holding_risk_premium": holding_risk_premium,
        "total_cost": total_cost,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "gross_return_pct": gross_return_pct,
        "net_return_pct": net_return_pct,
    }


def calc_t1_net_return(
    entry_price: float,
    exit_price: float,
    shares: int = 100,
    **kwargs,
) -> float:
    """便捷函数:直接返回净收益率(%)

    Args:
        entry_price/exit_price/shares: 同 calc_t1_holding_cost
        **kwargs: 透传给 calc_t1_holding_cost(hold_days, daily_risk_premium_bps, slippage_bps)

    Returns:
        净收益率(%,扣手续费 + 持仓风险溢价后);出错返回 None
    """
    result = calc_t1_holding_cost(entry_price, exit_price, shares, **kwargs)
    if "error" in result:
        return None
    return result["net_return_pct"]


def format_t1_cost_report(cost: dict) -> str:
    """格式化 T+1 成本报告(中文)— 用于多 Agent verdict 卡片显示

    Args:
        cost: calc_t1_holding_cost() 返回的 dict

    Returns:
        单行可读文本,例: "T+1 净收益 -0.30%(扣费 0.10% + 持仓溢价 0.05%)"
    """
    if not cost or "error" in cost:
        return f"T+1 成本计算失败: {cost.get('error', 'unknown') if cost else 'None'}"

    net_pct = cost["net_return_pct"]
    sell_fee_pct = cost["sell_fee"]["total"] / (cost["entry_price"] * cost["shares"]) * 100
    hold_premium_pct = cost["holding_risk_premium"] / (cost["entry_price"] * cost["shares"]) * 100

    sign = "+" if net_pct >= 0 else ""
    return (
        f"T+1 净收益 {sign}{net_pct:.2f}%"
        f"(卖费 {sell_fee_pct:.2f}% + 持仓溢价 {hold_premium_pct:.2f}%)"
    )
