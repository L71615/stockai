"""Tests for technical._fetch_local_daily_kline (v3.10.3 K-line time fix).

背景: vendor_router 远程 K 线 API 受限频/缓存影响, 拿到的可能是几个月前的旧数据。
     _fetch_local_daily_kline 优先读本地 historical_kline 表, 不足时回退远程。

测试矩阵:
  - DB 无数据 → 返回 None (触发 fallback)
  - DB 数据 < 20 条 → 返回 None (触发 fallback, 即使 days=5)
  - DB 数据 30+ 条 → 返回 dict (走本地, source=local)
  - DB 异常 → 返回 None (不 crash)
"""

import sqlite3
from datetime import date, timedelta

import pytest

from database import execute_many, query_all

from services.technical import _fetch_local_daily_kline


def _seed_kline(code: str, days: int, start: date | None = None, close=None) -> None:
    """在测试 DB historical_kline 表插入 days 条数据"""
    if start is None:
        start = date(2026, 1, 1)
    statements = []
    for i in range(days):
        d = start + timedelta(days=i)
        statements.append(
            (
                "INSERT OR REPLACE INTO historical_kline (stock_code, trade_date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, d.isoformat(), 10.0 + i, 11.0 + i, 9.0 + i, close if close is not None else 10.5 + i, 1000 + i),
            )
        )
    execute_many(statements)


def test_returns_none_when_db_empty(db):
    """DB 完全没数据 → 返回 None, 触发 fallback"""
    assert _fetch_local_daily_kline("999999", 120) is None


def test_returns_none_when_too_few_rows(db):
    """DB 只有 5 条 (days=120) → 不够 30 条门槛, 返回 None"""
    _seed_kline("600000", 5)
    assert _fetch_local_daily_kline("600000", 120) is None


def test_returns_none_when_below_min_20(db):
    """days=5, DB 有 15 条 (低于 max(5//4, 20)=20 阈值) → 返回 None"""
    _seed_kline("600001", 15)
    assert _fetch_local_daily_kline("600001", 5) is None


def test_returns_kline_when_sufficient(db):
    """DB 有 100 条, days=60 → 返回 dict, dates 正序"""
    _seed_kline("600002", 100, start=date(2026, 1, 1))
    result = _fetch_local_daily_kline("600002", 60)
    assert result is not None
    assert result["source"] == "local"
    assert len(result["dates"]) == 60
    # 早→晚顺序
    assert result["dates"][0] < result["dates"][-1]
    # 取的是最后 60 天 (1月1日 + 99 = 4月10日)
    assert result["dates"][-1] == "2026-04-10"
    assert result["closes"][-1] == 10.5 + 99


def test_dates_trimmed_to_days(db):
    """DB 130 条, days=120 → 返回最后 120 条"""
    _seed_kline("600003", 130, start=date(2026, 1, 1))
    result = _fetch_local_daily_kline("600003", 120)
    assert result is not None
    assert len(result["dates"]) == 120


def test_returns_none_on_db_exception(db, monkeypatch):
    """DB query 抛异常 → 返回 None (不 crash 调用方)"""
    import database

    def _raise(*a, **kw):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(database, "query_all", _raise)
    result = _fetch_local_daily_kline("600005", 60)
    assert result is None