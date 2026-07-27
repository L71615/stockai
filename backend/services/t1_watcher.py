"""T+1/T+2 短线模拟成交 watcher — v4.0

状态机:
  pending_buy → bought → pending_sell → sold
                                ↑ (持仓期满)
                                ↓
                            cancelled (手动取消)

调用方:
  - t1_watcher.process_pending_buys() — 09:30 触发,扫所有 pending_buy → 模拟成交
  - t1_watcher.process_pending_sells() — 09:30 触发,扫所有 bought + 持仓期满 → 模拟卖出
  - t1_watcher.create_pending_order() — 22:00 pipeline 调用,创建 pending_buy
  - t1_watcher.approve_order() / cancel_order() — /pipeline 收件箱 UI 调用

模拟成交规则:
  - 买入: 次日 09:30 开盘价 × (1 + slippage_bps/10000) → 写 holdings + transactions
  - 卖出: 持仓期满后次日 09:30 开盘价 × (1 - slippage_bps/10000) → 写 transactions
  - 成本: 复用 fees.calc_buy_fee / calc_sell_fee + t1_cost.calc_t1_holding_cost

用法:
  from services.t1_watcher import (
      create_pending_order,
      process_pending_buys,
      process_pending_sells,
      get_user_orders,
  )
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from services.fees import calc_buy_fee, calc_sell_fee
from services.t1_cost import calc_t1_holding_cost
from services.vendor_router import route

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  状态机常量
# ═══════════════════════════════════════════════════════════════

STATUS_PENDING_BUY = "pending_buy"
STATUS_BOUGHT = "bought"
STATUS_PENDING_SELL = "pending_sell"
STATUS_SOLD = "sold"
STATUS_CANCELLED = "cancelled"

ALL_STATUSES = {
    STATUS_PENDING_BUY,
    STATUS_BOUGHT,
    STATUS_PENDING_SELL,
    STATUS_SOLD,
    STATUS_CANCELLED,
}


# ═══════════════════════════════════════════════════════════════
#  CRUD — 创建 / 查询 / 审批 / 取消
# ═══════════════════════════════════════════════════════════════

def create_pending_order(
    user_id: int,
    stock_code: str,
    stock_name: str = "",
    brief_id: int | None = None,
    shares: int = 100,
    planned_entry_price: float | None = None,
    planned_exit_price: float | None = None,
    hold_days: int = 1,
    slippage_bps: float = 10.0,
    entry_date: str | None = None,
    reason: str = "",
) -> dict:
    """创建一条 T+1 pending_buy 订单

    Args:
        entry_date: 计划买入日期(YYYY-MM-DD),默认明天
        其他参数: 见 schema

    Returns:
        {"id": 新订单 ID, "status": "pending_buy", ...}
    """
    from database import execute, query_one

    if entry_date is None:
        entry_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # exit_date = entry_date + hold_days
    exit_date = (
        datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=hold_days)
    ).strftime("%Y-%m-%d")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result = execute(
        """INSERT INTO t1_pending_orders
           (user_id, stock_code, stock_name, brief_id, shares,
            planned_entry_price, planned_exit_price, hold_days,
            status, slippage_bps, entry_date, exit_date, reason,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, stock_code, stock_name, brief_id, shares,
            planned_entry_price, planned_exit_price, hold_days,
            STATUS_PENDING_BUY, slippage_bps, entry_date, exit_date,
            reason, now, now,
        ),
    )
    order_id = result.get("lastrowid") if isinstance(result, dict) else None
    return {
        "id": order_id,
        "user_id": user_id,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "shares": shares,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "hold_days": hold_days,
        "status": STATUS_PENDING_BUY,
        "slippage_bps": slippage_bps,
    }


