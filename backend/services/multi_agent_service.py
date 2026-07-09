"""多 Agent 深度分析 — TradingAgents 风格的多空辩论

5 个 Agent，3 轮调用:
  第1轮 (并行): 技术面分析师 + 基本面分析师
  第2轮 (并行): 多头研究员 + 空头研究员 (基于第1轮报告辩论)
  第3轮: 裁判 (审阅辩论，给出最终判断)

用法:
  from services.multi_agent_service import analyze_stock
  result = await analyze_stock("600519")

输出:
  {
    "code": "600519",
    "technical_report": "技术面报告...",
    "fundamentals_report": "基本面报告...",
    "bull_case": "多头论点...",
    "bear_case": "空头论点...",
    "verdict": "买入/持有/卖出",
    "confidence": 0.75,
    "reasoning": "最终判断理由...",
  }
"""

import asyncio
import logging
from typing import Any

from services.ai_service import ai_chat, get_default_provider

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  System Prompts
# ═══════════════════════════════════════════════════════════════

TECHNICAL_SYSTEM = """你是资深 A 股技术分析师，专注价格行为和量化因子分析。
分析框架:
1. K 线趋势（均线排列、支撑阻力、形态）
2. 技术指标信号（RSI/MACD/KDJ/布林带）
3. 量价配合关系
4. 55 因子评分（关注动量/波动率/量价/情绪类因子）
5. 海龟交易法信号（S1/S2 通道突破）

输出要求:
- 给出明确的技术面判断（看多/中性/看空）
- 列出 3-5 个关键信号，每个附具体数值
- 控制在 500 字以内
- 用中文"""

FUNDAMENTALS_SYSTEM = """你是资深 A 股基本面分析师，专注公司质地和估值分析。
分析框架:
1. 估值水平（PE/PB 相对历史和行业）
2. 盈利能力（ROE/毛利率/净利率）
3. 成长性（营收增速/利润增速）
4. 财务健康度（资产负债率/现金流）
5. 分红回报（股息率）

输出要求:
- 给出明确的基本面判断（低估/合理/高估）
- 列出 3-5 个关键指标，每个附具体数值
- 指出 1-2 个潜在风险点
- 控制在 500 字以内
- 用中文"""

BULL_SYSTEM = """你是 A 股多头研究员。你的任务是基于技术面和基本面分析报告，构建看涨论点。
分析框架:
1. 找出两份报告中所有正面信号
2. 将这些信号串联成连贯的看涨逻辑
3. 提出 3 个核心看涨理由
4. 估算目标价和上涨空间（用报告中给出的数据）
5. 说明什么情况下这个看涨逻辑会成立

输出要求:
- 必须有具体数据支撑，不能空泛
- 标注每个理由的置信度（高/中/低）
- 控制在 400 字以内
- 用中文"""

BEAR_SYSTEM = """你是 A 股空头研究员。你的任务是基于技术面和基本面分析报告，构建看跌论点。
分析框架:
1. 找出两份报告中所有风险信号和负面因素
2. 将这些信号串联成连贯的看跌逻辑
3. 提出 3 个核心看跌理由
4. 估算下行风险和潜在亏损空间
5. 指出什么情况下应该止损

输出要求:
- 必须有具体数据支撑，不能空泛
- 标注每个理由的置信度（高/中/低）
- 控制在 400 字以内
- 用中文"""

JUDGE_SYSTEM = """你是资深 A 股投资经理。请审阅以下多空辩论，给出最终判断。

你需要:
1. 比较多空双方的论据质量和数据支撑
2. 判断哪一方更有说服力
3. 给出明确的投资建议

输出格式（严格 JSON）:
{
  "verdict": "买入" | "持有" | "卖出",
  "confidence": 0.0-1.0,
  "key_reasons": ["理由1", "理由2", "理由3"],
  "risk_warning": "主要风险提示",
  "suggested_hold_days": 建议持仓天数,
  "stop_loss_pct": 建议止损百分比
}

要求:
- verdict 必须是 "买入"、"持有"、"卖出" 之一
- confidence 0-1，0.7 以上为高置信度
- 用中文"""


# ═══════════════════════════════════════════════════════════════
#  核心编排
# ═══════════════════════════════════════════════════════════════

