"""交易复盘 — 精简版：聚合交易数据 + 对接记忆系统

AI 复盘功能已合并到 trading_memory.py，本模块只保留数据聚合和记忆读取。
"""

from database import query_all


def aggregate_transactions(user_id: int = 1) -> dict:
    """聚合用户交易数据，计算关键指标（纯数据，不调 AI）"""
    trades = query_all(
        """SELECT t.*, h.cost_price, h.quantity as current_hold
           FROM transactions t
           LEFT JOIN holdings h ON t.stock_code = h.stock_code AND h.user_id = ?
           WHERE t.user_id = ?
           ORDER BY t.traded_at ASC""",
        (user_id, user_id),
    )

    if not trades:
        return {
            "transactions": [],
            "total_trades": 0,
            "win_count": 0,
            "lose_count": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_hold_days": 0,
            "top_gainers": [],
            "top_losers": [],
            "holdings_summary": [],
        }

    # 买卖配对计算 PnL
    buy_records = {}
    sell_records = []

    for t in trades:
        if t["direction"] == "buy":
            buy_records.setdefault(t["stock_code"], []).append(dict(t))
        elif t["direction"] == "sell":
            sells = buy_records.get(t["stock_code"], [])
            sell_qty = t["quantity"]
            sell_amount = t.get("amount", 0) or t["price"] * sell_qty
            matched_qty = 0
            matched_buy_amount = 0
            matched_buy = None
            while sells and matched_qty < sell_qty:
                buy = sells[0]
                remaining = sell_qty - matched_qty
                if buy["quantity"] <= remaining:
                    sells.pop(0)
                    matched_buy_amount += buy.get("amount", 0) or buy["price"] * buy["quantity"]
                    matched_qty += buy["quantity"]
                else:
                    buy["quantity"] -= remaining
                    matched_buy_amount += buy["price"] * remaining
                    matched_qty += remaining
                matched_buy = buy
            if matched_qty > 0:
                pnl = round(sell_amount - matched_buy_amount, 2)
                try:
                    buy_date = dt.strptime(matched_buy["traded_at"], "%Y-%m-%d")
                    sell_date = dt.strptime(t["traded_at"], "%Y-%m-%d")
                    hold_days = (sell_date - buy_date).days
                except Exception:
                    hold_days = 0
                sell_records.append({**t, "pnl": pnl, "hold_days": hold_days})

    from datetime import datetime as dt

    sorted_sells = sorted(sell_records, key=lambda x: x["pnl"], reverse=True)
    top_gainers = sorted_sells[:3]
    top_losers = sorted_sells[-3:] if len(sorted_sells) >= 3 else []
    top_losers = sorted(top_losers, key=lambda x: x["pnl"])

    win_count = sum(1 for s in sell_records if s["pnl"] > 0)
    lose_count = sum(1 for s in sell_records if s["pnl"] < 0)
    resolved = win_count + lose_count
    win_rate = round(win_count / resolved * 100, 1) if resolved > 0 else 0
    total_pnl = sum(s["pnl"] for s in sell_records)
    avg_hold_days = round(sum(s["hold_days"] for s in sell_records) / resolved, 1) if resolved > 0 else 0

    holdings = query_all("SELECT * FROM holdings WHERE user_id = ?", (user_id,))
    holdings_summary = [{
        "stock_code": h["stock_code"],
        "stock_name": h["stock_name"],
        "quantity": h["quantity"],
        "cost_price": h["cost_price"],
        "asset_type": h.get("asset_type", "stock"),
    } for h in holdings]

    enriched_transactions = []
    sell_by_id = {s["id"]: s for s in sell_records}
    for t in trades:
        enriched = dict(t)
        matching_sell = sell_by_id.get(t["id"])
        enriched["pnl"] = matching_sell["pnl"] if matching_sell else 0
        enriched["hold_days"] = matching_sell["hold_days"] if matching_sell else None
        enriched_transactions.append(enriched)

    return {
        "transactions": enriched_transactions,
        "total_trades": resolved,
        "win_count": win_count,
        "lose_count": lose_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_hold_days": avg_hold_days,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "holdings_summary": holdings_summary,
    }


def get_memory_entries(limit: int = 50) -> list[dict]:
    """读取交易记忆日志的解析结果"""
    from services.trading_memory import TradingMemoryLog
    mem = TradingMemoryLog()
    entries = mem.load_entries()
    # 最新在前
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:limit]


def get_memory_stats() -> dict:
    """交易记忆统计摘要"""
    from services.trading_memory import TradingMemoryLog
    mem = TradingMemoryLog()
    all_entries = mem.load_entries()
    resolved = [e for e in all_entries if not e.get("pending")]
    pending = [e for e in all_entries if e.get("pending")]

    # 统计已解析的盈亏
    gains = []
    losses = []
    for e in resolved:
        try:
            raw = float(e.get("raw", 0) or 0)
            if raw > 0:
                gains.append(raw)
            elif raw < 0:
                losses.append(abs(raw))
        except (ValueError, TypeError):
            pass

    return {
        "total_entries": len(all_entries),
        "resolved_count": len(resolved),
        "pending_count": len(pending),
        "total_gain": sum(gains),
        "total_loss": sum(losses),
        "avg_gain": round(sum(gains) / len(gains), 2) if gains else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "net_pnl": sum(gains) - sum(losses),
    }
