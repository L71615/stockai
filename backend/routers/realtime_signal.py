"""盘中信号 REST API — v5.0-alpha M3

  GET  /api/realtime/signal/recent?limit=50       — 最近 N 条信号
  POST /api/realtime/signal/{id}/accept           — 手动确认 → 调 t1_watcher.create_pending_order
  GET  /api/realtime/signal/{id}                  — 单条详情
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from services.realtime_signal_log import (
    get_signal, mark_accepted, recent_signals,
)
from services.realtime_quote import get_quote_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/realtime/signal", tags=["RealtimeSignal"])


@router.get("/recent")
def get_recent_signals(limit: int = Query(default=50, ge=1, le=200)):
    """最近 N 条信号(按时间倒序)"""
    return {"signals": recent_signals(limit=limit), "count": min(limit, 200)}


@router.get("/{signal_id}")
def get_signal_detail(signal_id: int):
    """单条信号详情"""
    sig = get_signal(signal_id)
    if sig is None:
        raise HTTPException(404, f"信号 {signal_id} 不存在")
    return sig


@router.post("/{signal_id}/accept")
def accept_signal(signal_id: int):
    """手动确认信号 → 创建 T+1 模拟下单

    alpha 简化:
      - shares=100, slippage=10bps
      - 用户 ID 取第一个 admin 用户(alpha 阶段单用户)
      - 关联 order_id 写回 signal_log
    """
    sig = get_signal(signal_id)
    if sig is None:
        raise HTTPException(404, f"信号 {signal_id} 不存在")
    if sig["accepted"]:
        raise HTTPException(409, f"信号 {signal_id} 已被接受 (order_id={sig['order_id']})")

    # 取当前行情(用于 planned_entry_price)
    code = sig["stock_code"]
    quote_service = get_quote_service()
    snapshots = quote_service.get_snapshot([code])
    if not snapshots:
        raise HTTPException(503, f"无法获取 {code} 实时行情")

    price = float(snapshots[0].price)

    # alpha 阶段: 用户 ID 取 admin(单用户)
    from database import query_one
    admin = query_one(
        "SELECT id FROM users WHERE email = ? OR username = 'admin' LIMIT 1",
        ("admin@stockai.com",),
    )
    if admin is None:
        raise HTTPException(500, "系统中找不到用户")
    user_id = admin["id"]

    # 创建 T+1 模拟下单
    from services.t1_watcher import create_pending_order
    today = date.today().isoformat()
    order = create_pending_order(
        user_id=user_id,
        stock_code=code,
        stock_name="盘中信号触发",  # alpha 简化
        shares=100,
        planned_entry_price=price,
        slippage_bps=10.0,
        entry_date=today,
        reason=f"realtime_signal:{sig['strategy_id']}",
        source="realtime_signal",
    )

    # 标记信号已被接受
    mark_accepted(signal_id, order_id=order["id"])

    logger.info("realtime_signal: 信号 %d 已接受, 创建订单 %d, 价格 %.2f",
                signal_id, order["id"], price)

    return {
        "signal_id": signal_id,
        "order_id": order["id"],
        "price": price,
        "stock_code": code,
        "ts": __import__("time").time(),
    }