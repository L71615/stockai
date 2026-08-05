"""v5.0-beta M5 — WebSocket 实时推送测试 (5 个 mock 测试)

覆盖:
  1. connect + initial trading_status
  2. subscribe codes → 收 snapshot
  3. service 更新 → 客户端收 quote
  4. ping/pong
  5. 多客户端独立订阅 + 断开清理
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.realtime import router as realtime_router
from services.realtime_quote import (
    Quote,
    RealtimeQuoteService,
    get_quote_service,
)


# ── Fixtures ──────────────────────────────────────


@pytest.fixture
def app():
    """最小 FastAPI app(避免 main.py 启动开销 + JWT 依赖)"""
    a = FastAPI()
    a.include_router(realtime_router)
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_service():
    """每个测试重置 RealtimeQuoteService 单例(避免 subscribers 累积 + 缓存污染)"""
    svc = get_quote_service()
    with svc._lock:
        svc._subscribers.clear()
        svc._quotes.clear()
        svc._running = False
    yield


def _make_quote(code: str, price: float = 10.0) -> Quote:
    return Quote(
        code=code,
        name=f"测试{code}",
        price=price,
        yesterday_close=price - 0.5,
        open=price - 0.2,
        high=price + 0.3,
        low=price - 0.3,
        volume=10000,
        amount=price * 10000,
        change=0.5,
        change_pct=5.0,
        timestamp=time.time(),
        source="tencent",
    )


# ── 测试 ──────────────────────────────────────


def test_connect_receives_initial_trading_status(client):
    """连接立即收到 trading_status 消息"""
    with client.websocket_connect("/api/realtime/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "trading_status"
    assert "is_trading_hours" in msg
    assert "is_trading_day" in msg
    assert "ts" in msg


def test_subscribe_codes_returns_snapshot(client):
    """subscribe 消息 → 立即推 snapshot(空 cache)"""
    with client.websocket_connect("/api/realtime/ws") as ws:
        ws.receive_json()  # 消耗 trading_status
        ws.send_text(json.dumps({"type": "subscribe", "codes": ["000725", "600519"]}))
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["quotes"] == []  # cache 空


def test_service_update_pushes_quote_to_subscriber(client):
    """subscribe 后 service 推 quote → 客户端收到"""
    with client.websocket_connect("/api/realtime/ws") as ws:
        ws.receive_json()  # trading_status
        ws.send_text(json.dumps({"type": "subscribe", "codes": ["000725"]}))
        ws.receive_json()  # snapshot (空)

        # 模拟 service 推送(直接调 _update_quotes)
        svc = get_quote_service()
        quote = _make_quote("000725", price=4.5)
        svc._update_quotes([quote])

        msg = ws.receive_json()
    assert msg["type"] == "quote"
    assert msg["code"] == "000725"
    assert msg["price"] == 4.5
    assert msg["name"] == "测试000725"


def test_ping_returns_pong(client):
    """ping 文本消息 → 立即返 pong"""
    with client.websocket_connect("/api/realtime/ws") as ws:
        ws.receive_json()  # trading_status
        ws.send_text("ping")
        msg = ws.receive_json()
    assert msg["type"] == "pong"
    assert "ts" in msg


def test_multi_client_isolation_and_disconnect_cleanup(client):
    """多客户端独立订阅 + 断开时 subscriber 被清理"""
    svc = get_quote_service()
    initial_subs = len(svc._subscribers)

    # 客户端 A: 订阅 000725
    with client.websocket_connect("/api/realtime/ws") as ws_a:
        ws_a.receive_json()  # trading_status
        ws_a.send_text(json.dumps({"type": "subscribe", "codes": ["000725"]}))
        ws_a.receive_json()  # snapshot

        assert len(svc._subscribers) == initial_subs + 1

        # 客户端 B: 订阅 600519
        with client.websocket_connect("/api/realtime/ws") as ws_b:
            ws_b.receive_json()
            ws_b.send_text(json.dumps({"type": "subscribe", "codes": ["600519"]}))
            ws_b.receive_json()

            assert len(svc._subscribers) == initial_subs + 2

            # 推 600519 → 只有 B 应收(无 A 推送)
            svc._update_quotes([_make_quote("600519", price=1500.0)])

            # B 收到 quote
            msg_b = ws_b.receive_json()
            assert msg_b["type"] == "quote"
            assert msg_b["code"] == "600519"
            assert msg_b["price"] == 1500.0

        # B 关闭后,subscribers 只剩 A
        assert len(svc._subscribers) == initial_subs + 1

        # 推 000725 → A 收到(B 已关闭,不会再收)
        svc._update_quotes([_make_quote("000725", price=4.6)])
        msg_a = ws_a.receive_json()
        assert msg_a["code"] == "000725"
        assert msg_a["price"] == 4.6

    # A 也关闭后,subscribers 完全清理
    assert len(svc._subscribers) == initial_subs