async def analyze_stock(
    code: str,
    provider: str = "",
    api_key: str = "",
    model: str = "",
    strategy_id: str = "",
) -> dict:
    """对单只股票运行多 Agent 深度分析

    Args:
        code: 股票代码
        provider/api_key/model: AI 供应商配置
        strategy_id: 可选，触发分析的策略 ID，用于注入历史交易记忆

    Returns:
        {code, technical_report, fundamentals_report, bull_case,
         bear_case, verdict, confidence, reasoning, key_reasons,
         risk_warning, suggested_hold_days, stop_loss_pct}
    """
    # ── 获取数据 ──
    stock_info = _gather_stock_data(code)
    if "error" in stock_info:
        return {"code": code, "error": stock_info["error"]}

    # ── 第 1 轮：技术面 + 基本面 并行 ──
    tech_prompt = _build_technical_prompt(code, stock_info)
    fund_prompt = _build_fundamentals_prompt(code, stock_info)

    tech_task = ai_chat(
        tech_prompt,
        system_prompt=TECHNICAL_SYSTEM,
        provider=provider, api_key=api_key, model=model,
        function="explain",
    )
    fund_task = ai_chat(
        fund_prompt,
        system_prompt=FUNDAMENTALS_SYSTEM,
        provider=provider, api_key=api_key, model=model,
        function="explain",
    )

    try:
        tech_report, fund_report = await asyncio.gather(tech_task, fund_task)
    except Exception as e:
        return {"code": code, "error": f"AI 调用异常: {e}"}

    tech_report = (tech_report or "").strip()
    fund_report = (fund_report or "").strip()

    # 检查错误格式（ai_chat 返回 "（错误描述）" 而非抛异常）
    if tech_report.startswith("（") and tech_report.endswith("）"):
        return {"code": code, "error": f"技术面分析失败: {tech_report[1:-1]}"}
    if fund_report.startswith("（") and fund_report.endswith("）"):
        return {"code": code, "error": f"基本面分析失败: {fund_report[1:-1]}"}
    if not tech_report or not fund_report:
        return {"code": code, "error": "AI 分析返回为空，请检查 API Key 配置"}

    # ── 第 2 轮：多头 + 空头 并行 ──
    debate_context = f"""## 技术面分析报告
{tech_report}

## 基本面分析报告
{fund_report}"""

    bull_task = ai_chat(
        debate_context + "\n\n请基于以上两份报告，构建看涨论点。",
        system_prompt=BULL_SYSTEM,
        provider=provider, api_key=api_key, model=model,
        function="explain",
    )
    bear_task = ai_chat(
        debate_context + "\n\n请基于以上两份报告，构建看跌论点。",
        system_prompt=BEAR_SYSTEM,
        provider=provider, api_key=api_key, model=model,
        function="explain",
    )

    try:
        bull_case, bear_case = await asyncio.gather(bull_task, bear_task)
    except Exception as e:
        return {"code": code, "error": f"辩论阶段 AI 调用异常: {e}"}
    bull_case = (bull_case or "").strip()
    bear_case = (bear_case or "").strip()

    # ── 第 3 轮：裁判 ──
    # 注入交易记忆上下文
    memory_context = ""
    try:
        from services.trading_memory import TradingMemoryLog
        mem = TradingMemoryLog()
        # 获取同股票历史交易教训
        past = mem.get_past_context(code, n_same=3, n_cross=2)
        if past:
            memory_context += f"\n\n## 历史交易参考（你的真实交易记录）\n{past}"
        # 获取策略维度历史表现
        if strategy_id:
            strat_ctx = mem.get_strategy_context(strategy_id, code=code, n=3)
            if strat_ctx:
                memory_context += f"\n\n{strat_ctx}"
    except Exception:
        pass  # 记忆注入失败不影响主流程

    judge_prompt = f"""## 股票: {code} {stock_info.get('name', '')}

## 技术面报告
{tech_report}

## 基本面报告
{fund_report}

## 多头论点
{bull_case}

## 空头论点
{bear_case}
{memory_context}

请给出最终判断。"""

    judge_raw = await ai_chat(
        judge_prompt,
        system_prompt=JUDGE_SYSTEM,
        provider=provider, api_key=api_key, model=model,
        function="explain",
    )

    verdict_data = _parse_judge_response(judge_raw) if judge_raw else {}

    # ── 组装结果 ──
    return {
        "code": code,
        "name": stock_info.get("name", ""),
        "price": stock_info.get("price"),
        "technical_report": tech_report,
        "fundamentals_report": fund_report,
        "bull_case": bull_case,
        "bear_case": bear_case,
        "verdict": verdict_data.get("verdict", "持有"),
        "confidence": verdict_data.get("confidence", 0.5),
        "key_reasons": verdict_data.get("key_reasons", []),
        "risk_warning": verdict_data.get("risk_warning", ""),
        "suggested_hold_days": verdict_data.get("suggested_hold_days"),
        "stop_loss_pct": verdict_data.get("stop_loss_pct"),
    }


