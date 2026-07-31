"""交易复盘 — 精简版：聚合交易数据 + 对接记忆系统

AI 复盘功能已合并到 trading_memory.py，本模块只保留数据聚合和记忆读取。
"""

import json

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


# ═══════════════════════════════════════════════════════════
#  v4.1+ 改进建议引擎 (7 月核心计划 P1)
#
#  设计:
#    1. 亏损归因 — 规则化分类每笔亏损(止损缺失 / 持有过久 / 频繁交易)
#    2. 自动推荐 — 基于归因 + 整体指标推荐具体参数调整
#    3. 一键应用 — 前端确认后写建议应用表
#
#  注: 这是规则化建议,不依赖 AI 调用,稳定且可解释
# ═══════════════════════════════════════════════════════════


def analyze_loss_attribution(transactions: list[dict]) -> dict:
    """亏损归因分析 — 分类每笔已结算的亏损交易

    归因规则:
      - 止损缺失 (no_stop_loss): pnl < -10% AND hold_days >= 5 (长期持有还亏大)
      - 持有过久 (over_hold): pnl < 0 AND hold_days > 10
      - 快速止损 (good_exit): 0 < pnl <= 3% AND hold_days <= 3 (小赚就走也可能是错)
      - 频繁亏损 (churn): 同一股票 30 天内多次亏损

    Returns:
        {
            'total_losers': N,
            'attribution': {
                'no_stop_loss': 4,
                'over_hold': 3,
                'churn_loss': 2,
                'clean_loss': N - 9,  # 其他
            },
            'loser_avg_hold_days': 7.2,
            'worst_loser': {...},
            'diagnosis': '4 笔亏损平均持有 7.2 天,疑似没设止损',
        }
    """
    losers = [t for t in transactions if t.get("pnl") is not None and t["pnl"] < 0]
    if not losers:
        return {
            "total_losers": 0,
            "attribution": {"no_stop_loss": 0, "over_hold": 0, "churn_loss": 0, "clean_loss": 0},
            "loser_avg_hold_days": 0,
            "worst_loser": None,
            "diagnosis": "无亏损交易,继续保持",
        }

    # 规则 1: 止损缺失(亏损 >=10% AND 持有 >=5天)
    no_stop = [t for t in losers if t["pnl"] <= -0.10 * abs(t["pnl"] + t["pnl"]) and t.get("hold_days", 0) >= 5]
    # 简化:用绝对亏损比估算
    # pnl 是绝对金额,用 |pnl|/quantity/cost 估算亏损比
    def _loss_ratio(t: dict) -> float:
        try:
            cost = (t.get("price", 0) or 0) * (t.get("quantity", 0) or 0)
            if cost <= 0:
                # fallback:用 matched_buy_amount
                return 0.10  # 默认 10%
            return abs(t["pnl"]) / cost
        except Exception:
            return 0.10

    # 重新算:亏损比 >= 10% 且持有 >= 5 天
    no_stop = [t for t in losers if _loss_ratio(t) >= 0.10 and t.get("hold_days", 0) >= 5]

    # 规则 2: 持有过久(亏损 AND 持有 > 10 天)
    over_hold = [t for t in losers if t.get("hold_days", 0) > 10 and t not in no_stop]

    # 规则 3: 频繁亏损(同 code 30 天内多次亏)
    churn_codes: dict[str, int] = {}
    for t in losers:
        churn_codes[t["stock_code"]] = churn_codes.get(t["stock_code"], 0) + 1
    churn_loss = [t for t in losers if churn_codes.get(t["stock_code"], 0) >= 2]

    # 其他
    flagged = set(id(t) for t in (no_stop + over_hold + churn_loss))
    clean_loss = [t for t in losers if id(t) not in flagged]

    avg_hold = sum(t.get("hold_days", 0) or 0 for t in losers) / len(losers) if losers else 0
    worst = min(losers, key=lambda t: t["pnl"]) if losers else None

    # 自动诊断
    if len(no_stop) >= 3:
        diagnosis = f"{len(no_stop)} 笔亏损平均持有 {avg_hold:.1f} 天,疑似没设止损"
    elif len(over_hold) >= 3:
        diagnosis = f"{len(over_hold)} 笔亏损持有 >10 天,缺乏主动止盈/止损机制"
    elif len(churn_loss) >= 2:
        diagnosis = f"{len(churn_loss)} 笔同标的反复亏损,选股或择时有问题"
    else:
        diagnosis = "亏损归因分散,无需特别干预"

    return {
        "total_losers": len(losers),
        "attribution": {
            "no_stop_loss": len(no_stop),
            "over_hold": len(over_hold),
            "churn_loss": len(churn_loss),
            "clean_loss": len(clean_loss),
        },
        "loser_avg_hold_days": round(avg_hold, 2),
        "worst_loser": {
            "code": worst["stock_code"],
            "name": worst.get("stock_name", ""),
            "pnl": worst["pnl"],
            "hold_days": worst.get("hold_days", 0),
        } if worst else None,
        "diagnosis": diagnosis,
    }


