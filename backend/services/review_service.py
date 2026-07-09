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


# ═══════════════════════════════════════════════════════════════
#  全自动月报 — AI 生成结构化月度投资报告
# ═══════════════════════════════════════════════════════════════

def generate_monthly_report(year_month: str, user_id: int = 1) -> dict:
    """生成指定月份的 AI 投资月报

    流程:
      1. 聚合当月交易数据
      2. 读取交易记忆反思
      3. 按策略维度统计
      4. 调 AI 生成结构化月报
      5. 存储到 review_reports 表

    Args:
        year_month: "2026-07" 格式
        user_id: 用户 ID

    Returns:
        {
            "year_month": "2026-07",
            "generated_at": "2026-07-08T...",
            "summary": {...},        # 总成绩单
            "top_gainers": [...],    # 赚最多3笔
            "top_losers": [...],     # 亏最多3笔
            "strategy_ranking": [...], # 策略PK
            "ai_advice": "...",      # AI改进建议
            "raw_report": "...",     # AI完整输出
        }
    """
    import json
    from datetime import datetime, timezone
    from database import query_all, query_one, execute

    # 检查是否有缓存报告
    existing = query_one(
        """SELECT ai_response FROM review_reports
           WHERE user_id = ? AND report_type = 'monthly'
           AND period_start = ? LIMIT 1""",
        (user_id, f"{year_month}-01"),
    )
    if existing and existing.get("ai_response"):
        try:
            cached = json.loads(existing["ai_response"])
            if cached.get("summary"):
                cached["cached"] = True
                return cached
        except Exception:
            pass

    # 1. 聚合交易数据
    agg = aggregate_transactions(user_id)

    if agg["total_trades"] == 0:
        return {
            "year_month": year_month,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"total_trades": 0, "message": "本月无已结算交易"},
            "top_gainers": [], "top_losers": [],
            "strategy_ranking": [], "ai_advice": "",
        }

    # 2. 读取交易记忆
    from services.trading_memory import TradingMemoryLog
    mem = TradingMemoryLog()
    all_entries = mem.load_entries()
    # 过滤当月已结算条目
    month_prefix = year_month
    month_entries = [
        e for e in all_entries
        if not e.get("pending") and e.get("date", "").startswith(month_prefix)
    ]

    # 3. 按策略维度统计
    strategy_stats: dict[str, dict] = {}
    for e in month_entries:
        sid = e.get("strategy_id", "") or "unknown"
        if sid not in strategy_stats:
            strategy_stats[sid] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        ss = strategy_stats[sid]
        ss["trades"] += 1
        try:
            pnl = float(e.get("raw", 0) or 0)
            if pnl > 0:
                ss["wins"] += 1
            ss["total_pnl"] += pnl
        except (ValueError, TypeError):
            pass

    strategy_ranking = sorted(
        [
            {
                "strategy_id": sid,
                "trades": s["trades"],
                "win_rate": round(s["wins"] / s["trades"] * 100, 1) if s["trades"] > 0 else 0,
                "total_pnl": round(s["total_pnl"], 2),
            }
            for sid, s in strategy_stats.items()
        ],
        key=lambda x: x["total_pnl"],
        reverse=True,
    )

    # 4. 构建 prompt 调 AI
    top3_win = agg["top_gainers"][:3]
    top3_loss = agg["top_losers"][:3]

    trades_text = "\n".join([
        f"{'赚' if t['pnl'] > 0 else '亏'}: {t['stock_code']} {t.get('stock_name','')} "
        f"¥{t['pnl']:.0f}, 持有{t.get('hold_days','?')}天"
        for t in (top3_win + top3_loss)
    ])

    strategy_text = "\n".join([
        f"{s['strategy_id']}: {s['trades']}笔 胜率{s['win_rate']}% 总盈亏{s['total_pnl']:+.0f}"
        for s in strategy_ranking
    ]) if strategy_ranking else "无按策略分类数据"

    reflections_text = "\n".join([
        f"[{e['date']}] {e['code']} {e.get('direction','')}: {e.get('reflection','')[:100]}"
        for e in month_entries[:10]
    ]) if month_entries else "无反思记录"

    prompt = f"""你是专业的 A 股投资教练。请根据以下月度交易数据，生成一份简洁的月度投资报告。

## 本月成绩
- 总交易: {agg['total_trades']}笔, 胜率: {agg['win_rate']}%, 盈亏比: {(agg['total_pnl'] / max(abs(sum(t['pnl'] for t in top3_loss), 1), 1)):.1f}
- 总盈亏: ¥{agg['total_pnl']:+.0f}, 均持有时长: {agg['avg_hold_days']}天

## 赚最多/亏最多
{trades_text}

## 策略表现
{strategy_text}

## 交易反思
{reflections_text}

请输出 JSON 格式（不要markdown code block）:
{{
  "one_liner": "一句话总结本月（30字内）",
  "good": ["做得好的1-3点"],
  "bad": ["需要改进的1-3点"],
  "advice": "下月改进建议（100字内）",
  "score": 1-10
}}"""

    # 5. 调 AI
    ai_response_raw = ""
    ai_structured = {}
    try:
        from services.ai_service import ai_chat
        raw = ai_chat(prompt, function="review",
                       system_prompt="你是专业的 A 股投资教练。请简洁有力地给出月度总结。只输出JSON。")
        # asyncio event loop 桥接
        import asyncio
        raw = asyncio.new_event_loop().run_until_complete(
            ai_chat(prompt, function="review",
                     system_prompt="你是专业的 A 股投资教练。只输出JSON，不要markdown代码块。")
        )
        ai_response_raw = raw.strip() if raw else ""
        # 尝试解析 JSON
        if ai_response_raw:
            # 去除可能的 markdown 代码块包裹
            clean = ai_response_raw
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:]) if len(lines) > 1 else clean
                if clean.endswith("```"):
                    clean = clean[:-3]
            ai_structured = json.loads(clean)
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("monthly_report: AI call or parse failed", exc_info=True)
        ai_structured = {
            "one_liner": f"{year_month}月共{agg['total_trades']}笔交易，盈亏¥{agg['total_pnl']:+.0f}",
            "good": [], "bad": [], "advice": "", "score": 5,
        }

    # 6. 存储
    report_data = {
        "year_month": year_month,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_trades": agg["total_trades"],
            "win_rate": agg["win_rate"],
            "total_pnl": agg["total_pnl"],
            "avg_hold_days": agg["avg_hold_days"],
            "net_pnl": agg["total_pnl"],
        },
        "top_gainers": [
            {"code": t["stock_code"], "name": t.get("stock_name", ""),
             "pnl": t["pnl"], "hold_days": t.get("hold_days", 0)}
            for t in top3_win
        ],
        "top_losers": [
            {"code": t["stock_code"], "name": t.get("stock_name", ""),
             "pnl": t["pnl"], "hold_days": t.get("hold_days", 0)}
            for t in top3_loss
        ],
        "strategy_ranking": strategy_ranking,
        "ai_advice": ai_structured.get("advice", ""),
        "ai_score": ai_structured.get("score", 5),
        "one_liner": ai_structured.get("one_liner", ""),
        "ai_good": ai_structured.get("good", []),
        "ai_bad": ai_structured.get("bad", []),
        "raw_report": ai_response_raw,
    }

    # 幂等写入
    execute(
        """INSERT OR REPLACE INTO review_reports
           (user_id, report_type, period_start, period_end, transactions_count,
            ai_response, summary, score_data, created_at)
           VALUES (?, 'monthly', ?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
        (
            user_id,
            f"{year_month}-01",
            f"{year_month}-31",
            agg["total_trades"],
            json.dumps(report_data, ensure_ascii=False),
            ai_structured.get("one_liner", ""),
            json.dumps({"score": ai_structured.get("score", 5)}, ensure_ascii=False),
        ),
    )

    return report_data


def compare_monthly_reports(current_month: str, user_id: int = 1) -> dict:
    """对比当前月与上月的交易表现

    Returns:
        {
            "current_month": "2026-07", "previous_month": "2026-06",
            "current": {...}, "previous": {...},
            "delta": {win_rate, total_pnl, num_trades, sharpe},
            "trend": "improving" | "declining" | "stable",
            "diagnosis": "本月胜率较上月提升5%，但交易次数减少..."
        }
    """
    from datetime import datetime, timedelta

    # 计算上月
    try:
        dt = datetime.strptime(current_month, "%Y-%m")
    except ValueError:
        return {"error": "月份格式错误，需为 YYYY-MM"}

    prev_dt = dt - timedelta(days=1)
    previous_month = prev_dt.strftime("%Y-%m")

    # 生成或获取两个月报
    current = generate_monthly_report(current_month, user_id)
    previous = generate_monthly_report(previous_month, user_id)

    cs = current.get("summary", {}) or {}
    ps = previous.get("summary", {}) or {}

    # 计算差值
    delta_win = round((cs.get("win_rate", 0) or 0) - (ps.get("win_rate", 0) or 0), 1)
    delta_pnl = round((cs.get("total_pnl", 0) or 0) - (ps.get("total_pnl", 0) or 0), 2)
    delta_trades = (cs.get("total_trades", 0) or 0) - (ps.get("total_trades", 0) or 0)

    # 判定趋势
    if delta_win > 2 and delta_pnl >= 0:
        trend = "improving"
    elif delta_win < -2 or delta_pnl < -500:
        trend = "declining"
    else:
        trend = "stable"

    # 生成诊断
    parts = []
    if delta_win != 0:
        parts.append(f"胜率{'提升' if delta_win > 0 else '下降'}{abs(delta_win):.1f}%")
    if abs(delta_pnl) > 1:
        parts.append(f"净盈亏{'+' if delta_pnl > 0 else ''}¥{delta_pnl:.0f}")
    if delta_trades != 0:
        parts.append(f"交易次数{'增加' if delta_trades > 0 else '减少'}{abs(delta_trades)}笔")

    diagnosis = "，".join(parts) + "。" if parts else "与上月持平。"

    if trend == "improving":
        diagnosis += " 本月表现好于上月，继续保持纪律。"
    elif trend == "declining":
        diagnosis += " 本月表现退步，建议复盘亏损交易的共同原因。"

    return {
        "current_month": current_month,
        "previous_month": previous_month,
        "current": current,
        "previous": previous,
        "delta": {
            "win_rate": delta_win,
            "total_pnl": delta_pnl,
            "num_trades": delta_trades,
        },
        "trend": trend,
        "diagnosis": diagnosis,
    }
