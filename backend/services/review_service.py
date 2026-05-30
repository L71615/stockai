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


def build_review_prompt(data: dict) -> str:
    """Build the structured review prompt with embedded JSON schema"""
    holdings_text = "\n".join(
        f"- {h['stock_code']} {h['stock_name']}（{h.get('asset_type','stock')}），"
        f"持仓{h['quantity']}股，成本{h['cost_price']}元"
        for h in data["holdings_summary"]
    ) if data["holdings_summary"] else "暂无持仓"

    gainers_text = "\n".join(
        f"- {g['stock_code']} {g.get('stock_name','')}：盈亏 +{g['pnl']}元，"
        f"持有{g['hold_days']}天"
        for g in data["top_gainers"]
    ) if data["top_gainers"] else "暂无盈利交易"

    losers_text = "\n".join(
        f"- {l['stock_code']} {l.get('stock_name','')}：盈亏 {l['pnl']}元，"
        f"持有{l['hold_days']}天"
        for l in data["top_losers"]
    ) if data["top_losers"] else "暂无亏损交易"

    if data["total_trades"] < 5:
        trades_note = f"（仅 {data['total_trades']} 笔交易，数据不足，分析可能不完整）"
    else:
        trades_note = f"共 {data['total_trades']} 笔交易"

    prompt = f"""你是一位专业的 A 股投资教练。请基于以下用户的交易数据，生成一份结构化的投资复盘报告。

## 用户交易数据
- 总交易笔数：{data['total_trades']} {trades_note}
- 胜率：{data['win_rate']}%（{data['win_count']}胜/{data['lose_count']}负）
- 总盈亏：{data['total_pnl']}元
- 平均持有天数：{data['avg_hold_days']}天

### 当前持仓
{holdings_text}

### 盈利最大的 3 笔
{gainers_text}

### 亏损最大的 3 笔
{losers_text}

## 输出要求

请严格按以下 JSON 结构输出（不要包含 markdown 代码块标记，直接输出 JSON）：

{{
  "dimensions": [
    {{
      "id": "pnl_attribution",
      "title": "盈亏归因",
      "summary": "一句话总结本期盈亏情况和归因（选股/择时/大盘）",
      "detail": "详细分析盈利和亏损的主要原因，对比同期大盘指数表现",
      "score": 0-100 的整数评分
    }},
    {{
      "id": "behavior_pattern",
      "title": "行为模式",
      "summary": "一句话总结交易行为特征（追涨/杀跌/持仓时间/集中度）",
      "detail": "分析追涨杀跌频率、持仓集中度(top 3占比)、平均持有天数是否合理",
      "score": 0-100 的整数评分
    }},
    {{
      "id": "risk_alert",
      "title": "风险提示",
      "summary": "一句话总结当前风险状况",
      "detail": "分析单票仓位是否过重(>30%)、行业集中度、是否满仓/空仓极端状态",
      "score": 0-100 的整数评分
    }}
  ],
  "summary": "总体评估，一段话总结（50-100字）",
  "suggestions": [
    {{
      "text": "具体的改进建议",
      "reasoning": "为什么提出这条建议，基于什么数据或行为模式"
    }}
  ]
}}

请确保：
1. 输出是有效的 JSON（不要 markdown 代码块）
2. 每个维度的 detail 至少 50 字
3. 给出至少 3 条改进建议，每条必须附带 reasoning
4. 建议要具体、可执行，不要泛泛而谈
5. 如果你不知道该说什么，输出 {{"error": "数据不足，无法生成分析"}}"""
    return prompt
