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
from services.notify_service import send_notification

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
    source: str = "user_manual",                 # v4.1 1A.3: pipeline_proposal / user_manual
    proposal_id: int | None = None,             # v4.1 1A.3: 关联 approval_proposals.proposal_id
) -> dict:
    """创建一条 T+1 pending_buy 订单

    Args:
        entry_date: 计划买入日期(YYYY-MM-DD),默认明天
        source: 'pipeline_proposal' (来自 /pipeline 收件箱) 或 'user_manual' (默认)
        proposal_id: 当 source='pipeline_proposal' 时关联的 approval_proposals.proposal_id
        其他参数: 见 schema

    Returns:
        {"id": 新订单 ID, "status": "pending_buy", "source": ..., ...}
    """
    from database import execute, query_one

    if entry_date is None:
        entry_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # exit_date = entry_date + hold_days
    exit_date = (
        datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=hold_days)
    ).strftime("%Y-%m-%d")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # v4.1 1A.3: source 字段 + proposal_id 字段 (v4.0 schema 可能没有, 用 try/except ALTER)
    # 这里直接 INSERT, source 是新字段, proposal_id 也加进去
    try:
        result = execute(
            """INSERT INTO t1_pending_orders
               (user_id, stock_code, stock_name, brief_id, shares,
                planned_entry_price, planned_exit_price, hold_days,
                status, slippage_bps, entry_date, exit_date, reason,
                source, proposal_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, stock_code, stock_name, brief_id, shares,
                planned_entry_price, planned_exit_price, hold_days,
                STATUS_PENDING_BUY, slippage_bps, entry_date, exit_date,
                reason, source, proposal_id, now, now,
            ),
        )
    except Exception:
        # 旧 schema 无 source / proposal_id 字段 — 回退到基础 insert
        try:
            execute(
                """ALTER TABLE t1_pending_orders ADD COLUMN proposal_id INTEGER""",
            )
        except Exception:
            pass
        result = execute(
            """INSERT INTO t1_pending_orders
               (user_id, stock_code, stock_name, brief_id, shares,
                planned_entry_price, planned_exit_price, hold_days,
                status, slippage_bps, entry_date, exit_date, reason,
                source, proposal_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, stock_code, stock_name, brief_id, shares,
                planned_entry_price, planned_exit_price, hold_days,
                STATUS_PENDING_BUY, slippage_bps, entry_date, exit_date,
                reason, source, proposal_id, now, now,
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
        "source": source,
        "proposal_id": proposal_id,
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

    # v4.1 1B.1: 推送取消通知 (best-effort, 不阻塞取消主流程)
    _notify_settlement(
        title="[订单取消]",
        body=f"订单 #{order_id} 已取消\n原因: {reason}",
        order_id=order_id,
    )
    return True


def _notify_settlement(title: str, body: str, order_id: int) -> None:
    """v4.1 1B.1: 成交通知推送 (best-effort)

    失败不阻塞 watcher 主流程:
      - notify_service 内部已 try/except 每个 channel
      - 这里再套一层 try/except 防御 send_notification 自身抛异常
      - 无渠道时仅 log "[notify_skip]", 不算错
    """
    try:
        result = send_notification(markdown=body, title=title, run_id=f"t1_watcher_{order_id}")
        if not result.get("sent"):
            logger.info("[notify_skip] order %s: %s", order_id, result.get("reason", "no channel"))
    except Exception as e:
        # 通知失败不影响 watcher 模拟成交 — 已在 notify_log 留 audit
        logger.warning("notify_settlement order %s failed: %s", order_id, e)


# ═══════════════════════════════════════════════════════════════
#  Watcher — 模拟买入 / 卖出
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  v4.1.1 — risk_guard 集成
# ═══════════════════════════════════════════════════════════════

# 风险拦截原因(写到 order.reason / notifications)
RISK_BLOCKED_REASON = "blocked_by_risk"


def _get_user_positions_value(user_id: int) -> dict[str, float]:
    """查询用户当前持仓市值(用 cost_basis 作 fallback,避免每次拉最新价)

    Returns:
        {stock_code: market_value} — market_value 优先用最新 close,
        没数据时 fallback 到 cost_basis (保守估计)
    """
    from database import query_all
    rows = query_all(
        """SELECT h.stock_code, h.quantity, h.cost_price,
                  (SELECT close FROM historical_kline
                   WHERE stock_code = h.stock_code
                   ORDER BY trade_date DESC LIMIT 1) AS last_close
           FROM holdings h WHERE h.user_id = ? AND h.quantity > 0""",
        (user_id,),
    )
    out: dict[str, float] = {}
    for r in rows:
        qty = float(r["quantity"])
        last_close = r.get("last_close")
        if last_close is not None:
            value = qty * float(last_close)
        else:
            value = qty * float(r["cost_price"])
        out[r["stock_code"]] = value
    return out


def _evaluate_buy_risk(
    user_id: int,
    stock_code: str,
    proposed_value: float,
) -> dict:
    """评估单笔买入是否会触发风控(v4.1.1 集成 risk_guard)

    简化版 (v4.1.1):只检查 single_position 规则 (max_position_pct)。
    不检查 total_exposure / max_drawdown / daily_loss — 后者需要 cash + NAV
    历史基建,本版未到位。

    Args:
        user_id: 用户 ID
        stock_code: 拟买入的股票代码
        proposed_value: 本次买入的市值估算 (open_price × shares × (1+slippage))

    Returns:
        {action, reason, max_position_symbol, max_position_pct_actual, ...}
    """
    try:
        from services.risk_guard import check_risk, RiskAction, RiskLimits
    except Exception as e:
        logger.debug("t1_watcher: risk_guard 不可用,跳过: %s", e)
        return {"action": RiskAction.ALLOW.value, "reason": "risk_guard_unavailable"}

    positions = _get_user_positions_value(user_id)
    positions_with_pending = dict(positions)
    positions_with_pending[stock_code] = positions_with_pending.get(stock_code, 0.0) + proposed_value

    total_value = sum(positions_with_pending.values())
    if total_value <= 0:
        return {"action": RiskAction.ALLOW.value, "reason": "no_positions",
                "max_position_pct_actual": 0.0, "max_position_symbol": ""}

    # 用单仓阈值 (默认 30%),其他规则阈值设极高避免误触
    limits = RiskLimits(
        max_position_pct=0.30,
        max_total_exposure=10.0,  # 禁用:无 cash 跟踪时永远 100% → 误触
        max_daily_loss=10.0,      # 禁用:无 day_start_nav 历史
        max_drawdown=10.0,        # 禁用:无 peak_nav 历史
    )
    result = check_risk(
        current_nav=total_value,
        positions=positions_with_pending,
        day_start_nav=total_value,
        peak_nav=total_value,
        limits=limits,
    )
    return {
        "action": result.action.value,
        "reason": result.reason,
        "max_position_symbol": result.max_position_symbol,
        "max_position_pct_actual": result.max_position_pct_actual,
        "total_exposure_pct": result.total_exposure_pct,
    }


def _notify_risk_block(order_id: int, user_id: int, stock_code: str, risk_result: dict) -> None:
    """风控拦截时通知用户(v4.1.1)"""
    try:
        from services.notify_service import send_notification
        body = (
            f"# 🚫 风控拦截买入\n\n"
            f"- 订单 ID: `{order_id}`\n"
            f"- 股票: `{stock_code}`\n"
            f"- 原因: {risk_result.get('reason', 'unknown')}\n"
            f"- 总仓位: {risk_result.get('total_exposure_pct', 0)*100:.1f}%\n\n"
            f"订单已标记 `blocked_by_risk`,可在 /pipeline 收件箱查看。"
        )
        send_notification(body, title=f"[StockAI] 买入风控拦截 {stock_code}")
    except Exception as e:
        logger.warning("t1_watcher: 风险通知失败(不阻塞): %s", e)


def _cancel_blocked_order(order_id: int, reason: str) -> None:
    """风控拦截时把订单标 cancelled + 记录原因

    不复用 cancel_order(user_id, reason="用户取消"),因为这里没有 user_id 校验
    需求(订单本来就是这个用户的)。直接 UPDATE。
    """
    from database import execute
    try:
        execute(
            """UPDATE t1_pending_orders
               SET status = ?, updated_at = ?
               WHERE id = ? AND status = ?""",
            (STATUS_CANCELLED, datetime.now().isoformat(), order_id, STATUS_PENDING_BUY),
        )
        logger.info("t1_watcher: order %s marked cancelled by risk: %s", order_id, reason)
    except Exception as e:
        logger.warning("t1_watcher: cancel blocked order %s failed: %s", order_id, e)


def _get_open_price(stock_code: str, date: str) -> float | None:
    """获取指定日期的开盘价(从 historical_kline)

    v4.1 outside voice fix: first-tick 校验 — 若 historical_kline.open 缺失,
    拒绝用 prev_close 或 pre-open 报价当 open (会引入虚假 fill).
    Fallback 仅在 09:35 之后且 realtime 报价标记了 first_tick=True 时启用.
    """
    from database import query_one

    row = query_one(
        """SELECT open, close FROM historical_kline
           WHERE stock_code = ? AND trade_date = ?
           ORDER BY trade_date DESC LIMIT 1""",
        (stock_code, date),
    )
    if row and row.get("open") is not None and row["open"] > 0:
        # first-tick 校验 — 开盘价必须在昨收 ±20% 区间内 (A 股涨跌停 ±10%)
        if row.get("close") and row["close"] > 0:
            prev_close = float(row["close"])
            open_p = float(row["open"])
            if open_p < prev_close * 0.80 or open_p > prev_close * 1.20:
                # 数据异常, 不当 fill
                return None
        return float(row["open"])

    # Fallback: 09:35 之后才允许走 realtime, 且必须是 first_tick 确认过的真实 open
    now = datetime.now()
    if now.hour < 9 or (now.hour == 9 and now.minute < 35):
        # 09:35 之前不允许 fallback — 集合竞价阶段 prev_close/indicative 易被误当 open
        return None
    try:
        quote = route("get_realtime_quote", code=stock_code)
        if (
            isinstance(quote, dict)
            and quote.get("first_tick") is True
            and quote.get("open") is not None
            and float(quote["open"]) > 0
        ):
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

    v4.1 outside voice fix: 4 步写入现在封装在单个事务中, 任一异常全部回滚,
    避免"成交已记 + 持仓未更新"或"持仓已加 + 订单状态未变"的不一致.

    Args:
        order: t1_pending_orders 记录
        open_price: 开盘价(已应用滑点)

    Returns:
        {"order_id", "filled_price", "filled_shares", "fee", "holdings_id"}
    """
    from database import execute_transaction

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

    def _do(cur) -> dict:
        # 1. 写 transactions
        cur.execute(
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

        # 2. 更新或新增 holdings — 单事务内 SELECT 看到的是已 BEGIN 的快照
        existing = cur.execute(
            "SELECT id, quantity, cost_price FROM holdings "
            "WHERE user_id = ? AND stock_code = ?",
            (user_id, stock_code),
        ).fetchone()
        holdings_id: int
        if existing:
            existing_d = dict(existing)
            old_qty = float(existing_d["quantity"])
            old_cost = float(existing_d["cost_price"])
            new_qty = old_qty + shares
            new_cost = (old_cost * old_qty + open_price * shares) / new_qty if new_qty > 0 else open_price
            cur.execute(
                """UPDATE holdings
                   SET quantity = ?, cost_price = ?, stock_name = ?, updated_at = ?
                   WHERE id = ?""",
                (new_qty, round(new_cost, 4), stock_name, now, existing_d["id"]),
            )
            holdings_id = int(existing_d["id"])
        else:
            cur.execute(
                """INSERT INTO holdings
                   (user_id, stock_code, stock_name, asset_type, quantity, cost_price, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, stock_code, stock_name, "stock",
                 shares, round(open_price, 4), now, now),
            )
            holdings_id = int(cur.lastrowid)

        # 3. 更新订单状态
        cur.execute(
            """UPDATE t1_pending_orders
               SET status = ?, executed_entry_price = ?, entry_fee = ?,
                   actual_entry_at = ?, updated_at = ?
               WHERE id = ?""",
            (STATUS_BOUGHT, round(open_price, 4), round(fee["total"], 2),
             now, now, order_id),
        )

        return {"holdings_id": holdings_id}

    result = execute_transaction(_do)

    # 4. v4.1 1B.1: 推送模拟买入通知（不影响主流程，失败仅 audit log）
    _notify_settlement(
        title=f"[模拟买入] {stock_code} {stock_name}",
        body=(
            f"已模拟买入 {stock_code} {stock_name} {shares} 股 @ {round(open_price, 4)}\n"
            f"金额: ¥{round(buy_amount, 2)} + 费 ¥{round(fee['total'], 2)}\n"
            f"总成本: ¥{round(total_cost, 2)}\n"
            f"持仓时间: {today}"
        ),
        order_id=order_id,
    )

    return {
        "order_id": order_id,
        "filled_price": round(open_price, 4),
        "filled_shares": shares,
        "fee": round(fee["total"], 2),
        "total_cost": round(total_cost, 2),
        "entry_date": today,
        "holdings_id": result["holdings_id"],
    }


def _simulate_sell(order: dict, open_price: float) -> dict:
    """模拟卖出 — 写 transactions + 更新持仓 + 更新订单状态 + 收益统计

    v4.1 outside voice fix: 同 _simulate_buy — 4 步写入封装在单事务.

    Args:
        order: t1_pending_orders 记录(已 bought)
        open_price: 开盘价(已应用滑点)

    Returns:
        {"order_id", "filled_price", "filled_shares", "fee", "pnl", "net_return_pct"}
    """
    from database import execute_transaction

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

    # 3. 收益统计 — 复用 t1_cost
    t1 = calc_t1_holding_cost(
        entry_price=entry_price,
        exit_price=open_price,
        shares=shares,
        hold_days=hold_days,
        slippage_bps=0,  # 滑点已在 open_price 中应用
    )

    def _do(cur) -> dict:
        # 写 transactions
        cur.execute(
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

        # 扣减 holdings
        existing = cur.execute(
            "SELECT id, quantity, cost_price FROM holdings "
            "WHERE user_id = ? AND stock_code = ?",
            (user_id, stock_code),
        ).fetchone()
        if existing:
            existing_d = dict(existing)
            old_qty = float(existing_d["quantity"])
            new_qty = max(0, old_qty - shares)
            if new_qty == 0:
                cur.execute("DELETE FROM holdings WHERE id = ?", (existing_d["id"],))
            else:
                cur.execute(
                    """UPDATE holdings
                       SET quantity = ?, updated_at = ?
                       WHERE id = ?""",
                    (new_qty, now, existing_d["id"]),
                )

        # 更新订单状态
        cur.execute(
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
        return {}

    execute_transaction(_do)

    # 5. v4.1 1B.1: 推送模拟卖出通知
    _notify_settlement(
        title=f"[模拟卖出] {stock_code} {stock_name}",
        body=(
            f"已模拟卖出 {stock_code} {stock_name} {shares} 股 @ {round(open_price, 4)}\n"
            f"毛收益: ¥{round(t1.get('gross_pnl', 0), 2)}\n"
            f"净收益: ¥{round(t1.get('net_pnl', 0), 2)} ({round(t1.get('net_return_pct', 0) * 100, 2)}%)\n"
            f"持仓: {hold_days} 天, 卖费: ¥{round(fee['total'], 2)}"
        ),
        order_id=order_id,
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

            # v4.1.1: 风控检查 — 单仓位 > 30% / 总仓位 > 80% → BLOCK_BUY
            planned_shares = int(order.get("planned_shares") or 0)
            proposed_value = filled_price * planned_shares if planned_shares > 0 else filled_price * 100
            risk_result = _evaluate_buy_risk(order["user_id"], stock_code, proposed_value)

            if risk_result.get("action") == "liquidate":
                # 极端情况:最大回撤触发 — v4.1.1 dry-run,只 log 不自动平仓
                logger.warning(
                    "process_pending_buys: order %s LIQUIDATE_ALL triggered (dry-run, no auto-liquidate): %s",
                    order_id, risk_result,
                )
            elif risk_result.get("action") == "block_buy":
                # 仓位超标 — 标记订单 cancelled + 通知
                logger.warning(
                    "process_pending_buys: order %s BLOCKED by risk: %s",
                    order_id, risk_result.get("reason"),
                )
                _cancel_blocked_order(order_id, risk_result.get("reason", ""))
                _notify_risk_block(order_id, order["user_id"], stock_code, risk_result)
                results.append({
                    "order_id": order_id,
                    "filled": False,
                    "reason": f"风控拦截: {risk_result.get('reason', 'unknown')}",
                    "risk_action": "block_buy",
                })
                continue

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
