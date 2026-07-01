"""Futu 数据接入测试 — 数据库 schema / ingest / fallback / API smoke test

当前阶段覆盖：
- Task 1: init_db 应创建 Futu raw 表与唯一索引
- Task 3: raw 落库 / 日线同步 / 幂等
- Task 4: fallback 包装函数
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db, query_one, query_all
from services.futu_ingest_service import (
    sync_daily_kline,
    sync_minute_kline,
    sync_quote,
    get_quote_with_fallback,
    get_daily_kline_with_fallback,
)


class _StubClient:
    def get_snapshot(self, codes):
        code = codes[0]
        market = "SH" if code.startswith(("51", "56", "58", "60", "68")) else "SZ"
        return [{
            "code": code,
            "market": market,
            "symbol": f"{market}.{code}",
            "name": "测试股票",
            "price": 1234.5,
            "open_price": 1220.0,
            "high_price": 1240.0,
            "low_price": 1218.0,
            "prev_close": 1210.0,
            "change": 24.5,
            "change_pct": 2.02,
            "volume": 2000,
            "turnover": 3000000,
            "quote_time": "2026-07-01 10:30:00",
            "source": "futu",
            "raw_payload": "{}",
        }]

    def get_kline(self, code, interval, count=200, adjust_type="qfq"):
        market = "SH" if code.startswith(("51", "56", "58", "60", "68")) else "SZ"
        return {
            "code": code,
            "market": market,
            "symbol": f"{market}.{code}",
            "interval": interval,
            "adjust_type": adjust_type,
            "dates": ["2026-07-01", "2026-07-02"],
            "opens": [1200.0, 1210.0],
            "highs": [1250.0, 1260.0],
            "lows": [1190.0, 1200.0],
            "closes": [1234.5, 1255.0],
            "volumes": [2000, 2100],
            "turnovers": [3000000, 3200000],
            "raw_rows": [{"time_key": "2026-07-01 00:00:00"}, {"time_key": "2026-07-02 00:00:00"}],
            "source": "futu",
        }


class _FailingClient:
    def get_snapshot(self, codes):
        return [{"error": "opend offline", "source": "futu"}]

    def get_kline(self, code, interval, count=200, adjust_type="qfq"):
        return {"error": "opend offline", "source": "futu", "code": code}


def test_init_db_creates_futu_raw_tables(db):
    init_db()

    quote_table = query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='futu_raw_quote'"
    )
    kline_table = query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='futu_raw_kline'"
    )
    unique_index = query_one(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='uq_futu_raw_kline_bar'"
    )

    assert quote_table is not None
    assert kline_table is not None
    assert unique_index is not None


def test_sync_quote_writes_raw_table(db):
    result = sync_quote("600519", client=_StubClient())

    row = query_one(
        "SELECT symbol, price, source FROM futu_raw_quote WHERE code = ? ORDER BY id DESC LIMIT 1",
        ("600519",),
    )

    assert result["price"] == 1234.5
    assert row["symbol"] == "SH.600519"
    assert row["source"] == "futu"


def test_sync_daily_kline_writes_raw_and_historical(db):
    result = sync_daily_kline("600519", count=2, client=_StubClient())

    raw_rows = query_all(
        "SELECT symbol, interval, bar_time FROM futu_raw_kline WHERE code = ? ORDER BY bar_time",
        ("600519",),
    )
    hist_rows = query_all(
        "SELECT stock_code, trade_date, close FROM historical_kline WHERE stock_code = ? ORDER BY trade_date",
        ("600519",),
    )

    assert result["source"] == "futu"
    assert len(raw_rows) == 2
    assert raw_rows[0]["interval"] == "1d"
    assert len(hist_rows) == 2
    assert hist_rows[0]["stock_code"] == "600519"


def test_sync_minute_kline_only_writes_raw(db):
    sync_minute_kline("000001", count=2, client=_StubClient())

    raw_rows = query_all(
        "SELECT symbol, interval FROM futu_raw_kline WHERE code = ?",
        ("000001",),
    )
    hist_rows = query_all(
        "SELECT stock_code FROM historical_kline WHERE stock_code = ?",
        ("000001",),
    )

    assert raw_rows
    assert all(row["interval"] == "1m" for row in raw_rows)
    assert hist_rows == []


def test_sync_daily_kline_is_idempotent(db):
    client = _StubClient()

    sync_daily_kline("300750", count=2, client=client)
    sync_daily_kline("300750", count=2, client=client)

    raw_count = query_one(
        "SELECT COUNT(*) AS n FROM futu_raw_kline WHERE code = ? AND interval = '1d'",
        ("300750",),
    )
    hist_count = query_one(
        "SELECT COUNT(*) AS n FROM historical_kline WHERE stock_code = ?",
        ("300750",),
    )

    assert raw_count["n"] == 2
    assert hist_count["n"] == 2


def test_get_quote_with_fallback_returns_old_source_when_futu_fails(db):
    result = get_quote_with_fallback(
        "600519",
        fallback=lambda: {"code": "600519", "price": 1000.0, "source": "legacy"},
        client=_FailingClient(),
    )

    assert result["source"] == "legacy"
    assert result["price"] == 1000.0




from services import technical


def test_fetch_kline_uses_futu_daily_first_for_a_share(monkeypatch):
    monkeypatch.setattr(
        "services.futu_ingest_service.get_daily_kline_with_fallback",
        lambda code, count, fallback, client=None: {
            "code": code,
            "dates": ["2026-07-01"],
            "opens": [10.0],
            "highs": [11.0],
            "lows": [9.0],
            "closes": [10.5],
            "volumes": [1000],
            "source": "futu",
        },
    )

    result = technical.fetch_kline("600519", days=1)

    assert result["source"] == "futu"
    assert result["closes"] == [10.5]
