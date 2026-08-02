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
#  状态机常量 — v4.2 M1 N 态(6 态,OSS OMS 风格)
# ═══════════════════════════════════════════════════════════════

STATUS_OPEN           = "open"            # 未成交(含买入/卖出挂单)
STATUS_PARTIAL_FILLED = "partial_filled"  # 部分成交
STATUS_FILLED         = "filled"          # 已成交(持仓中,未卖出)
STATUS_CLOSED         = "closed"          # 已卖出结算完成
STATUS_CANCELLED      = "cancelled"       # 用户取消
STATUS_REJECTED       = "rejected"        # broker / 系统拒绝

ALL_STATUSES = {
    STATUS_OPEN, STATUS_PARTIAL_FILLED, STATUS_FILLED,
    STATUS_CLOSED, STATUS_CANCELLED, STATUS_REJECTED,
}

# 老记录状态字面量 → 新名字映射(老记录保留,新代码不再使用)
LEGACY_STATUS_MAP: dict[str, str] = {
    "pending_buy":  STATUS_OPEN,
    "pending_sell": STATUS_OPEN,
    "bought":       STATUS_FILLED,
    "sold":         STATUS_CLOSED,
}

# 兼容集合:查询层用,把所有等价字面量合并
_LEGACY_OPEN_SET   = {STATUS_OPEN, "pending_buy", "pending_sell"}
_LEGACY_FILLED_SET = {STATUS_FILLED, "bought"}
_LEGACY_CLOSED_SET = {STATUS_CLOSED, "sold"}
_LEGACY_NOT_TERMINAL_SET = _LEGACY_OPEN_SET | _LEGACY_FILLED_SET

# v4.2 M1: 老字面量 alias(让现有 from-import 不破坏, 标记 deprecated)
# 现有测试 / 调用方仍可引用这些常量,但应该迁移到新名字
STATUS_PENDING_BUY  = "pending_buy"   # deprecated: 用 STATUS_OPEN
STATUS_BOUGHT       = "bought"        # deprecated: 用 STATUS_FILLED
STATUS_PENDING_SELL = "pending_sell"  # deprecated: 用 STATUS_OPEN
STATUS_SOLD         = "sold"          # deprecated: 用 STATUS_CLOSED
# STATUS_CANCELLED 不变(终态语义保持)

# 状态转换白名单(from → {to})
# closed / cancelled / rejected 均为终态,不能转出
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATUS_OPEN: {
        STATUS_PARTIAL_FILLED, STATUS_FILLED,
        STATUS_CANCELLED, STATUS_REJECTED,
    },
    STATUS_PARTIAL_FILLED: {
        STATUS_FILLED, STATUS_OPEN,                  # 撤单重挂 → open
        STATUS_CANCELLED, STATUS_REJECTED,
    },
    STATUS_FILLED: {
        STATUS_CLOSED, STATUS_CANCELLED,              # 极端平仓场景
    },
    STATUS_CLOSED:    set(),
    STATUS_CANCELLED: set(),
    STATUS_REJECTED:  set(),
}


def _expand_legacy_status(status: str) -> list[str]:
    """把新状态字面量展开为 [新, 老...] 同义集合(查询层兼容用)

    - "open"     → ["open", "pending_buy", "pending_sell"]
    - "filled"   → ["filled", "bought"]
    - "closed"   → ["closed", "sold"]
    - "partial_filled" / "cancelled" / "rejected" → [自身]
    """
    if status == STATUS_OPEN:
        return ["open", "pending_buy", "pending_sell"]
    if status == STATUS_FILLED:
        return ["filled", "bought"]
    if status == STATUS_CLOSED:
        return ["closed", "sold"]
    return [status]


def _legacy_status_to_new(status: str) -> str:
    """把任意字面量(新或老)归一化为新名字 — 用于聚合 / 标签"""
    return LEGACY_STATUS_MAP.get(status, status)


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
        {"id": 新订单 ID, "status": "open", "source": ..., ...}
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
    # v4.2 M1: status 默认值改为 STATUS_OPEN (新状态字面量)
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
                STATUS_OPEN, slippage_bps, entry_date, exit_date,
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
        "status": STATUS_OPEN,
        "slippage_bps": slippage_bps,
        "source": source,
        "proposal_id": proposal_id,
    }