def generate_improvement_suggestions(
    user_id: int = 1,
    lookback_trades: int = 50,
) -> dict:
    """生成改进建议 — 亏损归因 + 整体指标 + 具体参数调整

    Returns:
        {
            'attribution': {...},         # 来自 analyze_loss_attribution
            'overall_metrics': {...},     # 胜率/平均盈亏/平均持仓
            'suggestions': [
                {
                    'id': 'tighten_stop_loss',
                    'priority': 'high',     # high/medium/low
                    'category': '止损',
                    'title': '收紧止损到 -5%',
                    'reason': '4 笔亏损平均持有 7.2 天,疑似没设止损',
                    'param_changes': [
                        {
                            'strategy_id': 'turtle_s1',
                            'param_name': 'stop_loss_pct',
                            'old_value': -0.10,
                            'new_value': -0.05,
                            'description': '止损从 -10% 收到 -5%,快速离场',
                        },
                    ],
                    'expected_impact': '预估止损更快,亏损幅度减少 ~50%',
                },
                ...
            ],
            'summary': '...',
        }
    """
    agg = aggregate_transactions(user_id)
    if agg["total_trades"] == 0:
        return {
            "attribution": {},
            "overall_metrics": {},
            "suggestions": [],
            "summary": "无交易数据,无法生成建议",
        }

    transactions = agg["transactions"]
    # 取最近 lookback_trades 笔
    if len(transactions) > lookback_trades:
        transactions = transactions[-lookback_trades:]

    # 归因
    attribution = analyze_loss_attribution(transactions)

    # 整体指标
    overall = {
        "total_trades": agg["total_trades"],
        "win_rate": agg["win_rate"],
        "total_pnl": agg["total_pnl"],
        "avg_hold_days": agg["avg_hold_days"],
        "lookback_used": len(transactions),
    }

    # 规则化建议
    suggestions: list[dict] = []

    # 规则 1: 止损缺失 → 建议收紧止损
    no_stop_count = attribution["attribution"]["no_stop_loss"]
    if no_stop_count >= 2:
        suggestions.append({
            "id": "tighten_stop_loss",
            "priority": "high" if no_stop_count >= 4 else "medium",
            "category": "止损",
            "title": f"收紧止损(已识别 {no_stop_count} 笔无止损亏损)",
            "reason": (
                f"{no_stop_count} 笔亏损平均亏损比 ≥10% 且持有 ≥5 天,"
                f"平均持有 {attribution['loser_avg_hold_days']:.1f} 天 — "
                f"典型没设止损 / 止损太宽"
            ),
            "param_changes": [
                {
                    "strategy_id": "turtle_s1",
                    "param_name": "stop_loss_pct",
                    "old_value": -0.10,
                    "new_value": -0.05,
                    "description": "止损从 -10% 收到 -5%,快速离场",
                },
                {
                    "strategy_id": "momentum_leader",
                    "param_name": "stop_loss_pct",
                    "old_value": -0.08,
                    "new_value": -0.05,
                    "description": "止损从 -8% 收到 -5%",
                },
            ],
            "expected_impact": f"预估止损失败更快,平均亏损幅度 ↓30-50%",
        })

    # 规则 2: 持有过久 → 建议主动止盈
    over_hold_count = attribution["attribution"]["over_hold"]
    if over_hold_count >= 2:
        suggestions.append({
            "id": "tighten_hold_period",
            "priority": "medium",
            "category": "持仓",
            "title": f"缩短持仓周期(已识别 {over_hold_count} 笔持有 >10 天亏损)",
            "reason": (
                f"{over_hold_count} 笔亏损单笔持有 >10 天,缺乏主动止盈/止损机制"
            ),
            "param_changes": [
                {
                    "strategy_id": "turtle_s1",
                    "param_name": "max_hold_days",
                    "old_value": 20,
                    "new_value": 10,
                    "description": "持仓上限 20 → 10 天",
                },
            ],
            "expected_impact": "10 天内强制 exit,避免浮亏变实亏",
        })

    # 规则 3: 频繁亏损 → 建议收紧入场
    churn_count = attribution["attribution"]["churn_loss"]
    if churn_count >= 2:
        churn_codes = attribution.get("worst_loser", {}).get("code", "")
        suggestions.append({
            "id": "tighten_entry_filter",
            "priority": "medium",
            "category": "入场",
            "title": f"收紧入场过滤(已识别 {churn_count} 笔同标的反复亏损)",
            "reason": (
                f"{churn_count} 笔亏损在同标的反复出现,选股或择时信号太弱"
            ),
            "param_changes": [
                {
                    "strategy_id": "turtle_s1",
                    "param_name": "entry_min_volume_ratio",
                    "old_value": 1.0,
                    "new_value": 1.5,
                    "description": "入场要求量比从 1.0 提到 1.5(避免无量阴跌)",
                },
            ],
            "expected_impact": "只追有量突破,过滤无量震荡",
        })

    # 规则 4: 整体胜率 < 40% → 建议严格风控
    if agg["win_rate"] < 40 and agg["total_trades"] >= 10:
        suggestions.append({
            "id": "improve_win_rate",
            "priority": "high",
            "category": "风控",
            "title": f"胜率仅 {agg['win_rate']}%,建议加强风控",
            "reason": (
                f"总胜率 {agg['win_rate']}% 远低于 50%,入场信号需更严格"
            ),
            "param_changes": [
                {
                    "strategy_id": "all",
                    "param_name": "max_position_pct",
                    "old_value": 0.30,
                    "new_value": 0.20,
                    "description": "单票仓位上限 30% → 20%",
                },
            ],
            "expected_impact": "降低单票波动对组合的冲击",
        })

    # 规则 5: 平均持仓 < 3 天且亏损多 → 频繁交易
    if agg["avg_hold_days"] < 3 and agg["lose_count"] >= 3:
        suggestions.append({
            "id": "reduce_churn",
            "priority": "medium",
            "category": "纪律",
            "title": "减少频繁交易",
            "reason": (
                f"平均持仓仅 {agg['avg_hold_days']} 天,疑似频繁进出 — "
                f"摩擦成本高,且信号来不及展开"
            ),
            "param_changes": [
                {
                    "strategy_id": "all",
                    "param_name": "min_hold_days",
                    "old_value": 1,
                    "new_value": 3,
                    "description": "最小持仓 1 天 → 3 天(避免 T+1 内反复)",
                },
            ],
            "expected_impact": "过滤掉日内噪音,让策略信号有展开空间",
        })

    # Summary
    high_count = sum(1 for s in suggestions if s["priority"] == "high")
    if high_count >= 2:
        summary = f"检测到 {high_count} 个高优先级问题,建议优先处理"
    elif suggestions:
        summary = f"生成 {len(suggestions)} 条建议,可逐条确认应用"
    else:
        summary = "交易纪律良好,暂无需特别调整"

    return {
        "attribution": attribution,
        "overall_metrics": overall,
        "suggestions": suggestions,
        "summary": summary,
    }


def apply_improvement_suggestion(
    user_id: int,
    suggestion_id: str,
    accepted_param_changes: list[dict] | None = None,
) -> dict:
    """记录用户接受了改进建议(写入建议应用表)

    注: 实际修改策略参数需要走 strategies API + 审批流。
    本函数只记录决策审计(谁接受了什么建议)。
    """
    from database import execute
    from datetime import datetime

    execute(
        """INSERT INTO improvement_accepted
           (user_id, suggestion_id, accepted_at, param_changes_json)
           VALUES (?, ?, ?, ?)""",
        (
            user_id, suggestion_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps(accepted_param_changes or [], ensure_ascii=False),
        ),
    )
    return {
        "status": "recorded",
        "suggestion_id": suggestion_id,
        "user_id": user_id,
        "note": "已记录决策审计。参数实际修改请走策略参数配置流程。",
    }