def get_user_orders(
    user_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """获取用户的 T+1 订单列表"""
    from database import query_all

    if status:
        sql = """SELECT * FROM t1_pending_orders
                WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?"""
        rows = query_all(sql, (user_id, status, limit))
    else:
        sql = """SELECT * FROM t1_pending_orders
                WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?"""
        rows = query_all(sql, (user_id, limit))
    return rows or []


def get_order_by_id(order_id: int, user_id: int | None = None) -> dict | None:
    """按 ID 查询订单(可选 user_id 校验)"""
    from database import query_one

    if user_id is not None:
        row = query_one(
            "SELECT * FROM t1_pending_orders WHERE id = ? AND user_id = ?",
            (order_id, user_id),
        )
    else:
        row = query_one("SELECT * FROM t1_pending_orders WHERE id = ?", (order_id,))
    return row


def cancel_order(order_id: int, user_id: int, reason: str = "用户取消") -> bool:
    """取消订单(只在 pending_buy 状态可取消)"""
    from database import execute

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute(
        """UPDATE t1_pending_orders
           SET status = ?, reason = ?, updated_at = ?
           WHERE id = ? AND user_id = ? AND status = ?""",
        (STATUS_CANCELLED, f"[{now}] {reason}", now,
         order_id, user_id, STATUS_PENDING_BUY),
    )
    return True


# ═══════════════════════════════════════════════════════════════
#  Watcher — 模拟买入 / 卖出
# ═══════════════════════════════════════════════════════════════

def _get_open_price(stock_code: str, date: str) -> float | None:
    """获取指定日期的开盘价(从 historical_kline)"""
    from database import query_one

    row = query_one(
        """SELECT open FROM historical_kline
           WHERE stock_code = ? AND trade_date = ?
           ORDER BY trade_date DESC LIMIT 1""",
        (stock_code, date),
    )
    if row and row.get("open") is not None:
        return float(row["open"])
    # Fallback: 调实时数据(如果当天还没收盘)
    try:
        quote = route("get_realtime_quote", code=stock_code)
        if isinstance(quote, dict) and "open" in quote and quote["open"] is not None:
            return float(quote["open"])
    except Exception:
        pass
    return None


def _apply_slippage(price: float, side: str, slippage_bps: float) -> float:
    """对成交价应用滑点

    Args:
        side: "buy" (× (1 + slippage)) 或 "sell" (× (1 - slippage))
    """
    if price is None or slippage_bps <= 0:
        return price
    factor = slippage_bps / 10000.0
    if side == "buy":
        return price * (1 + factor)
    else:  # sell
        return price * (1 - factor)


def _simulate_buy(order: dict, open_price: float) -> dict:
    """模拟买入 — 写 holdings + transactions + 更新订单状态

    Args:
        order: t1_pending_orders 记录
        open_price: 开盘价(已应用滑点)

    Returns:
        {"order_id", "filled_price", "filled_shares", "fee", "holdings_id"}
    """
    from database import execute, query_one

    order_id = order["id"]
    user_id = order["user_id"]
    stock_code = order["stock_code"]
    stock_name = order["stock_name"] or stock_code
    shares = int(order["shares"])

    # 买入手续费
    buy_amount = open_price * shares
    fee = calc_buy_fee(buy_amount)
    total_cost = buy_amount + fee["total"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. 写 transactions
    execute(
        """INSERT INTO transactions
           (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, stock_code, stock_name, "buy",
            round(open_price, 4), shares,
            round(total_cost, 2),
            round(fee["total"], 2),
            now,
            f"[T+1 模拟成交] brief_id={order.get('brief_id')}",
        ),
    )

    # 2. 更新或新增 holdings
    existing = query_one(
        "SELECT id, quantity, cost_price FROM holdings WHERE user_id = ? AND stock_code = ?",
        (user_id, stock_code),
    )
    if existing:
        old_qty = float(existing["quantity"])
        old_cost = float(existing["cost_price"])
        new_qty = old_qty + shares
        new_cost = (old_cost * old_qty + open_price * shares) / new_qty if new_qty > 0 else open_price
        execute(
            """UPDATE holdings
               SET quantity = ?, cost_price = ?, stock_name = ?, updated_at = ?
               WHERE id = ?""",
            (new_qty, round(new_cost, 4), stock_name, now, existing["id"]),
        )
    else:
        execute(
            """INSERT INTO holdings
               (user_id, stock_code, stock_name, asset_type, quantity, cost_price, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, stock_code, stock_name, "stock",
             shares, round(open_price, 4), now, now),
        )

    # 3. 更新订单状态
    execute(
        """UPDATE t1_pending_orders
           SET status = ?, executed_entry_price = ?, entry_fee = ?,
               actual_entry_at = ?, updated_at = ?
           WHERE id = ?""",
        (STATUS_BOUGHT, round(open_price, 4), round(fee["total"], 2),
         now, now, order_id),
    )

    return {
        "order_id": order_id,
        "filled_price": round(open_price, 4),
        "filled_shares": shares,
        "fee": round(fee["total"], 2),
        "total_cost": round(total_cost, 2),
        "entry_date": today,
    }


def _simulate_sell(order: dict, open_price: float) -> dict:
    """模拟卖出 — 写 transactions + 更新持仓 + 更新订单状态 + 收益统计

    Args:
        order: t1_pending_orders 记录(已 bought)
        open_price: 开盘价(已应用滑点)

    Returns:
        {"order_id", "filled_price", "filled_shares", "fee", "pnl", "net_return_pct"}
    """
    from database import execute, query_one

    order_id = order["id"]
    user_id = order["user_id"]
    stock_code = order["stock_code"]
    stock_name = order["stock_name"] or stock_code
    shares = int(order["shares"])
    entry_price = float(order.get("executed_entry_price") or order.get("planned_entry_price") or 0)
    slippage_bps = float(order.get("slippage_bps", 10.0))
    hold_days = int(order.get("hold_days", 1))

    if entry_price <= 0:
        return {"error": f"订单 {order_id} 缺少 entry_price"}

    # 1. 写 transactions
    sell_amount = open_price * shares
    fee = calc_sell_fee(sell_amount)
    net_proceeds = sell_amount - fee["total"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")

    execute(
        """INSERT INTO transactions
           (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, stock_code, stock_name, "sell",
            round(open_price, 4), shares,
            round(net_proceeds, 2),
            round(fee["total"], 2),
            now,
            f"[T+1 模拟卖出] order_id={order_id}",
        ),
    )

    # 2. 扣减 holdings
    existing = query_one(
        "SELECT id, quantity, cost_price FROM holdings WHERE user_id = ? AND stock_code = ?",
        (user_id, stock_code),
    )
    if existing:
        old_qty = float(existing["quantity"])
        new_qty = max(0, old_qty - shares)
        if new_qty == 0:
            execute("DELETE FROM holdings WHERE id = ?", (existing["id"],))
        else:
            execute(
                """UPDATE holdings
                   SET quantity = ?, updated_at = ?
                   WHERE id = ?""",
                (new_qty, now, existing["id"]),
            )

    # 3. 收益统计 — 复用 t1_cost
    t1 = calc_t1_holding_cost(
        entry_price=entry_price,
        exit_price=open_price,
        shares=shares,
        hold_days=hold_days,
        slippage_bps=0,  # 滑点已在 open_price 中应用
    )

    # 4. 更新订单状态
    execute(
        """UPDATE t1_pending_orders
           SET status = ?, executed_exit_price = ?, exit_fee = ?,
               holding_risk_premium = ?, gross_pnl = ?, net_pnl = ?, net_return_pct = ?,
               actual_exit_at = ?, updated_at = ?
           WHERE id = ?""",
        (STATUS_SOLD, round(open_price, 4), round(fee["total"], 2),
         t1.get("holding_risk_premium", 0), t1.get("gross_pnl", 0),
         t1.get("net_pnl", 0), t1.get("net_return_pct", 0),
         now, now, order_id),
    )

    return {
        "order_id": order_id,
        "filled_price": round(open_price, 4),
        "filled_shares": shares,
        "fee": round(fee["total"], 2),
        "gross_pnl": t1.get("gross_pnl"),
        "net_pnl": t1.get("net_pnl"),
        "net_return_pct": t1.get("net_return_pct"),
        "exit_date": today,
    }


# ═══════════════════════════════════════════════════════════════
#  Watcher 主函数 — 由 scheduler 触发
# ═══════════════════════════════════════════════════════════════

def process_pending_buys(today: str | None = None) -> list[dict]:
    """扫描所有 pending_buy 且 entry_date <= today,模拟买入

    Args:
        today: 今天日期(YYYY-MM-DD),默认今天

    Returns:
        处理结果列表 [{"order_id": ..., "filled": True/False, "reason": ...}, ...]
    """
    from database import query_all

    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    rows = query_all(
        """SELECT * FROM t1_pending_orders
           WHERE status = ? AND entry_date <= ?
           ORDER BY created_at ASC""",
        (STATUS_PENDING_BUY, today),
    )

    results: list[dict] = []
    for order in rows:
        order_id = order["id"]
        stock_code = order["stock_code"]
        slippage_bps = float(order.get("slippage_bps", 10.0))

        try:
            open_price = _get_open_price(stock_code, today)
            if open_price is None or open_price <= 0:
                results.append({"order_id": order_id, "filled": False, "reason": "无开盘价数据"})
                continue

            filled_price = _apply_slippage(open_price, "buy", slippage_bps)
            result = _simulate_buy(order, filled_price)
            result["filled"] = True
            results.append(result)
        except Exception as e:
            logger.warning("process_pending_buys: order %s failed: %s", order_id, e)
            results.append({"order_id": order_id, "filled": False, "reason": str(e)})

    return results


def process_pending_sells(today: str | None = None) -> list[dict]:
    """扫描所有 bought 且 exit_date <= today,模拟卖出

    实际语义:exit_date 是"持仓期满次日"。所以 exit_date == today 时卖出。
    """
    from database import query_all

    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    rows = query_all(
        """SELECT * FROM t1_pending_orders
           WHERE status = ? AND exit_date <= ?
           ORDER BY created_at ASC""",
        (STATUS_BOUGHT, today),
    )

    results: list[dict] = []
    for order in rows:
        order_id = order["id"]
        stock_code = order["stock_code"]
        slippage_bps = float(order.get("slippage_bps", 10.0))

        try:
            open_price = _get_open_price(stock_code, today)
            if open_price is None or open_price <= 0:
                results.append({"order_id": order_id, "filled": False, "reason": "无开盘价数据"})
                continue

            filled_price = _apply_slippage(open_price, "sell", slippage_bps)
            result = _simulate_sell(order, filled_price)
            result["filled"] = True
            results.append(result)
        except Exception as e:
            logger.warning("process_pending_sells: order %s failed: %s", order_id, e)
            results.append({"order_id": order_id, "filled": False, "reason": str(e)})

    return results


# ═══════════════════════════════════════════════════════════════
#  收益汇总
# ═══════════════════════════════════════════════════════════════

def summarize_user_pnl(user_id: int, days: int = 30) -> dict:
    """汇总用户最近 N 天的 T+1 模拟盈亏"""
    from database import query_all

    rows = query_all(
        """SELECT status, COUNT(*) as cnt,
                  COALESCE(SUM(net_pnl), 0) as total_pnl,
                  COALESCE(AVG(net_return_pct), 0) as avg_return_pct
           FROM t1_pending_orders
           WHERE user_id = ? AND created_at >= date('now', ?)
           GROUP BY status""",
        (user_id, f"-{days} days"),
    )

    summary = {
        "days": days,
        "by_status": {},
        "total_orders": 0,
        "sold_orders": 0,
        "total_pnl": 0.0,
        "avg_return_pct": 0.0,
    }
    for r in rows:
        summary["by_status"][r["status"]] = {
            "count": r["cnt"],
            "total_pnl": r["total_pnl"],
            "avg_return_pct": r["avg_return_pct"],
        }
        summary["total_orders"] += r["cnt"]
        if r["status"] == STATUS_SOLD:
            summary["sold_orders"] = r["cnt"]
            summary["total_pnl"] = r["total_pnl"]
            summary["avg_return_pct"] = r["avg_return_pct"]
    return summary
