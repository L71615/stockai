"""实时行情 API — v5.0-alpha M1

REST 端点:
  GET /api/realtime/watchlist?codes=000725,600519  — 一次性 snapshot
  GET /api/realtime/trading-status                — 盘中/盘后/周末 状态
  GET /api/realtime/all                           — 当前 cache 的所有 quote

WebSocket:
  /api/realtime/ws                                — 实时推送(beta 阶段)
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from services.realtime_quote import (
    get_quote_service,
    is_trading_hours,
    is_trading_day,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/realtime", tags=["Realtime"])


@router.get("/watchlist")
def get_watchlist_quotes(
    codes: str = Query(..., description="逗号分隔股票代码, e.g. '000725,600519'"),
):
    """REST 一次性取 snapshot — 给前端 SWR 高频轮询用

    Returns:
        {"quotes": [{...Quote dict...}, ...], "ts": float, "is_trading": bool}
    """
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    service = get_quote_service()
    quotes = service.get_snapshot(code_list)
    return {
        "quotes": [q.to_dict() for q in quotes],
        "ts": time.time(),
        "is_trading": is_trading_hours(),
        "is_trading_day": is_trading_day(),
    }


@router.get("/all")
def get_all_quotes():
    """取当前 cache 的所有 quote — 用于测试 + 调试"""
    service = get_quote_service()
    codes = service.get_all_codes()
    quotes = service.get_snapshot(codes)
    return {
        "quotes": [q.to_dict() for q in quotes],
        "count": len(quotes),
        "ts": time.time(),
    }


@router.get("/trading-status")
def get_trading_status():
    """返回当前是否在交易时段 — 用于前端决定是否展示"实时"徽章"""
    return {
        "is_trading_hours": is_trading_hours(),
        "is_trading_day": is_trading_day(),
        "ts": time.time(),
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时推送 — beta 阶段实现

    v5.0-alpha 简化: 只接受连接 + 立即断开, 留 hook 给 beta 阶段做真实推送
    """
    await websocket.accept()
    try:
        # 立即推送一次当前 trading status
        await websocket.send_json({
            "type": "trading_status",
            "is_trading_hours": is_trading_hours(),
            "is_trading_day": is_trading_day(),
            "ts": time.time(),
        })
        # 维持连接(等前端发任意消息或断连)
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("realtime ws error: %s", e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass