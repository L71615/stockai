"""v5.0-alpha M3 — 盘中信号扫描 + 手动确认测试

覆盖:
  - realtime_signal: scan_signals / _evaluate_code / 未知策略跳过 / 空候选返回
  - realtime_signal_log: log_signal / mark_accepted / recent_signals / get_signal
  - REST: GET /signal/recent / POST /signal/{id}/accept / 404 / 409
  - RealtimeSignalScanner: _loop / _tick / _candidate_codes
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────── realtime_signal ───────────────────────


class TestRealtimeSignalScan:
    def test_scan_signals_empty_candidates_returns_empty(self, _test_db_session):
        from services.realtime_signal import scan_signals
        result = scan_signals(enabled_strategies=["boll_mean"], candidate_codes=[])
        assert result == []

    def test_scan_signals_empty_strategies_returns_empty(self, _test_db_session):
        from services.realtime_signal import scan_signals
        result = scan_signals(enabled_strategies=[], candidate_codes=["000725"])
        assert result == []

    def test_scan_signals_skips_unknown_strategy(self, _test_db_session):
        from services.realtime_signal import scan_signals
        # 注入 K 线 + 启用了未注册的策略 → 不抛
        _insert_kline("000725", 60)
        # 异常策略会导致 _load_strategy_conditions 失败, scan_signals 静默返回 []
        result = scan_signals(
            enabled_strategies=["__nonexistent__"],
            candidate_codes=["000725"],
        )
        assert result == []

    def test_evaluate_code_returns_none_on_insufficient_data(self, _test_db_session):
        from services.realtime_signal import _evaluate_code
        # 没插 K 线 → 返回 None
        result = _evaluate_code("NOSUCHCODE", window=60)
        assert result is None

    def test_evaluate_code_builds_stock_data(self, _test_db_session):
        from services.realtime_signal import _evaluate_code
        _insert_kline("000725", 60)
        result = _evaluate_code("000725", window=60)
        assert result is not None
        # 基础字段
        assert "close" in result
        assert "price" in result
        assert result["close"] == result["price"]
        # M2 因子字段(至少 ma5 应有值)
        assert "ma5" in result
        assert "rsi_14" in result
        assert "vol_ratio" in result
        # M3 补算字段
        assert "avg_amount_20d" in result
        assert "high_20d" in result
        assert "atr_pct" in result


# ─────────────────────── realtime_signal_log ───────────────────────


class TestRealtimeSignalLog:
    def test_log_signal_returns_id(self, _test_db_session):
        from services.realtime_signal import RealtimeSignal
        from services.realtime_signal_log import log_signal, recent_signals
        sig = RealtimeSignal(
            strategy_id="boll_mean",
            strategy_name="布林带回归",
            stock_code="000725",
            direction="buy",
            score=0.75,
            triggered_at=time.time(),
            reason="测试",
            snapshot_factors={"close": 4.5, "ma5": 4.4},
        )
        new_id = log_signal(sig)
        assert new_id > 0

        # recent_signals 应能查到
        rows = recent_signals(limit=10)
        assert any(r["id"] == new_id for r in rows)

    def test_recent_signals_returns_desc_by_time(self, _test_db_session):
        from services.realtime_signal import RealtimeSignal
        from services.realtime_signal_log import log_signal, recent_signals
        now = time.time()
        # 写 3 条信号(顺序触发)
        ids = []
        for i in range(3):
            sig = RealtimeSignal(
                strategy_id="momentum",
                strategy_name="动量",
                stock_code="000725",
                direction="buy",
                score=0.7,
                triggered_at=now + i,
                reason=f"测试{i}",
                snapshot_factors={},
            )
            ids.append(log_signal(sig))

        rows = recent_signals(limit=10)
        # 最近的在最前
        assert rows[0]["id"] == ids[-1]
        assert rows[1]["id"] == ids[-2]

    def test_mark_accepted(self, _test_db_session):
        from services.realtime_signal import RealtimeSignal
        from services.realtime_signal_log import (
            get_signal, log_signal, mark_accepted,
        )
        sig = RealtimeSignal(
            strategy_id="momentum", strategy_name="动量",
            stock_code="000725", direction="buy", score=0.7,
            triggered_at=time.time(), reason="测试", snapshot_factors={},
        )
        sid = log_signal(sig)
        # 默认 accepted=False
        assert get_signal(sid)["accepted"] is False
        # 标记 + 关联 order_id
        mark_accepted(sid, order_id=42)
        row = get_signal(sid)
        assert row["accepted"] is True
        assert row["order_id"] == 42

    def test_get_signal_returns_none_for_invalid_id(self, _test_db_session):
        from services.realtime_signal_log import get_signal
        assert get_signal(999999) is None


# ─────────────────────── REST API ───────────────────────


class TestSignalRestApi:
    def test_recent_endpoint_returns_list(self, client, _test_db_session):
        from services.realtime_signal import RealtimeSignal
        from services.realtime_signal_log import log_signal
        # 写 2 条信号
        for i in range(2):
            log_signal(RealtimeSignal(
                strategy_id="momentum", strategy_name="动量",
                stock_code="000725", direction="buy", score=0.7,
                triggered_at=time.time(), reason=f"测试{i}", snapshot_factors={},
            ))
        resp = client.get("/api/realtime/signal/recent?limit=10")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "signals" in data
        assert data["count"] == 10
        assert len(data["signals"]) >= 2

    def test_get_signal_detail(self, client, _test_db_session):
        from services.realtime_signal import RealtimeSignal
        from services.realtime_signal_log import log_signal
        sid = log_signal(RealtimeSignal(
            strategy_id="boll_mean", strategy_name="布林带回归",
            stock_code="000725", direction="buy", score=0.7,
            triggered_at=time.time(), reason="测试", snapshot_factors={},
        ))
        resp = client.get(f"/api/realtime/signal/{sid}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == sid
        assert data["accepted"] is False

    def test_get_signal_404(self, client):
        resp = client.get("/api/realtime/signal/999999")
        assert resp.status_code == 404

    def test_accept_signal_creates_order(self, client, _test_db_session):
        from services.realtime_signal import RealtimeSignal
        from services.realtime_signal_log import log_signal, get_signal
        sid = log_signal(RealtimeSignal(
            strategy_id="boll_mean", strategy_name="布林带回归",
            stock_code="000725", direction="buy", score=0.7,
            triggered_at=time.time(), reason="测试", snapshot_factors={},
        ))

        # mock 行情服务, 避免依赖真实数据源
        mock_quote = MagicMock()
        mock_quote.price = 4.5
        with patch("routers.realtime_signal.get_quote_service") as mock_qs:
            mock_service = MagicMock()
            mock_service.get_snapshot.return_value = [mock_quote]
            mock_qs.return_value = mock_service

            resp = client.post(f"/api/realtime/signal/{sid}/accept")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["signal_id"] == sid
        assert data["order_id"] > 0
        assert data["price"] == 4.5
        assert data["stock_code"] == "000725"
        # 信号应被标记 accepted
        assert get_signal(sid)["accepted"] is True

    def test_accept_signal_409_already_accepted(self, client, _test_db_session):
        from services.realtime_signal import RealtimeSignal
        from services.realtime_signal_log import log_signal
        sig = RealtimeSignal(
            strategy_id="boll_mean", strategy_name="布林带回归",
            stock_code="000725", direction="buy", score=0.7,
            triggered_at=time.time(), reason="测试", snapshot_factors={},
        )
        sid = log_signal(sig)

        # mock 行情
        mock_quote = MagicMock()
        mock_quote.price = 4.5
        with patch("routers.realtime_signal.get_quote_service") as mock_qs:
            mock_service = MagicMock()
            mock_service.get_snapshot.return_value = [mock_quote]
            mock_qs.return_value = mock_service
            # 第一次
            r1 = client.post(f"/api/realtime/signal/{sid}/accept")
            assert r1.status_code == 200
            # 第二次 → 409
            r2 = client.post(f"/api/realtime/signal/{sid}/accept")
            assert r2.status_code == 409

    def test_accept_signal_404(self, client):
        mock_quote = MagicMock()
        mock_quote.price = 4.5
        with patch("routers.realtime_signal.get_quote_service") as mock_qs:
            mock_service = MagicMock()
            mock_service.get_snapshot.return_value = [mock_quote]
            mock_qs.return_value = mock_service
            resp = client.post("/api/realtime/signal/999999/accept")
        assert resp.status_code == 404


# ─────────────────────── Scanner 守护线程 ───────────────────────


class TestRealtimeSignalScanner:
    def test_scanner_singleton(self):
        from services.realtime_signal_scanner import RealtimeSignalScanner
        a = RealtimeSignalScanner()
        b = RealtimeSignalScanner()
        assert a is b

    def test_tick_skips_non_trading_hours(self, _test_db_session):
        from services.realtime_signal_scanner import RealtimeSignalScanner
        scanner = RealtimeSignalScanner()
        # 非交易时段 → _tick 直接返回, 不调 scan_signals
        with patch("services.realtime_signal_scanner.is_trading_hours", return_value=False):
            with patch("services.realtime_signal_scanner.scan_signals") as mock_scan:
                scanner._tick(["boll_mean"])
                mock_scan.assert_not_called()

    def test_tick_calls_scan_during_trading_hours(self, _test_db_session):
        from services.realtime_signal_scanner import RealtimeSignalScanner
        scanner = RealtimeSignalScanner()
        # 盘中 → _tick 调 scan_signals
        with patch("services.realtime_signal_scanner.is_trading_hours", return_value=True):
            with patch.object(scanner, "_candidate_codes", return_value=["000725"]):
                with patch("services.realtime_signal_scanner.scan_signals", return_value=[]) as mock_scan:
                    scanner._tick(["boll_mean"])
                    mock_scan.assert_called_once()

    def test_tick_logs_signals(self, _test_db_session):
        from services.realtime_signal_scanner import RealtimeSignalScanner
        from services.realtime_signal import RealtimeSignal
        scanner = RealtimeSignalScanner()
        sig = RealtimeSignal(
            strategy_id="momentum", strategy_name="动量",
            stock_code="000725", direction="buy", score=0.7,
            triggered_at=time.time(), reason="测试", snapshot_factors={},
        )
        with patch("services.realtime_signal_scanner.is_trading_hours", return_value=True):
            with patch.object(scanner, "_candidate_codes", return_value=["000725"]):
                with patch("services.realtime_signal_scanner.scan_signals", return_value=[sig]):
                    with patch("services.realtime_signal_scanner.log_signal") as mock_log:
                        scanner._tick(["momentum"])
                        mock_log.assert_called_once_with(sig)

    def test_candidate_codes_combines_holdings_and_watchlist(self, _test_db_session):
        from services.realtime_signal_scanner import RealtimeSignalScanner
        # ensure_admin_user() 已自动创建 admin, 取其 id
        from database import execute, query_one
        admin = query_one("SELECT id FROM users WHERE email = 'admin@stockai.com' LIMIT 1")
        assert admin is not None, "admin 用户应在 _test_db_session 中自动创建"
        uid = admin["id"]
        execute(
            "INSERT INTO holdings (user_id, stock_code, stock_name, quantity, cost_price) "
            "VALUES (?, '000725', '京东方A', 1000, 4.0)",
            (uid,),
        )
        execute(
            "INSERT INTO watchlist (user_id, stock_code, stock_name) "
            "VALUES (?, '600519', '贵州茅台')",
            (uid,),
        )
        codes = RealtimeSignalScanner()._candidate_codes()
        assert "000725" in codes
        assert "600519" in codes


# ─────────────────────── Helpers ───────────────────────


def _insert_kline(code: str, count: int) -> None:
    """插 N 根递增 close 的 historical_kline"""
    from database import execute
    base = date(2026, 5, 1)
    for i in range(count):
        d = (base + timedelta(days=i)).isoformat()
        execute(
            """INSERT OR IGNORE INTO historical_kline
               (stock_code, trade_date, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, d, 4.0 + i * 0.01, 4.5 + i * 0.01, 3.9 + i * 0.01,
             4.2 + i * 0.01, 1000000),
        )