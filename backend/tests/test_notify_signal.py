"""v5.0-beta M9 — 通知推送测试 (5 个 mock 测试)

覆盖:
  1. signal 触发 → send_signal 调通
  2. 5min dedup — 同一 (code, strategy) 不重推
  3. NOTIFY_ENABLED=false → 跳过推送
  4. 发送失败不阻塞 scanner(异常隔离)
  5. 多 channel 并行(wechat + telegram + email)
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict
from unittest.mock import patch

import pytest

from services.realtime_signal import RealtimeSignal
from services.realtime_signal_scanner import (
    DEDUP_TTL_SECONDS,
    _dedup_state,
    _reset_dedup,
    _should_push,
)
from services import notify_service


# ── Fixtures ──


@pytest.fixture(autouse=True)
def reset_dedup():
    """每个测试清空 dedup 缓存"""
    _reset_dedup()
    yield
    _reset_dedup()


@pytest.fixture
def fake_signal():
    return RealtimeSignal(
        strategy_id="turtle_s1",
        strategy_name="海龟通道突破",
        stock_code="600519",
        direction="buy",
        score=0.85,
        triggered_at=time.time(),
        reason="突破 20 日新高 + 成交量放大 2.3x",
        snapshot_factors={"ret_20d": 0.12, "close": 1680.0},
    )


# ── 测试 ──


def test_signal_trigger_calls_send_signal(fake_signal, monkeypatch):
    """signal 触发 → send_signal 调通 3 渠道"""
    monkeypatch.setenv("NOTIFY_ENABLED", "true")
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://example.com/wechat")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("EMAIL_SENDER", "bot@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "fake_pwd")
    monkeypatch.setenv("EMAIL_RECEIVER", "me@example.com")

    # mock 3 个 channel 实际 HTTP/SMTP 调用
    with patch.object(notify_service, "_send_wechat", return_value=True) as m_wx, \
         patch.object(notify_service, "_send_telegram", return_value=True) as m_tg, \
         patch.object(notify_service, "_send_email", return_value=True) as m_em, \
         patch.object(notify_service, "_log_notification"):  # 不写 audit
        result = notify_service.send_signal(fake_signal)

    assert result["sent"] is True
    assert m_wx.called
    assert m_tg.called
    assert m_em.called


def test_dedup_blocks_within_5min(fake_signal):
    """同一 (code, strategy) 5min 内 _should_push 第二次返 False"""
    assert _should_push("600519", "turtle_s1") is True
    assert _should_push("600519", "turtle_s1") is False
    assert _should_push("600519", "turtle_s1") is False
    # 不同 code 或 strategy 仍可推
    assert _should_push("000725", "turtle_s1") is True
    assert _should_push("600519", "boll_mean") is True


def test_dedup_expires_after_ttl(fake_signal):
    """5min TTL 过期后重新可推(用 mock time 加速)"""
    with patch("time.time") as m_time:
        m_time.return_value = 1000.0
        assert _should_push("600519", "turtle_s1") is True

        m_time.return_value = 1000.0 + DEDUP_TTL_SECONDS - 1
        assert _should_push("600519", "turtle_s1") is False  # 仍在 5min 内

        m_time.return_value = 1000.0 + DEDUP_TTL_SECONDS + 1
        assert _should_push("600519", "turtle_s1") is True  # 已过期


def test_send_signal_skipped_when_notify_disabled(fake_signal):
    """NOTIFY_ENABLED=false → send_signal 跳过不发送"""
    os.environ["NOTIFY_ENABLED"] = "false"
    # 强制刷新配置缓存
    with patch.object(notify_service, "_send_wechat") as m_wx, \
         patch.object(notify_service, "_send_telegram") as m_tg, \
         patch.object(notify_service, "_send_email") as m_em:
        result = notify_service.send_signal(fake_signal)
    assert result["sent"] is False
    assert "NOTIFY_ENABLED" in result.get("reason", "")
    m_wx.assert_not_called()
    m_tg.assert_not_called()
    m_em.assert_not_called()


def test_send_failure_does_not_block_scanner(fake_signal, monkeypatch):
    """send_signal 抛异常不阻塞 scanner(异常隔离)"""
    monkeypatch.setenv("NOTIFY_ENABLED", "true")
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://example.com/wechat")

    # scanner._tick 内部 `from services.notify_service import send_signal` (函数内 import)
    # 所以要 mock 原始模块,不是 scanner 模块
    with patch("services.realtime_signal_scanner.scan_signals", return_value=[fake_signal]), \
         patch("services.realtime_signal_scanner.is_trading_hours", return_value=True), \
         patch("services.realtime_signal_scanner.log_signal"), \
         patch("services.notify_service.send_signal", side_effect=RuntimeError("boom")):
        from services.realtime_signal_scanner import RealtimeSignalScanner
        scanner = RealtimeSignalScanner()
        # 关键: _tick 内部 try/except,send_signal 抛异常不阻塞
        try:
            scanner._tick(["turtle_s1"])
        except Exception as e:
            pytest.fail(f"_tick 不应让异常传出: {e}")


# 简化版: 上面 test_send_failure 太复杂,改写一个更聚焦的

def test_send_signal_isolates_channel_failures(fake_signal, monkeypatch):
    """单个 channel 失败不影响其他 channel(send_notification 设计)"""
    monkeypatch.setenv("NOTIFY_ENABLED", "true")
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://example.com/wechat")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("EMAIL_SENDER", "bot@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "fake_pwd")

    # wechat 失败, telegram + email 成功
    with patch.object(notify_service, "_send_wechat", return_value=False), \
         patch.object(notify_service, "_send_telegram", return_value=True), \
         patch.object(notify_service, "_send_email", return_value=True), \
         patch.object(notify_service, "_log_notification"):
        result = notify_service.send_signal(fake_signal)

    # wechat 失败不应阻止 telegram/email; 至少一个成功 → sent=True
    assert result["sent"] is True
    assert result["channels"]["wechat"] is False
    assert result["channels"]["telegram"] is True
    assert result["channels"]["email"] is True