# ═══════════════════════════════════════════════════════════════
#  数据收集
# ═══════════════════════════════════════════════════════════════

def _gather_stock_data(code: str) -> dict:
    """收集分析所需数据——优先本地 historical_kline，仅基本面调外部 API"""
    try:
        from database import query_all
        from services.technical import calc_ma, calc_rsi, calc_macd

        # ── 从本地 historical_kline 读 K 线（零外部请求）──
        rows = query_all(
            """SELECT trade_date, open, high, low, close, volume
               FROM historical_kline
               WHERE stock_code = ? AND trade_date >= date('now','-180 days')
               ORDER BY trade_date ASC""",
            (code,),
        )
        if not rows or len(rows) < 60:
            # 回退到外部 K 线
            from services.technical import fetch_kline
            from services.utils import get_market
            kline = fetch_kline(code, get_market(code), days=120)
            if "error" in kline:
                return {"error": f"无法获取 K 线数据: {kline['error']}"}
            closes = kline.get("closes", [])
            highs = kline.get("highs", [])
            lows = kline.get("lows", [])
            volumes = kline.get("volumes", [])
        else:
            closes = [float(r["close"]) for r in rows if r["close"] is not None]
            highs = [float(r["high"]) for r in rows if r["high"] is not None]
            lows = [float(r["low"]) for r in rows if r["low"] is not None]
            volumes = [float(r["volume"]) for r in rows if r["volume"] is not None]

        if len(closes) < 60:
            return {"error": "K 线数据不足（需至少 60 天）"}

        # ── 技术指标计算（纯本地 CPU，不需要网络）──
        price = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else price
        change_pct = round((price - prev) / prev * 100, 2) if prev else 0

        ma = calc_ma(closes, [5, 10, 20, 60])
        rsi = calc_rsi(closes, 14)
        macd = calc_macd(closes)
        atr = _calc_atr(highs, lows, closes, 20)
        turtle = _calc_turtle(highs, lows, closes)

        vol_ratio = 1.0
        if volumes and len(volumes) >= 20:
            valid = [v for v in volumes[-21:-1] if v is not None]
            vm = sum(valid) / len(valid) if valid else 0
            vol_ratio = round(volumes[-1] / vm, 2) if vm > 0 and volumes[-1] is not None else 1.0

        ret_5d = round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None
        ret_20d = round((closes[-1] / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None

        # ── 股票名称：从本地持仓/自选股表获取 ──
        name = ""
        try:
            nr = query_all("SELECT stock_name FROM holdings WHERE stock_code = ? LIMIT 1", (code,))
            if nr and nr[0].get("stock_name"):
                name = nr[0]["stock_name"]
        except Exception:
            pass
        if not name:
            try:
                wr = query_all("SELECT stock_name FROM watchlist WHERE stock_code = ? LIMIT 1", (code,))
                if wr and wr[0].get("stock_name"):
                    name = wr[0]["stock_name"]
            except Exception:
                pass

        # ── 基本面（仅这里调外部 API，AKShare 通常 <1s）──
        fundamentals = {}
        try:
            from services.vendor_router import route
            fundamentals = route("get_fundamentals", code=code)
        except Exception:
            pass

        return {
            "name": name or code,
            "price": price,
            "change_pct": change_pct,
            "ma5": _latest_ma(ma.get("MA5", [])),
            "ma10": _latest_ma(ma.get("MA10", [])),
            "ma20": _latest_ma(ma.get("MA20", [])),
            "ma60": _latest_ma(ma.get("MA60", [])),
            "rsi_14": _latest_ma(rsi),
            "macd_dif": _latest_ma(macd.get("DIF", [])),
            "macd_dea": _latest_ma(macd.get("DEA", [])),
            "macd_bar": _latest_ma(macd.get("MACD", [])),
            "atr_20": atr,
            "vol_ratio": vol_ratio,
            "ret_5d": ret_5d, "ret_20d": ret_20d,
            "turtle_s1_entry": turtle.get("s1_entry"),
            "turtle_s2_entry": turtle.get("s2_entry"),
            "turtle_atr": turtle.get("atr"),
            "turtle_score": turtle.get("score"),
            "pe": fundamentals.get("pe"), "pb": fundamentals.get("pb"),
            "roe": fundamentals.get("roe"), "eps": fundamentals.get("eps"),
            "market_cap_billion": fundamentals.get("market_cap_billion"),
            "dividend_yield": fundamentals.get("dividend"),
            "industry": fundamentals.get("industry", ""),
            "debt_ratio": fundamentals.get("debt_ratio"),
            "gross_margin": fundamentals.get("gross_margin"),
            "revenue_growth": fundamentals.get("revenue_growth"),
        }
    except Exception as e:
        logger.warning("multi_agent: data gather failed for %s: %s", code, e)
        return {"error": f"数据获取失败: {e}"}


# ═══════════════════════════════════════════════════════════════
#  Prompt 构建
# ═══════════════════════════════════════════════════════════════

def _build_technical_prompt(code: str, d: dict) -> str:
    return f"""请分析 {code} {d.get('name','')} 的技术面。

基础数据:
- 最新价: {d['price']} 元, 涨跌幅: {d.get('change_pct','?')}%
- MA5={d.get('ma5')}, MA10={d.get('ma10')}, MA20={d.get('ma20')}, MA60={d.get('ma60')}
- RSI(14)={d.get('rsi_14')}
- MACD: DIF={d.get('macd_dif')}, DEA={d.get('macd_dea')}, BAR={d.get('macd_bar')}
- ATR(20)={d.get('atr_20')}, 量比={d.get('vol_ratio')}
- 5日动量={d.get('ret_5d')}%, 20日动量={d.get('ret_20d')}%

海龟通道:
- S1入场(20日高点)={d.get('turtle_s1_entry')}, S2入场(55日高点)={d.get('turtle_s2_entry')}
- ATR(N)={d.get('turtle_atr')}, 综合评分={d.get('turtle_score')}/100"""


def _build_fundamentals_prompt(code: str, d: dict) -> str:
    pe_str = f"{d['pe']:.1f}" if d.get('pe') else "无数据"
    pb_str = f"{d['pb']:.3f}" if d.get('pb') else "无数据"
    return f"""请分析 {code} {d.get('name','')} 的基本面。

基础数据 (TTM):
- PE={pe_str}, PB={pb_str}
- ROE={d.get('roe','无数据')}%, EPS={d.get('eps','无数据')}元
- 市值={d.get('market_cap_billion','无数据')}亿元
- 股息率={d.get('dividend_yield','无数据')}%
- 行业={d.get('industry','未知')}
- 资产负债率={d.get('debt_ratio','无数据')}%
- 毛利率={d.get('gross_margin','无数据')}%
- 营收增速={d.get('revenue_growth','无数据')}%"""


# ═══════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════

def _latest_ma(data: list) -> float | None:
    valid = [v for v in data if v is not None]
    return round(valid[-1], 2) if valid else None


def _calc_atr(highs, lows, closes, period=20):
    if len(closes) < period + 1:
        return None
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
           for i in range(1, len(closes))]
    return round(sum(trs[-period:]) / period, 4) if len(trs) >= period else None


def _calc_turtle(highs, lows, closes):
    n = len(closes)
    if n < 60:
        return {"error": "K线不足60天", "score": 0}
    price = closes[-1]
    s1e = round(max(highs[-21:-1]), 2) if n >= 21 else None
    s2e = round(max(highs[-56:-1]), 2) if n >= 56 else None
    atr_val = _calc_atr(highs, lows, closes, 20)
    score = 0
    if s1e and price > s1e:
        score += 30
    elif s1e and price > s1e * 0.97:
        score += 15
    if s2e and price > s2e:
        score += 25
    elif s2e and price > s2e * 0.95:
        score += 12
    if atr_val and price > 0:
        vol_r = atr_val / price * 100
        if 1.5 <= vol_r <= 5:
            score += 20
    return {"s1_entry": s1e, "s2_entry": s2e, "atr": atr_val, "score": min(100, score)}


def _parse_judge_response(raw: str) -> dict:
    """从 LLM 输出中提取 JSON 判断"""
    import re
    import json as _json
    # 尝试直接解析
    try:
        data = _json.loads(raw)
        return data
    except (_json.JSONDecodeError, TypeError):
        pass
    # 尝试提取代码块中的 JSON
    m = re.search(r'\{[^{}]*"verdict"[^{}]*\}', raw, re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(0))
        except (_json.JSONDecodeError, TypeError):
            pass
    # 回退：从文本推断
    result = {"verdict": "持有", "confidence": 0.5, "key_reasons": [], "risk_warning": ""}
    if "买入" in raw:
        result["verdict"] = "买入"
        result["confidence"] = 0.6
    elif "卖出" in raw:
        result["verdict"] = "卖出"
        result["confidence"] = 0.6
    return result


# ═══════════════════════════════════════════════════════════════
#  批量多 Agent 选股（screener 调用）
# ═══════════════════════════════════════════════════════════════

async def run_multi_agent_screen(
    candidates: list[dict],
    provider: str = "",
    agent_keys: list[str] | None = None,
) -> dict:
    """对候选股票池逐只运行多 Agent 深度分析，返回排名结果

    这是 screener.py 中「多 Agent 交叉验证」的入口函数。

    Args:
        candidates: [{code, name, ...}] — 候选股票列表
        provider: AI 供应商
        agent_keys: 要使用的 Agent 列表（保留参数，当前总是用 5 Agent 全流程）

    Returns:
        {
            "results": [{rank, code, name, verdict, confidence, score, ...}],
            "summary": {total, buy_count, hold_count, sell_count, avg_confidence},
            "top_picks": [...],
        }
    """
    import asyncio

    if not candidates:
        return {"error": "候选池为空", "results": [], "summary": {}}

    # 限制并发数
    sem = asyncio.Semaphore(3)

    async def analyze_one(c: dict) -> dict:
        async with sem:
            code = c.get("code", "")
            name = c.get("name", "")
            stock_info = c
            try:
                result = await analyze_stock(
                    code=code,
                    provider=provider,
                )
                # 添加原始候选信息
                result["candidate"] = stock_info
                return result
            except Exception as e:
                logger = __import__("logging").getLogger(__name__)
                logger.warning(f"multi_agent_screen: failed to analyze {code}: {e}")
                return {
                    "code": code,
                    "name": name,
                    "error": str(e),
                    "verdict": "持有",
                    "confidence": 0,
                }

    # 并行分析所有候选（最多3并发）
    tasks = [analyze_one(c) for c in candidates[:30]]
    raw_results = await asyncio.gather(*tasks)
    results = list(raw_results)

    # 评分排序
    def _score(r: dict) -> float:
        if r.get("error"):
            return -1
        verdict = r.get("verdict", "持有")
        confidence = r.get("confidence", 0.5)
        base = 0.5
        if verdict == "买入":
            base = 1.0
        elif verdict == "卖出":
            base = 0.0
        return base * confidence

    results.sort(key=_score, reverse=True)

    # 统计
    buy_count = sum(1 for r in results if r.get("verdict") == "买入")
    hold_count = sum(1 for r in results if r.get("verdict") == "持有")
    sell_count = sum(1 for r in results if r.get("verdict") == "卖出")
    confidences = [r.get("confidence", 0) for r in results if not r.get("error")]

    # Top picks
    top_picks = [r for r in results if r.get("verdict") == "买入"][:5]

    return {
        "results": [
            {
                "rank": i + 1,
                "code": r.get("code"),
                "name": r.get("name"),
                "verdict": r.get("verdict"),
                "confidence": r.get("confidence"),
                "score": round(_score(r), 3),
                "key_reasons": r.get("key_reasons", []),
                "risk_warning": r.get("risk_warning", ""),
                "technical_report": r.get("technical_report", "")[:200] if r.get("technical_report") else "",
            }
            for i, r in enumerate(results)
        ],
        "summary": {
            "total": len(results),
            "buy_count": buy_count,
            "hold_count": hold_count,
            "sell_count": sell_count,
            "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0,
        },
        "top_picks": [
            {
                "code": r.get("code"),
                "name": r.get("name"),
                "verdict": r.get("verdict"),
                "confidence": r.get("confidence"),
                "key_reasons": r.get("key_reasons", []),
            }
            for r in top_picks
        ],
    }
