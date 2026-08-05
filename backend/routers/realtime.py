"""实时行情 API — v5.0-alpha M1

REST 端点:
  GET /api/realtime/watchlist?codes=000725,600519  — 一次性 snapshot
  GET /api/realtime/trading-status                — 盘中/盘后/周末 状态
  GET /api/realtime/all                           — 当前 cache 的所有 quote

WebSocket:
  /api/realtime/ws                                — 实时推送(v5.0-beta M5 升级)
"""
from __future__ import annotations

import asyncio
import json
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
    """WebSocket 实时推送 — v5.0-beta M5 真实推送实现

    协议:
      - 客户端发: {"type": "subscribe", "codes": ["000725", "600519"]}
      - 服务端推: {"type": "snapshot", "quotes": [...]}
      - 服务端推: {"type": "quote", ...quote.to_dict()...}  // 每次 service 更新
      - 客户端发: {"type": "unsubscribe", "codes": ["..."]}
      - 客户端发: "ping" → 服务端返 {"type": "pong"}

    多客户端: 每连接独立 subscribed_codes,共享 RealtimeQuoteService 单例。
    """
    await websocket.accept()
    service = get_quote_service()
    loop = asyncio.get_event_loop()
    subscribed_codes: set[str] = set()

    def push_quote(quote):
        """service.subscribe callback — 在 service 线程被调,跨线程 send_json"""
        if quote.code not in subscribed_codes:
            return
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "quote", **quote.to_dict()}),
            loop,
        )

    service.subscribe(push_quote)

    try:
        # 立即推一次 trading status
        await websocket.send_json({
            "type": "trading_status",
            "is_trading_hours": is_trading_hours(),
            "is_trading_day": is_trading_day(),
            "ts": time.time(),
        })

        while True:
            msg = await websocket.receive_text()

            # ping/pong 字符串协议(简单)
            if msg == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
                continue

            # JSON 协议(subscribe/unsubscribe)
            try:
                data = json.loads(msg)
                msg_type = data.get("type")
                codes = data.get("codes", [])

                if msg_type == "subscribe":
                    subscribed_codes.update(codes)
                    # 立即推一次 snapshot
                    snapshot = service.get_snapshot(list(subscribed_codes))
                    await websocket.send_json({
                        "type": "snapshot",
                        "quotes": [q.to_dict() for q in snapshot],
                        "ts": time.time(),
                    })
                elif msg_type == "unsubscribe":
                    subscribed_codes.difference_update(codes)
                else:
                    logger.debug("realtime ws unknown type: %s", msg_type)
            except (json.JSONDecodeError, AttributeError) as e:
                logger.debug("realtime ws invalid msg: %s (%s)", msg[:50], e)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("realtime ws error: %s", e)
    finally:
        service.unsubscribe(push_quote)  # 清理 subscriber,避免泄漏
        try:
            await websocket.close()
        except Exception:
            pass