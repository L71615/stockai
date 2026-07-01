"""Futu 数据接入服务层 — raw 落库、日线兼容同步、后续 fallback 入口。"""

import json
import logging

from database import execute, execute_many
from services.futu_client import FutuClient

logger = logging.getLogger(__name__)


def _upsert_raw_quote(row: dict) -> None:
    execute(
        """INSERT INTO futu_raw_quote
           (code, market, symbol, price, open_price, high_price, low_price,
            prev_close, change, change_pct, volume, turnover, quote_time,
            source, raw_payload)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["code"],
            row["market"],
            row["symbol"],
            row.get("price"),
            row.get("open_price"),
            row.get("high_price"),
            row.get("low_price"),
            row.get("prev_close"),
            row.get("change"),
            row.get("change_pct"),
            row.get("volume"),
            row.get("turnover"),
            row.get("quote_time"),
            row.get("source", "futu"),
            row.get("raw_payload", "{}"),
        ),
    )



def _build_raw_kline_statements(payload: dict) -> list[tuple[str, tuple]]:
    statements: list[tuple[str, tuple]] = []
    raw_rows = payload.get("raw_rows", [])
    turnovers = payload.get("turnovers", [])

    for idx, trade_date in enumerate(payload["dates"]):
        sql = """INSERT INTO futu_raw_kline
                 (code, market, symbol, interval, bar_time, open, high, low,
                  close, volume, turnover, adjust_type, source, raw_payload, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                 ON CONFLICT(symbol, interval, bar_time, adjust_type)
                 DO UPDATE SET
                     open=excluded.open,
                     high=excluded.high,
                     low=excluded.low,
                     close=excluded.close,
                     volume=excluded.volume,
                     turnover=excluded.turnover,
                     raw_payload=excluded.raw_payload,
                     updated_at=datetime('now','localtime')"""
        raw_payload = raw_rows[idx] if idx < len(raw_rows) else {}
        turnover = turnovers[idx] if idx < len(turnovers) else None
        params = (
            payload["code"],
            payload["market"],
            payload["symbol"],
            payload["interval"],
            trade_date,
            payload["opens"][idx],
            payload["highs"][idx],
            payload["lows"][idx],
            payload["closes"][idx],
            payload["volumes"][idx],
            turnover,
            payload.get("adjust_type", "qfq"),
            payload.get("source", "futu"),
            json.dumps(raw_payload, ensure_ascii=False),
        )
        statements.append((sql, params))
    return statements



def _build_historical_sync_statements(payload: dict) -> list[tuple[str, tuple]]:
    statements: list[tuple[str, tuple]] = []
    for idx, trade_date in enumerate(payload["dates"]):
        sql = """INSERT INTO historical_kline
                 (stock_code, trade_date, open, high, low, close, volume)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(stock_code, trade_date)
                 DO UPDATE SET
                     open=excluded.open,
                     high=excluded.high,
                     low=excluded.low,
                     close=excluded.close,
                     volume=excluded.volume"""
        params = (
            payload["code"],
            trade_date,
            payload["opens"][idx],
            payload["highs"][idx],
            payload["lows"][idx],
            payload["closes"][idx],
            payload["volumes"][idx],
        )
        statements.append((sql, params))
    return statements



def sync_quote(code: str, client: FutuClient | None = None) -> dict:
    client = client or FutuClient()
    rows = client.get_snapshot([code])
    row = rows[0]
    if "error" in row:
        return row
    _upsert_raw_quote(row)
    return row



def sync_minute_kline(code: str, count: int = 240, client: FutuClient | None = None) -> dict:
    client = client or FutuClient()
    payload = client.get_kline(code, "1m", count=count)
    if "error" in payload:
        return payload
    execute_many(_build_raw_kline_statements(payload))
    return payload



def sync_daily_kline(code: str, count: int = 200, client: FutuClient | None = None) -> dict:
    client = client or FutuClient()
    payload = client.get_kline(code, "1d", count=count)
    if "error" in payload:
        return payload
    statements = _build_raw_kline_statements(payload) + _build_historical_sync_statements(payload)
    execute_many(statements)
    return payload
