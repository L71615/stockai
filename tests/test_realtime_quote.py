"""v5.0-alpha M1 — 实时行情服务 + REST 测试

覆盖:
  - is_trading_hours / is_trading_day 时段判断
  - RealtimeQuoteService 单例
  - subscribe / get_snapshot / _update_quotes / _poll_once
  - REST /api/realtime/watchlist / trading-status / all
"""
from __future__ import annotations

from datetime import datetime, time
from unittest.mock import patch

import pytest


# ─────────────────────── 时段判断 ───────────────────────


class TestTradingHours:
    def test_is_trading_hours_workday_morning(self):
        # 周三 10:00
        ts = datetime(2026, 8, 5, 10, 0)  # 2026-08-05 是周三
        assert _call(ts) is True

    def test_is_trading_hours_workday_lunch(self):
        # 周三 12:00 (午休)
        ts = datetime(2026, 8, 5, 12, 0)
        assert _call(ts) is False

    def test_is_trading_hours_workday_afternoon(self):
        # 周三 14:00
        ts = datetime(2026, 8, 5, 14, 0)
        assert _call(ts) is True

    def test_is_trading_hours_before_open(self):
        ts = datetime(2026, 8, 5, 9, 0)
        assert _call(ts) is False

    def test_is_trading_hours_after_close(self):
        ts = datetime(2026, 8, 5, 15, 30)
        assert _call(ts) is False

    def test_is_trading_hours_weekend(self):
        # 2026-08-01 是周六
        ts = datetime(2026, 8, 1, 10, 0)
        assert _call(ts) is False

    def test_is_trading_hours_boundary_open(self):
        # 9:30 整
        ts = datetime(2026, 8, 5, 9, 30)
        assert _call(ts) is True

    def test_is_trading_hours_boundary_close(self):
        # 15:00 整(收盘)
        ts = datetime(2026, 8, 5, 15, 0)
        assert _call(ts) is True


def _call(ts):
    from services.realtime_quote import is_trading_hours
    return is_trading_hours(ts)


# ─────────────────────── 服务类 ───────────────────────


class TestRealtimeQuoteService:
    def test_singleton(self):
        from services.realtime_quote import RealtimeQuoteService
        s1 = RealtimeQuoteService()
        s2 = RealtimeQuoteService()
        assert s1 is s2

    def test_get_snapshot_empty_codes(self):
        from services.realtime_quote import get_quote_service
        assert get_quote_service().get_snapshot([]) == []

    def test_get_snapshot_returns_only_requested(self):
        from services.realtime_quote import get_quote_service, Quote
        svc = get_quote_service()
        # 手动注入
        svc._quotes = {"000725": Quote(code="000725", name="京东方"), "600519": Quote(code="600519", name="茅台")}
        result = svc.get_snapshot(["000725"])
        assert len(result) == 1
        assert result[0].code == "000725"

    def test_subscribe_registers_callback(self):
        from services.realtime_quote import get_quote_service
        svc = get_quote_service()
        cb = lambda q: None
        before = len(svc._subscribers)
        svc.subscribe(cb)
        assert len(svc._subscribers) == before + 1

    def test_update_quotes_pushes_to_subscribers(self):
        from services.realtime_quote import get_quote_service, Quote
        svc = get_quote_service()
        received = []
        svc.subscribe(lambda q: received.append(q))
        new_q = Quote(code="000725", name="test", price=4.5)
        svc._update_quotes([new_q])
        assert any(r.code == "000725" for r in received)
        assert svc._quotes.get("000725") is not None

    def test_update_quotes_subscriber_exception_doesnt_break(self):
        from services.realtime_quote import get_quote_service, Quote
        svc = get_quote_service()
        def bad_cb(q):
            raise RuntimeError("boom")
        good_calls = []
        svc.subscribe(bad_cb)
        svc.subscribe(lambda q: good_calls.append(q))
        svc._update_quotes([Quote(code="000725", name="x", price=1.0)])
        # 即使坏 callback 抛异常, 好 callback 仍收到
        assert len(good_calls) >= 1


# ─────────────────────── _poll_once ───────────────────────


class TestPollOnce:
    def test_poll_once_returns_empty_for_empty_codes(self):
        from services.realtime_quote import get_quote_service
        svc = get_quote_service()
        result = svc._poll_once.run(svc, []) if hasattr(svc._poll_once, "run") else None
        # 实际跑一下 coroutine
        import asyncio
        out = asyncio.run(svc._poll_once([]))
        assert out == []

    def test_poll_once_uses_akshare_batch(self):
        from services.realtime_quote import get_quote_service
        svc = get_quote_service()
        import asyncio
        with patch("services.akshare_adapter.get_batch_quotes") as mock_batch:
            mock_batch.return_value = {
                "000725": {"code": "000725", "name": "京东方A", "price": 4.5,
                           "yesterday_close": 4.4, "open": 4.4, "high": 4.6,
                           "low": 4.3, "volume": 1000000, "amount": 4500000.0,
                           "change": 0.1, "change_pct": 2.27, "source": "tencent"},
            }
            out = asyncio.run(svc._poll_once(["000725"]))
            mock_batch.assert_called_once_with(["000725"])
        assert len(out) == 1
        assert out[0].code == "000725"
        assert out[0].price == 4.5
        assert out[0].change_pct == 2.27

    def test_poll_once_handles_exception(self):
        from services.realtime_quote import get_quote_service
        svc = get_quote_service()
        import asyncio
        with patch("services.akshare_adapter.get_batch_quotes", side_effect=Exception("network")):
            out = asyncio.run(svc._poll_once(["000725"]))
        assert out == []


# ─────────────────────── REST API ───────────────────────


class TestRestApi:
    def test_watchlist_endpoint_returns_quotes(self, client):
        from services.realtime_quote import get_quote_service, Quote
        svc = get_quote_service()
        svc._quotes = {
            "000725": Quote(code="000725", name="京东方A", price=4.5, change_pct=2.0),
        }
        resp = client.get("/api/realtime/watchlist?codes=000725")
        assert resp.status_code == 200
        data = resp.json()
        assert "quotes" in data
        assert "ts" in data
        assert "is_trading" in data
        assert data["quotes"][0]["code"] == "000725"

    def test_watchlist_endpoint_empty_codes(self, client):
        resp = client.get("/api/realtime/watchlist?codes=")
        assert resp.status_code == 200
        assert resp.json()["quotes"] == []

    def test_trading_status_endpoint(self, client):
        resp = client.get("/api/realtime/trading-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_trading_hours" in data
        assert "is_trading_day" in data

    def test_all_endpoint(self, client):
        from services.realtime_quote import get_quote_service, Quote
        svc = get_quote_service()
        svc._quotes = {
            "000725": Quote(code="000725", name="test"),
        }
        resp = client.get("/api/realtime/all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1