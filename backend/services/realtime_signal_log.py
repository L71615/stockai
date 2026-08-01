"""信号历史表 — v5.0-alpha M3

表 realtime_signal_log(id, strategy_id, stock_code, direction, score,
                       triggered_at, accepted, order_id, snapshot_json)
让 /live 页面能展示最近 N 条信号, 记录"用户是否接受"。
"""
from __future__ import annotations

import json
import logging

from database import execute, query_all, query_one
from services.realtime_signal import RealtimeSignal

logger = logging.getLogger(__name__)


def log_signal(sig: RealtimeSignal) -> int:
    """写一条信号 → 返回新 ID"""
    result = execute(
        """INSERT INTO realtime_signal_log
           (strategy_id, stock_code, direction, score, triggered_at, accepted, snapshot_json)
           VALUES (?, ?, ?, ?, ?, 0, ?)""",
        (sig.strategy_id, sig.stock_code, sig.direction, sig.score,
         sig.triggered_at, json.dumps(sig.snapshot_factors, default=str, ensure_ascii=False)),
    )
    new_id = result["lastrowid"]
    logger.info("realtime_signal_log: 新信号 id=%d %s %s score=%.2f",
                new_id, sig.stock_code, sig.strategy_id, sig.score)
    return new_id


def mark_accepted(signal_id: int, order_id: int | None = None) -> None:
    """标记信号已被用户接受, 可选关联 t1_pending_orders.id"""
    if order_id is not None:
        execute(
            "UPDATE realtime_signal_log SET accepted = 1, order_id = ? WHERE id = ?",
            (order_id, signal_id),
        )
    else:
        execute(
            "UPDATE realtime_signal_log SET accepted = 1 WHERE id = ?",
            (signal_id,),
        )


def recent_signals(limit: int = 50) -> list[dict]:
    """最近 N 条信号, 按时间倒序"""
    rows = query_all(
        "SELECT id, strategy_id, stock_code, direction, score, triggered_at, "
        "       accepted, order_id, snapshot_json "
        "FROM realtime_signal_log ORDER BY triggered_at DESC LIMIT ?",
        (limit,),
    )
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "strategy_id": r["strategy_id"],
            "stock_code": r["stock_code"],
            "direction": r["direction"],
            "score": r["score"],
            "triggered_at": r["triggered_at"],
            "accepted": bool(r["accepted"]),
            "order_id": r["order_id"],
            "snapshot": _safe_load_json(r["snapshot_json"]),
        })
    return out


def get_signal(signal_id: int) -> dict | None:
    """取单条信号详情"""
    row = query_one(
        "SELECT id, strategy_id, stock_code, direction, score, triggered_at, "
        "       accepted, order_id, snapshot_json "
        "FROM realtime_signal_log WHERE id = ?",
        (signal_id,),
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "strategy_id": row["strategy_id"],
        "stock_code": row["stock_code"],
        "direction": row["direction"],
        "score": row["score"],
        "triggered_at": row["triggered_at"],
        "accepted": bool(row["accepted"]),
        "order_id": row["order_id"],
        "snapshot": _safe_load_json(row["snapshot_json"]),
    }


def _safe_load_json(s: str | None) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}