def get_user_orders(
    user_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """获取用户的 T+1 订单列表(v4.2 M1: 双谓词兼容老字面量)

    若 status 是新字面量(open/filled/closed/cancelled),自动展开同义老字面量
    (pending_buy/pending_sell/bought/sold)以保持兼容。
    """
    from database import query_all

    if status:
        # 展开同义字面量 — 老记录保留,新代码按新名字查
        expanded = _expand_legacy_status(status)
        if len(expanded) == 1:
            sql = """SELECT * FROM t1_pending_orders
                    WHERE user_id = ? AND status = ?
                    ORDER BY created_at DESC LIMIT ?"""
            rows = query_all(sql, (user_id, expanded[0], limit))
        else:
            placeholders = ",".join("?" for _ in expanded)
            sql = f"""SELECT * FROM t1_pending_orders
                    WHERE user_id = ? AND status IN ({placeholders})
                    ORDER BY created_at DESC LIMIT ?"""
            rows = query_all(sql, (user_id, *expanded, limit))
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


# ═══════════════════════════════════════════════════════════════
#  v4.2 M1 — transition() 守卫 + 事件溯源
# ═══════════════════════════════════════════════════════════════

def _transition_inner(
    cur,
    *,
    order_id: int,
    target: str,
    actor: str,
    event_type: str,
    reason: str,
    filled_shares: int | None,
    pending_shares: int | None,
    metadata: dict | None,
    expected_status: str | None,
) -> dict:
    """transition 的内部实现 — 在 caller 提供的事务内执行

    步骤:
      1. 读 order 当前 status (CAS 校验)
      2. 校验 from→to 白名单
      3. UPDATE t1_pending_orders SET status, ...
      4. INSERT t1_order_events(append-only audit)
      5. 返回最新 order

    Raises:
        ValueError: order 不存在 / from→to 非法 / CAS 失败 / target 不在 ALL_STATUSES
    """
    import json as _json

    if target not in ALL_STATUSES:
        raise ValueError(f"transition: target '{target}' 不在 ALL_STATUSES 中")

    # 1. 读 order
    cur.execute(
        "SELECT id, status, filled_shares, pending_shares FROM t1_pending_orders WHERE id = ?",
        (order_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"transition: order {order_id} 不存在")

    current = dict(row)
    current_status = current.get("status")
    if current_status not in ALL_STATUSES:
        # 老字面量 → 视为等价的新名字(白名单查询用)
        normalized_from = LEGACY_STATUS_MAP.get(current_status, current_status)
    else:
        normalized_from = current_status

    # CAS 校验
    if expected_status is not None:
        if current_status != expected_status and normalized_from != expected_status:
            raise ValueError(
                f"transition: CAS 失败 order {order_id}: 当前 {current_status!r},"
                f" 期望 {expected_status!r}"
            )

    # 2. 白名单校验(用 normalized_from,允许老记录转新状态)
    allowed = _ALLOWED_TRANSITIONS.get(normalized_from, set())
    if target not in allowed:
        raise ValueError(
            f"transition: 非法状态转换 order {order_id}:"
            f" {current_status!r} → {target!r} 不在白名单"
        )

    # 3. UPDATE order
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates = ["status = ?", "updated_at = ?"]
    params: list = [target, now]

    if filled_shares is not None:
        updates.append("filled_shares = ?")
        params.append(int(filled_shares))
    if pending_shares is not None:
        updates.append("pending_shares = ?")
        params.append(int(pending_shares))
    if reason:
        updates.append("reason = ?")
        params.append(f"[{now}] {reason}")

    params.append(order_id)
    cur.execute(
        f"UPDATE t1_pending_orders SET {', '.join(updates)} WHERE id = ?",
        params,
    )

    # 4. INSERT audit event(原样记录 from_status, 老字面量可追溯)
    metadata_json = _json.dumps(metadata or {}, default=str, ensure_ascii=False)
    cur.execute(
        """INSERT INTO t1_order_events
           (order_id, actor, event_type, from_status, to_status,
            filled_shares, pending_shares, reason, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            order_id, actor, event_type,
            current_status, target,
            filled_shares, pending_shares,
            reason, metadata_json,
        ),
    )

    # 返回最新 order
    cur.execute("SELECT * FROM t1_pending_orders WHERE id = ?", (order_id,))
    updated = dict(cur.fetchone())
    updated["_last_event_id"] = cur.lastrowid
    return updated


def transition(
    *,
    order_id: int,
    target: str,
    actor: str = "system",
    event_type: str = "transition",
    reason: str = "",
    filled_shares: int | None = None,
    pending_shares: int | None = None,
    metadata: dict | None = None,
    expected_status: str | None = None,
    cur=None,
) -> dict:
    """统一状态转换入口(v4.2 M1)

    全部订单状态变更必须走此函数,确保:
      1. from→to 在白名单 (非法转换抛 ValueError)
      2. CAS 校验 current_status (防并发覆盖)
      3. 写 t1_order_events 审计行

    Args:
        order_id: t1_pending_orders.id
        target: 目标状态(必须在 ALL_STATUSES)
        actor: 谁触发,格式 'user:1' / 'scheduler' / 'risk_guard' /
               'realtime_signal' / 'bulk_approve'
        event_type: 'transition' / 'risk_blocked' / 'cancel' / 'expired'
        reason: 备注
        filled_shares / pending_shares: partial_filled 专用
        metadata: 附加 dict, 序列化为 metadata_json(risk_blocked 时存 risk_result)
        expected_status: CAS 校验当前状态
        cur: 可选 — 若提供,在 caller 事务内复用 cursor

    Returns:
        最新 order dict(含 _last_event_id)

    Raises:
        ValueError: 见 _transition_inner
    """
    from database import execute_transaction

    if cur is None:
        # 单独事务(用于 cancel_order 等单步场景)
        def _do(c) -> dict:
            return _transition_inner(
                c,
                order_id=order_id,
                target=target,
                actor=actor,
                event_type=event_type,
                reason=reason,
                filled_shares=filled_shares,
                pending_shares=pending_shares,
                metadata=metadata,
                expected_status=expected_status,
            )
        return execute_transaction(_do)
    return _transition_inner(
        cur,
        order_id=order_id,
        target=target,
        actor=actor,
        event_type=event_type,
        reason=reason,
        filled_shares=filled_shares,
        pending_shares=pending_shares,
        metadata=metadata,
        expected_status=expected_status,
    )


def cancel_order(order_id: int, user_id: int, reason: str = "用户取消") -> bool:
    """取消订单(v4.2 M1 N 态版) — 走 transition() 写审计

    open / partial_filled 状态可取消。filled(持仓中)取消等价于强制平仓,
    由 _simulate_sell 的 closed 路径处理,不通过本函数。
    """
    from database import query_one

    order = query_one(
        "SELECT id, status FROM t1_pending_orders WHERE id = ? AND user_id = ?",
        (order_id, user_id),
    )
    if order is None:
        return False

    current_status = order["status"]
    # 老字面量也算可取消
    normalized = LEGACY_STATUS_MAP.get(current_status, current_status)
    if normalized not in (STATUS_OPEN, STATUS_PARTIAL_FILLED):
        return False

    transition(
        order_id=order_id,
        target=STATUS_CANCELLED,
        actor=f"user:{user_id}",
        event_type="cancel",
        reason=reason,
        expected_status=current_status,
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


def _cancel_blocked_order(order_id: int, reason: str, risk_result: dict | None = None) -> None:
    """风控拦截时把订单标 cancelled + 写审计(v4.2 M1)

    不复用 cancel_order(user_id, reason="用户取消"),因为这里没有 user_id 校验
    需求(订单本来就是这个用户的)。走 transition() 写 audit event_type='risk_blocked'。
    """
    try:
        transition(
            order_id=order_id,
            target=STATUS_CANCELLED,
            actor="risk_guard",
            event_type="risk_blocked",
            reason=reason,
            metadata=risk_result,
        )
        logger.info("t1_watcher: order %s marked cancelled by risk: %s", order_id, reason)
    except ValueError as e:
        # 订单已被并发取消/已 filled 等,记录 warning 不阻塞主流程
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

        # 3. 更新订单状态 — v4.2 M1: 走 transition() 写审计 (cur 同事务)
        transition(
            order_id=order_id,
            target=STATUS_FILLED,
            actor="scheduler",
            event_type="filled",
            reason=f"模拟买入成交 @ {round(open_price, 4)}",
            expected_status=None,  # 不强制 CAS — 单 ticker 串行, 简化
            cur=cur,
        )

        # 同步更新价格/费用字段(transition 不覆盖这些)
        cur.execute(
            """UPDATE t1_pending_orders
               SET executed_entry_price = ?, entry_fee = ?, actual_entry_at = ?
               WHERE id = ?""",
            (round(open_price, 4), round(fee["total"], 2), now, order_id),
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

        # 更新订单状态 — v4.2 M1: 走 transition() 写审计
        transition(
            order_id=order_id,
            target=STATUS_CLOSED,
            actor="scheduler",
            event_type="closed",
            reason=f"模拟卖出成交 @ {round(open_price, 4)},"
                   f" 净收益 {round(t1.get('net_pnl', 0), 2)}",
            cur=cur,
        )
        # 同步更新价格/费用/PnL 字段(transition 不覆盖这些)
        cur.execute(
            """UPDATE t1_pending_orders
               SET executed_exit_price = ?, exit_fee = ?,
                   holding_risk_premium = ?, gross_pnl = ?, net_pnl = ?, net_return_pct = ?,
                   actual_exit_at = ?
               WHERE id = ?""",
            (round(open_price, 4), round(fee["total"], 2),
             t1.get("holding_risk_premium", 0), t1.get("gross_pnl", 0),
             t1.get("net_pnl", 0), t1.get("net_return_pct", 0),
             now, order_id),
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
    """扫描所有 open(含 pending_buy / pending_sell 老字面量)且 entry_date <= today,模拟买入

    Args:
        today: 今天日期(YYYY-MM-DD),默认今天

    Returns:
        处理结果列表 [{"order_id": ..., "filled": True/False, "reason": ...}, ...]
    """
    from database import query_all

    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    # v4.2 M1: 双谓词 — 同时查新字面量 'open' 和老字面量 'pending_buy' / 'pending_sell'
    rows = query_all(
        """SELECT * FROM t1_pending_orders
           WHERE status IN ('open', 'pending_buy', 'pending_sell')
             AND entry_date <= ?
           ORDER BY created_at ASC""",
        (today,),
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
                # 仓位超标 — 标记订单 cancelled + 通知(v4.2 M1: 走 transition 写 audit)
                logger.warning(
                    "process_pending_buys: order %s BLOCKED by risk: %s",
                    order_id, risk_result.get("reason"),
                )
                _cancel_blocked_order(order_id, risk_result.get("reason", ""), risk_result)
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
    """扫描所有 filled(含 bought 老字面量)且 exit_date <= today,模拟卖出

    实际语义:exit_date 是"持仓期满次日"。所以 exit_date == today 时卖出。
    """
    from database import query_all

    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    # v4.2 M1: 双谓词 — filled + 老字面量 bought
    rows = query_all(
        """SELECT * FROM t1_pending_orders
           WHERE status IN ('filled', 'bought') AND exit_date <= ?
           ORDER BY created_at ASC""",
        (today,),
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
    """汇总用户最近 N 天的 T+1 模拟盈亏(v4.2 M1: by_status 用新名字聚合)

    老字面量 pending_buy/pending_sell/bought/sold 自动归一化为
    open/filled/closed,保证 by_status key 一致性。
    """
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
        "sold_orders": 0,       # filled 的订单数(含 bought 老字面量)
        "total_pnl": 0.0,
        "avg_return_pct": 0.0,
    }
    for r in rows:
        # 归一化 status key(老字面量 → 新名字)
        new_status = _legacy_status_to_new(r["status"])
        # 合并同一新名字下的多行(老+新字面量)
        if new_status in summary["by_status"]:
            existing = summary["by_status"][new_status]
            existing["count"] += r["cnt"]
            existing["total_pnl"] += r["total_pnl"]
            # avg_return_pct 不再平均(避免错误),保留首次记录
        else:
            summary["by_status"][new_status] = {
                "count": r["cnt"],
                "total_pnl": r["total_pnl"],
                "avg_return_pct": r["avg_return_pct"],
            }
        summary["total_orders"] += r["cnt"]
        if new_status == STATUS_CLOSED:
            summary["sold_orders"] += r["cnt"]
            summary["total_pnl"] += r["total_pnl"]
    # 重新算 avg_return_pct (从闭合计)
    closed = summary["by_status"].get(STATUS_CLOSED)
    if closed and closed["count"] > 0:
        # 重新拉一次 closed 状态数据算 avg
        closed_rows = query_all(
            """SELECT AVG(net_return_pct) as avg
               FROM t1_pending_orders
               WHERE user_id = ? AND status IN ('closed', 'sold')
                 AND created_at >= date('now', ?)""",
            (user_id, f"-{days} days"),
        )
        if closed_rows and closed_rows[0].get("avg") is not None:
            summary["avg_return_pct"] = closed_rows[0]["avg"]
    return summary
