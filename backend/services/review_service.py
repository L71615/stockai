"""AI 投资教练 — 复盘报告引擎

数据聚合 -> prompt 构建 -> AI 调用 -> JSON 解析 -> 降级处理
"""
from database import query_all


def aggregate_transactions(user_id: int = 1) -> dict:
    """聚合用户交易数据，计算关键指标"""
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

    # Calculate PnL per stock by matching buy/sell pairs
    buy_records = {}  # stock_code -> [buy transactions]
    sell_records = []  # list of sell transactions with matched buy info

    for t in trades:
        if t["direction"] == "buy":
            if t["stock_code"] not in buy_records:
                buy_records[t["stock_code"]] = []
            buy_records[t["stock_code"]].append(t)
        elif t["direction"] == "sell":
            sells = buy_records.get(t["stock_code"], [])
            if sells:
                buy = sells.pop(0)
                buy_amount = buy["price"] * buy["quantity"]
                sell_amount = t["price"] * t["quantity"]
                pnl = round(sell_amount - buy_amount, 2)
                from datetime import datetime as dt
                try:
                    buy_date = dt.strptime(buy["traded_at"], "%Y-%m-%d")
                    sell_date = dt.strptime(t["traded_at"], "%Y-%m-%d")
                    hold_days = (sell_date - buy_date).days
                except Exception:
                    hold_days = 0
                sell_records.append({**t, "pnl": pnl, "hold_days": hold_days})

    # Identify top gainers and losers
    sorted_sells = sorted(sell_records, key=lambda x: x["pnl"], reverse=True)
    top_gainers = sorted_sells[:3]
    top_losers = sorted_sells[-3:] if len(sorted_sells) >= 3 else []
    top_losers = sorted(top_losers, key=lambda x: x["pnl"])

    win_count = sum(1 for s in sell_records if s["pnl"] > 0)
    lose_count = sum(1 for s in sell_records if s["pnl"] < 0)
    total_trades = len(sell_records)
    win_rate = round(win_count / total_trades * 100, 1) if total_trades > 0 else 0
    total_pnl = sum(s["pnl"] for s in sell_records)
    avg_hold_days = round(sum(s["hold_days"] for s in sell_records) / total_trades, 1) if total_trades > 0 else 0

    # Holdings summary
    holdings = query_all(
        "SELECT * FROM holdings WHERE user_id = ?",
        (user_id,),
    )
    holdings_summary = [{
        "stock_code": h["stock_code"],
        "stock_name": h["stock_name"],
        "quantity": h["quantity"],
        "cost_price": h["cost_price"],
        "asset_type": h.get("asset_type", "stock"),
    } for h in holdings]

    # Enrich transactions with PnL info
    enriched_transactions = []
    for t in trades:
        enriched = dict(t)
        matching_sell = next((s for s in sell_records if s["id"] == t["id"]), None)
        enriched["pnl"] = matching_sell["pnl"] if matching_sell else 0
        enriched["hold_days"] = matching_sell["hold_days"] if matching_sell else None
        enriched_transactions.append(enriched)

    return {
        "transactions": enriched_transactions,
        "total_trades": total_trades,
        "win_count": win_count,
        "lose_count": lose_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_hold_days": avg_hold_days,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "holdings_summary": holdings_summary,
    }
