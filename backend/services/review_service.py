"""AI 投资教练 — 复盘报告引擎

数据聚合 -> prompt 构建 -> AI 调用 -> JSON 解析 -> 降级处理
"""
import asyncio
import json
import re
from datetime import datetime as dt

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
            buy_records[t["stock_code"]].append(dict(t))
        elif t["direction"] == "sell":
            sells = buy_records.get(t["stock_code"], [])
            sell_qty = t["quantity"]
            sell_amount = t.get("amount", 0) or t["price"] * sell_qty  # net proceeds (amount = price*qty - fee)
            matched_qty = 0
            matched_buy_amount = 0
            matched_buy = None
            while sells and matched_qty < sell_qty:
                buy = sells[0]
                remaining = sell_qty - matched_qty
                if buy["quantity"] <= remaining:
                    sells.pop(0)
                    matched_buy_amount += buy.get("amount", 0) or buy["price"] * buy["quantity"]  # cost including fee
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

    # Identify top gainers and losers
    sorted_sells = sorted(sell_records, key=lambda x: x["pnl"], reverse=True)
    top_gainers = sorted_sells[:3]
    top_losers = sorted_sells[-3:] if len(sorted_sells) >= 3 else []
    top_losers = sorted(top_losers, key=lambda x: x["pnl"])

    win_count = sum(1 for s in sell_records if s["pnl"] > 0)
    lose_count = sum(1 for s in sell_records if s["pnl"] < 0)
    total_trades = len(trades)
    resolved = win_count + lose_count
    win_rate = round(win_count / resolved * 100, 1) if resolved > 0 else 0
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
    sell_by_id = {s["id"]: s for s in sell_records}
    enriched_transactions = []
    for t in trades:
        enriched = dict(t)
        matching_sell = sell_by_id.get(t["id"])
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


def build_review_prompt(data: dict, quant_context: str = "") -> str:
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

    if data["total_trades"] < 3:
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

### 量化风控指标
{quant_context if quant_context else "暂无量化数据"}

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


def parse_review_response(raw: str) -> dict:
    """Parse AI review response into structured dict, with progressive fallback.

    Uses shared parse_ai_json() for JSON extraction, then normalizes to
    review-specific fields (dimensions/summary/suggestions).
    """
    from services.utils import parse_ai_json

    if not raw or not raw.strip():
        return {
            "dimensions": [],
            "summary": "AI 分析暂不可用，请稍后重试",
            "suggestions": [],
            "error": True,
            "raw": "",
        }

    data = parse_ai_json(raw)

    # If parse failed, return raw fallback
    if data.get("parse_error"):
        return {
            "dimensions": [],
            "summary": "AI 返回格式异常，以下为原始内容",
            "suggestions": [],
            "raw": raw,
        }

    return _normalize_response(data, raw)


def _normalize_response(data: dict, raw_text: str) -> dict:
    """Ensure the parsed response has the expected fields"""
    return {
        "dimensions": data.get("dimensions", []),
        "summary": data.get("summary", ""),
        "suggestions": data.get("suggestions", []),
        "raw": raw_text,
        "error": "error" in data,
    }


def _format_quant_context(qdata: dict) -> str:
    """Format quant risk data into natural language for the AI prompt."""
    if not qdata or qdata.get("error"):
        return ""

    lines = []
    if qdata.get("sharpe") is not None:
        s = qdata["sharpe"]
        level = "优秀（>1）" if s > 1 else "一般（0.5-1）" if s > 0.5 else "偏低（<0.5）"
        lines.append(f"- 夏普比率: {s} — {level}，衡量风险调整后收益")
    if qdata.get("max_drawdown") is not None:
        dd = qdata["max_drawdown"]
        lines.append(f"- 最大回撤: {dd*100:.1f}%")
    if qdata.get("volatility") is not None:
        vol = qdata["volatility"]
        lines.append(f"- 年化波动率: {vol*100:.1f}%")
    if qdata.get("beta") is not None:
        b = qdata["beta"]
        level = "高于市场波动" if b > 1 else "低于市场波动" if b < 1 else "与市场同步"
        lines.append(f"- Beta (vs 沪深300): {b} — {level}")

    # Per-holding risk
    for hr in qdata.get("holdings_risk", [])[:5]:
        risk_items = []
        if hr.get("sharpe") is not None:
            risk_items.append(f"夏普{hr['sharpe']}")
        if hr.get("max_dd") is not None:
            risk_items.append(f"最大回撤{hr['max_dd']*100:.1f}%")
        if hr.get("vol") is not None:
            risk_items.append(f"波动率{hr['vol']*100:.1f}%")
        if risk_items:
            name = hr.get("name") or hr.get("code", "")
            lines.append(f"- {name}: {', '.join(risk_items)}")

    return "\n".join(lines) if lines else ""


