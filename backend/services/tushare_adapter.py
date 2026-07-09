"""Tushare MCP 数据适配器 — 通过 MCP Server 获取数据写入本地数据库

比 AKShare 稳定，比 Futu 便宜（不消耗 K 线配额）。
通过 MCP 协议调用，绕过 Tushare HTTP API 的积分限制。

用法:
  from services.tushare_adapter import sync_daily_kline, sync_stock_basic

MCP 端点: https://api.tushare.pro/mcp/?token=...
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime

from database import execute, execute_many

logger = logging.getLogger(__name__)

import os
_TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "9d785a25a4987d31bc56b2329dd7894dd31c64bfdc74f3f429b32991")
_MCP_URL = f"https://api.tushare.pro/mcp/?token={_TUSHARE_TOKEN}"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 60) -> list[dict]:
    """调用 Tushare MCP 工具，返回解析后的数据列表"""
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": 1,
    }).encode()
    req = urllib.request.Request(
        _MCP_URL, data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.URLError as e:
        logger.warning(f"tushare_mcp: {tool_name} network error: {e}")
        return []

    # 解析 SSE 响应
    for line in raw.split("\n"):
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            content = data.get("result", {}).get("content", [])
            if content and len(content) > 0:
                text = content[0].get("text", "[]")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return []
    return []


def sync_stock_basic() -> dict:
    """同步全市场股票基本信息到 watchlist（过滤主板+非ST+价格合理）

    通过 MCP stock_basic 获取 >= 获取后通过 daily 拉价格过滤。

    Returns:
        {"added": int, "total": int, "error": str | None}
    """
    items = _call_mcp("stock_basic", {
        "exchange": "", "list_status": "L",
        "fields": "ts_code,name,industry,list_date",
    })
    if not items:
        return {"added": 0, "total": 0, "error": "stock_basic 返回空"}

    added = 0
    for item in items:
        ts_code = item.get("ts_code", "")  # 000001.SZ
        if "." not in ts_code:
            continue
        code = ts_code.split(".")[0]
        name = item.get("name", "")

        # 过滤：只要主板 + 非ST
        from services.screener_service import detect_board
        board = detect_board(code)
        if board not in ("main_sh", "main_sz"):
            continue
        if "ST" in (name or "").upper():
            continue

        market = "SH" if code.startswith("6") else "SZ"
        industry = item.get("industry", "") or ""

        # 幂等写入 watchlist
        try:
            execute(
                """INSERT OR IGNORE INTO watchlist (user_id, stock_code, stock_name, market, asset_type)
                   VALUES (1, ?, ?, ?, 'stock')""",
                (code, name, market),
            )
            added += 1
        except Exception:
            pass

    return {"added": added, "total": len(items)}


def sync_daily_kline(trade_date: str = "") -> dict:
    """从 Tushare MCP 拉取指定日期的全市场日线并写入 historical_kline

    Args:
        trade_date: YYYYMMDD 格式，空=今天

    Returns:
        {"date": str, "stocks": int, "error": str | None}
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    items = _call_mcp("daily", {
        "trade_date": trade_date,
        "limit": "6000",  # 全市场
    })
    if not items:
        return {"date": trade_date, "stocks": 0, "error": "daily 返回空"}

    saved = 0
    for item in items:
        ts_code = item.get("ts_code", "")
        if "." not in ts_code:
            continue
        code = ts_code.split(".")[0]
        try:
            execute(
                """INSERT OR REPLACE INTO historical_kline
                   (stock_code, trade_date, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    code,
                    trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:],
                    item.get("open"), item.get("high"), item.get("low"),
                    item.get("close"), int(item.get("vol", 0) or 0),
                ),
            )
            saved += 1
        except Exception:
            pass

    return {"date": trade_date, "stocks": saved}


def sync_daily_basic(trade_date: str = "") -> dict:
    """从 Tushare MCP 拉取每日基本面指标（PE/PB/市值/ROE）写入 local_fundamentals"""
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    items = _call_mcp("daily_basic", {
        "ts_code": "",
        "trade_date": trade_date,
        "fields": ["ts_code","trade_date","pe_ttm","pb","total_mv","turnover_rate","dv_ttm"],
    })
    if not items:
        return {"date": trade_date, "stocks": 0, "error": "daily_basic 返回空"}

    dated = trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:]
    saved = 0
    for item in items:
        ts_code = item.get("ts_code", "")
        if "." not in ts_code:
            continue
        code = ts_code.split(".")[0]
        try:
            execute(
                """INSERT OR REPLACE INTO local_fundamentals
                   (stock_code, trade_date, pe_ttm, pb, market_cap, turnover_rate, eps, roe, dividend_yield, source)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, 'tushare')""",
                (
                    code, dated,
                    item.get("pe_ttm"), item.get("pb"),
                    item.get("total_mv"), item.get("turnover_rate"),
                    item.get("roe"), item.get("dv_ttm"),
                ),
            )
            saved += 1
        except Exception:
            pass

    return {"date": trade_date, "stocks": saved}


def get_stock_info(code: str) -> dict | None:
    """查询单只股票基本信息（名称+行业），优先本地缓存，否则调 Tushare

    单只查询不受 1次/小时 频率限制。
    """
    from database import query_one, execute

    # 1. 查本地缓存
    row = query_one("SELECT name, industry, list_date FROM stock_info WHERE stock_code = ?", (code,))
    if row and row.get("name"):
        return {"name": row["name"], "industry": row.get("industry", ""), "code": code}

    # 2. 调 Tushare（单只，无频率限制）
    market = "SH" if code.startswith("6") else "SZ"
    ts_code = f"{code}.{market}"
    items = _call_mcp("stock_basic", {
        "ts_code": ts_code,
        "fields": ["ts_code", "name", "industry", "list_date"],
    })
    if items:
        item = items[0]
        name = item.get("name", "")
        industry = item.get("industry", "") or ""
        # 写入缓存
        try:
            execute(
                "INSERT OR REPLACE INTO stock_info (stock_code, name, industry, list_date) VALUES (?, ?, ?, ?)",
                (code, name, industry, item.get("list_date", "")),
            )
        except Exception:
            pass
        return {"name": name, "industry": industry, "code": code}

    return None


def sync_trade_cal() -> dict:
    """同步交易日历到本地（用于判断交易日）"""
    items = _call_mcp("trade_cal", {
        "exchange": "SSE",
        "start_date": "20250101",
        "end_date": "20261231",
    })
    return {"trading_days": len([i for i in items if i.get("is_open") == 1])}
