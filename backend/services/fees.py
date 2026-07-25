"""A 股交易手续费计算 (T4)

费率 (A 股标准, 与 strategy_backtest_service 一致):
  佣金: 万分之三 (0.0003), 最低 5 元
  印花税: 千分之一 (0.001), 仅卖出
  过户费: 十万分之一 (0.00001)

公开 API:
  - calc_buy_fee(amount) -> dict
  - calc_sell_fee(amount) -> dict
  - calc_total_fee(buy_amount, sell_amount) -> dict
"""
from __future__ import annotations

COMMISSION_RATE = 0.0003
COMMISSION_MIN = 5.0
STAMP_TAX_RATE = 0.001
TRANSFER_FEE_RATE = 0.00001


def _round2(x: float) -> float:
    return round(x, 2)


def calc_buy_fee(amount: float) -> dict:
    """买入手续费 (无印花税).

    Args:
        amount: 成交金额 (price * shares)

    Returns:
        {commission, stamp_tax, transfer_fee, total}
    """
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    stamp = 0.0
    transfer = amount * TRANSFER_FEE_RATE
    return {
        "commission": _round2(commission),
        "stamp_tax": _round2(stamp),
        "transfer_fee": _round2(transfer),
        "total": _round2(commission + stamp + transfer),
    }


def calc_sell_fee(amount: float) -> dict:
    """卖出手续费 (含印花税)."""
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    stamp = amount * STAMP_TAX_RATE
    transfer = amount * TRANSFER_FEE_RATE
    return {
        "commission": _round2(commission),
        "stamp_tax": _round2(stamp),
        "transfer_fee": _round2(transfer),
        "total": _round2(commission + stamp + transfer),
    }


def calc_total_fee(buy_amount: float = 0.0, sell_amount: float = 0.0) -> dict:
    """买卖合计费用."""
    buy = calc_buy_fee(buy_amount) if buy_amount > 0 else {
        "commission": 0.0, "stamp_tax": 0.0, "transfer_fee": 0.0, "total": 0.0
    }
    sell = calc_sell_fee(sell_amount) if sell_amount > 0 else {
        "commission": 0.0, "stamp_tax": 0.0, "transfer_fee": 0.0, "total": 0.0
    }
    return {
        "commission": _round2(buy["commission"] + sell["commission"]),
        "stamp_tax": _round2(buy["stamp_tax"] + sell["stamp_tax"]),
        "transfer_fee": _round2(buy["transfer_fee"] + sell["transfer_fee"]),
        "total": _round2(buy["total"] + sell["total"]),
        "buy": buy,
        "sell": sell,
    }