async def generate_review_report(
    user_id: int = 1,
    provider: str = "",
    api_key: str = "",
    model: str = "",
) -> dict:
    """Top-level: aggregate → check cold start → prompt → AI call → parse → store

    Returns the parsed report dict. Stores result in review_reports table.
    """
    from services.ai_service import ai_chat

    # Step 1: Aggregate
    data = aggregate_transactions(user_id)

    # Step 2: Cold start check
    if data["total_trades"] < 3:
        return {
            "dimensions": [],
            "summary": f"已有 {data['total_trades']} 笔交易，至少需要 3 笔交易才能生成 AI 复盘报告。继续记录你的交易吧！",
            "suggestions": [],
            "cold_start": True,
            "transactions_count": data["total_trades"],
            "raw": "",
        }

    # Step 3: Build prompt (with quant data injection)
    try:
        from services.quant_service import get_portfolio_risk
        quant_data = get_portfolio_risk(user_id)
        quant_context = _format_quant_context(quant_data)
    except Exception:
        quant_context = ""
    prompt = build_review_prompt(data, quant_context)

    # Step 4: Check if AI is configured
    from services.ai_service import _load_stored_ai_config
    effective_provider = provider
    effective_key = api_key
    effective_model = model
    if not effective_key:
        stored = _load_stored_ai_config()
        # Find first provider with a key
        for p, c in stored.items():
            if isinstance(c, dict) and c.get("api_key"):
                effective_provider = p
                effective_key = c["api_key"]
                effective_model = effective_model or c.get("model", "")
                break
    if not effective_key:
        return {
            "dimensions": [],
            "summary": "未配置 AI API Key。请先在设置页面配置至少一个 AI 供应商的 Key。",
            "suggestions": [],
            "cold_start": True,
            "transactions_count": data["total_trades"],
            "raw": "",
        }

    # Step 5: Call AI with retry + fallback
    raw = ""
    try:
        raw = await asyncio.wait_for(
            ai_chat(
                prompt,
                provider=effective_provider,
                api_key=effective_key,
                model=effective_model,
                system_prompt="你是专业的 A 股投资教练。请严格按 JSON 格式输出分析报告。",
            ),
            timeout=60.0,
        )
    except (asyncio.TimeoutError, ConnectionError, OSError):
        # Retry once on transient errors
        try:
            raw = await asyncio.wait_for(
                ai_chat(
                    prompt,
                    provider=effective_provider,
                    api_key=effective_key,
                    model=effective_model,
                    system_prompt="你是专业的 A 股投资教练。请严格按 JSON 格式输出分析报告。",
                ),
                timeout=60.0,
            )
        except Exception:
            raw = ""
    except Exception:
        raw = ""

    # Step 5: Parse
    report = parse_review_response(raw)
    report["transactions_count"] = data["total_trades"]
    report["cold_start"] = False
    report["total_pnl"] = data["total_pnl"]
    report["win_rate"] = data["win_rate"]
    report["avg_hold_days"] = data["avg_hold_days"]
    report["win_count"] = data["win_count"]
    report["lose_count"] = data["lose_count"]
    dims = report.get("dimensions", [])
    if dims:
        avg_score = round(sum(d.get("score", 0) for d in dims) / len(dims))
    else:
        avg_score = 0
    report["avg_score"] = avg_score

    # Step 6: Store in DB
    try:
        from database import execute
        import json as _json

        execute(
            """INSERT INTO review_reports (user_id, report_type, transactions_count, dimensions, ai_response, summary, score_data)
               VALUES (?, 'daily', ?, ?, ?, ?, ?)""",
            (
                user_id,
                data["total_trades"],
                _json.dumps([d["id"] for d in report.get("dimensions", [])], ensure_ascii=False),
                raw,
                report["summary"],
                _json.dumps(
                    {d["id"]: d.get("score", 0) for d in report.get("dimensions", [])},
                    ensure_ascii=False,
                ),
            ),
        )
    except Exception:
        pass  # Non-critical: report is still returned even if storage fails

    return report
