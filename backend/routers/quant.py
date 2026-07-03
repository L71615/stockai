"""量化分析 API 路由：风控指标 / 相关性 / 回测 / 蒙特卡洛"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.quant_service import (
    calc_correlation_matrix,
    backtest_dca,
    compare_strategies,
    monte_carlo_sim,
    get_portfolio_risk,
    get_benchmark_comparison,
)
from fastapi.responses import PlainTextResponse
import csv, io

router = APIRouter(prefix="/api/quant", tags=["Quant"])


# ==================== 个股透视 ====================

@router.get("/stock-insight/{code}")
def stock_insight(code: str, days: int = 120):
    """个股深度数据聚合：K线 + 技术指标 + 因子 + 实时行情"""
    from services.technical import get_indicators as calc_indicators
    from services.utils import get_market

    # 1. K 线 + 成交量（Baostock 优先，补 volumes）
    kline_data = {}
    from services.technical import fetch_kline

    kline = fetch_kline(code, get_market(code), days=days)
    if "error" not in kline:
        # 尝试从 Baostock 补 volumes（部分数据源不返回）
        vols = kline.get("volumes") or []
        if not vols and not code.startswith(("51", "159", "588", "56")):
            try:
                from services.baostock_adapter import get_kline as bs_kline
                bk = bs_kline(code, days=days)
                if "error" not in bk:
                    vols = bk.get("volumes") or []
            except Exception:
                pass

        kline_data = {
            "dates": kline.get("dates", []),
            "opens": kline.get("opens", []),
            "closes": kline.get("closes", []),
            "highs": kline.get("highs", []),
            "lows": kline.get("lows", []),
            "volumes": list(vols),
        }

    # Baostock 不可用时兜底
    if not kline_data.get("dates"):
        from services.technical import fetch_kline
        kline = fetch_kline(code, get_market(code), days=days)
        if "error" not in kline:
            kline_data = {
                "dates": kline.get("dates", []),
                "opens": kline.get("opens", []),
                "closes": kline.get("closes", []),
                "highs": kline.get("highs", []),
                "lows": kline.get("lows", []),
                "volumes": kline.get("volumes", []),
            }

    # 2. 计算 MA 数组（给前端 KlineChart 蜡烛图用）
    def _sma_arr(values, period):
        result = [None] * len(values)
        s = 0
        for i, v in enumerate(values):
            s += v
            if i >= period - 1:
                if i >= period:
                    s -= values[i - period]
                result[i] = round(s / period, 2)
        return result

    closes = kline_data.get("closes", [])
    kline_data["ma5"] = _sma_arr(closes, 5) if closes else []
    kline_data["ma10"] = _sma_arr(closes, 10) if closes else []
    kline_data["ma20"] = _sma_arr(closes, 20) if closes else []

    # 3. 技术指标
    indicators = calc_indicators(code, get_market(code), days=days)

    # 4. 实时行情
    from routers.stocks import _cached_quote
    quote = _cached_quote(code, get_market(code))

    # 5. 海龟交易法通道计算
    highs = kline_data.get("highs", [])
    lows = kline_data.get("lows", [])
    closes_t = kline_data.get("closes", [])

    def _calc_atr(h, l, c, period=20):
        if len(c) < period + 1:
            return None
        trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
        return round(sum(trs[-period:]) / period, 4) if len(trs) >= period else None

    def _calc_turtle():
        n = len(closes_t)
        if n < 60:
            return {"error": "K线不足60天", "turtle_score": 0}
        price = closes_t[-1]
        prev = closes_t[-2] if n >= 2 else price
        atr_val = _calc_atr(highs, lows, closes_t, 20)
        s1e = round(max(highs[-21:-1]), 2) if n >= 21 else None
        s2e = round(max(highs[-56:-1]), 2) if n >= 56 else None
        s1x = round(min(lows[-11:-1]), 2) if n >= 11 else None
        s2x = round(min(lows[-21:-1]), 2) if n >= 21 else None
        ph20 = max(highs[-22:-2]) if n >= 22 else s1e
        ph55 = max(highs[-57:-2]) if n >= 57 else s2e
        pl10 = min(lows[-12:-2]) if n >= 12 else s1x
        pl20 = min(lows[-22:-2]) if n >= 22 else s2x
        s1_enter = bool(ph20 and price > ph20 and prev <= ph20)
        s2_enter = bool(ph55 and price > ph55 and prev <= ph55)
        s1_exit_b = bool(pl10 and price < pl10 and prev >= pl10)
        s2_exit_b = bool(pl20 and price < pl20 and prev >= pl20)
        dist_s1 = round((s1e - price) / s1e * 100, 2) if s1e else None
        dist_s2 = round((s2e - price) / s2e * 100, 2) if s2e else None
        pos = round((price - s1x) / (s1e - s1x), 4) if s1e and s1x and (s1e - s1x) > 0 else None
        pos = max(0.0, min(1.0, pos)) if pos is not None else None
        # 0-100 评分
        score = 0
        details = []
        if s1_enter:
            score += 30; details.append("S1入场触发")
        elif dist_s1 is not None and dist_s1 < 3:
            score += 15; details.append(f"近S1入场({dist_s1}%)")
        if s2_enter:
            score += 25; details.append("S2入场触发")
        elif dist_s2 is not None and dist_s2 < 5:
            score += 12; details.append(f"近S2入场({dist_s2}%)")
        if pos is not None:
            if pos > 0.8: score += 25; details.append("强势区间")
            elif pos > 0.5: score += 18; details.append("偏强区间")
            elif pos > 0.3: score += 10; details.append("中性区间")
            else: score += 3; details.append("弱势区间")
        if s1_exit_b: score -= 20; details.append("S1出场!")
        if s2_exit_b: score -= 15; details.append("S2出场!")
        if atr_val and price > 0:
            vol_r = atr_val / price * 100
            if 1.5 <= vol_r <= 5: score += 10
            elif vol_r < 1.5: score += 5
            else: score += 3
        if s1e and s1x and s1e > 0:
            cw = (s1e - s1x) / s1e * 100
            if 5 <= cw <= 25: score += 10
            elif cw > 25: score += 5
            else: score += 3
        return {
            "atr_20": atr_val, "sys1_entry": s1e, "sys2_entry": s2e,
            "sys1_exit": s1x, "sys2_exit": s2x,
            "distance_sys1_pct": dist_s1, "distance_sys2_pct": dist_s2,
            "sys1_triggered": s1_enter, "sys2_triggered": s2_enter,
            "sys1_exit_triggered": s1_exit_b, "sys2_exit_triggered": s2_exit_b,
            "channel_position": pos, "turtle_score": max(0, min(100, score)),
            "details": details,
        }

    turtle = _calc_turtle()

    # 6. 基本面因子
    factors = {}
    _factors_executor = None
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
        from services.baostock_adapter import get_stock_factors

        _factors_executor = ThreadPoolExecutor(max_workers=1)
        fut = _factors_executor.submit(get_stock_factors, code)
        factors = fut.result(timeout=0.8)
    except FuturesTimeoutError:
        factors = {}
        try:
            fut.cancel()
        except Exception:
            pass
    except Exception:
        factors = {}
    finally:
        if _factors_executor is not None:
            _factors_executor.shutdown(wait=False, cancel_futures=True)

    return {
        "code": code,
        "name": indicators.get("name") or quote.get("name", ""),
        "price": indicators.get("price") or quote.get("price"),
        "change_pct": quote.get("change_pct"),
        "kline": kline_data,
        "indicators": {
            "MA": indicators.get("MA", {}),
            "MACD": indicators.get("MACD", {}),
            "KDJ": indicators.get("KDJ", {}),
            "RSI": indicators.get("RSI"),
        },
        "signal": indicators.get("signal", ""),
        "turtle": turtle,
        "factors": {
            "pe": factors.get("pe"),
            "pb": factors.get("pb"),
            "roe": factors.get("roe"),
            "eps": factors.get("eps"),
            "market_cap_billion": factors.get("market_cap_billion"),
            "dividend": factors.get("dividend"),
            "industry": factors.get("industry", ""),
            "industry_type": factors.get("industry_type", ""),
        },
    }


# ==================== 全因子面板 ====================

@router.get("/factor-panel/{code}")
def factor_panel(code: str, days: int = 120):
    """个股全因子面板 — 7大类因子完整评分 + 雷达图数据"""
    from services.factor_service import compute_all_factors, FACTOR_REGISTRY, REGISTRY_SUMMARY
    from services.technical import fetch_kline as _fetch_kline
    from services.utils import get_market as _get_market
    from services.baostock_adapter import get_stock_factors

    mkt = _get_market(code)
    kline = _fetch_kline(code, mkt, days=days)
    if "error" in kline:
        raise HTTPException(400, f"无法获取 {code} 的K线数据")

    closes = kline.get("closes", [])
    highs = kline.get("highs", [])
    lows = kline.get("lows", [])
    volumes = kline.get("volumes", [])

    if len(closes) < 60:
        raise HTTPException(400, f"{code} 数据不足 (需>=60天)")

    try:
        fundamentals = get_stock_factors(code)
    except Exception:
        fundamentals = {}

    # 资金流向数据（北向+机构持仓），失败不影响主流程
    north_flow_data = None
    inst_data = None
    try:
        from services.akshare_adapter import get_north_flow, get_inst_holding
        north_flow_data = get_north_flow(code)
    except Exception:
        pass
    try:
        from services.akshare_adapter import get_inst_holding
        inst_data = get_inst_holding(code)
    except Exception:
        pass

    raw = compute_all_factors(code, closes, highs, lows, volumes, fundamentals,
                               prev_eps=fundamentals.get("prev_eps"),
                               dividend=fundamentals.get("dividend"),
                               north_flow_data=north_flow_data,
                               inst_data=inst_data)
    import math

    # 因子评分映射 — 基于合理A股范围，0-100打分
    def factor_to_score(fname: str, value, direction: str) -> int | None:
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        # 定义各因子的合理区间 [低, 中低, 中, 中高, 高]
        thresholds = {
            "RET_5D": (-3, 0, 2, 5, 10), "RET_20D": (-8, -2, 3, 10, 20),
            "RET_60D": (-15, -5, 8, 20, 40), "RSI": (25, 35, 50, 65, 80),
            "MACD": (-0.02, 0, 0.01, 0.03, 0.06), "MA_DISPOSITION": (-0.6, -0.2, 0, 0.3, 0.7),
            "VOLATILITY_5": (0.1, 0.2, 0.3, 0.5, 0.8), "VOLATILITY_20": (0.15, 0.25, 0.35, 0.55, 0.85),
            "ATR": (0.01, 0.02, 0.04, 0.07, 0.12), "RANGE_VOLATILITY": (0.05, 0.1, 0.2, 0.35, 0.5),
            "DOWNSIDE_VOL": (0.08, 0.15, 0.25, 0.4, 0.6), "VOL_RATIO": (0.6, 0.85, 1.1, 1.5, 2.5),
            "PRICE_VOLUME": (-0.5, -0.2, 0.2, 0.5, 0.8), "TURNOVER_RATE": (0.005, 0.01, 0.03, 0.06, 0.12),
            "OBV_DIVERGENCE": (0.5, 0.8, 1.0, 1.3, 1.8), "AVG_AMOUNT": (6.0, 6.7, 7.7, 8.3, 9.0),  # log10(成交额) (1e6→6, 5e6→6.7, 5e7→7.7, 2e8→8.3, 1e9→9)
            "PE": (0.01, 0.017, 0.029, 0.05, 0.1),  # 盈利率 1/PE (PE=100→1%, 60→1.7%, 35→2.9%, 20→5%, 10→10%)
            "PB": (0.08, 0.17, 0.33, 0.67, 2.0),  # 1/PB (PB=12→0.08, 6→0.17, 3→0.33, 1.5→0.67, 0.5→2)
            "ROE": (0.02, 0.08, 0.15, 0.25, 0.35),  # 小数 (2%→0.02, 8%→0.08, ...)
            "EPS_GROWTH": (-30, 0, 15, 30, 60),
            "MARKET_CAP": (20, 50, 200, 500, 2000), "DIVIDEND_YIELD": (0.005, 0.015, 0.03, 0.05, 0.08),  # 小数 (0.5%→0.005, ...)
            "STRENGTH_20D": (0.2, 0.5, 1.0, 2.0, 4.0),
            "MOMENTUM_COMPOSITE": (0.2, 0.5, 1.0, 2.0, 4.0),
            "NORTH_FLOW": (-500, -100, 100, 500, 2000),
            "INST_CHANGE": (-3, -0.5, 0.5, 3, 10),
        }
        # 通用fallback: [-5, 0, 5, 15, 30] for momentum-like
        lo, mlo, mid, mhi, hi = thresholds.get(fname, (-5, 0, 5, 15, 30))
        # 线性插值到0-100
        if v <= lo: pts = 5
        elif v <= mlo: pts = 5 + 20 * (v - lo) / (mlo - lo)
        elif v <= mid: pts = 25 + 25 * (v - mlo) / (mid - mlo)
        elif v <= mhi: pts = 50 + 25 * (v - mid) / (mhi - mid)
        elif v <= hi: pts = 75 + 25 * (v - mhi) / (hi - mhi)
        else: pts = 100
        # 负向因子反转
        if direction == "负向":
            pts = 100 - pts
        return round(max(0, min(100, pts)))

    categories: dict[str, dict] = {}
    for fname, finfo in FACTOR_REGISTRY.items():
        cat = finfo["category"]
        if cat not in categories:
            categories[cat] = {"name": cat, "factors": [], "score_avg": 0}
        # 用 fn 名推导 compute_all_factors 的输出 key（去掉 "factor_" 前缀）
        fn_name = finfo.get("fn", "")
        output_key = fn_name.replace("factor_", "") if fn_name.startswith("factor_") else fn_name.lower()
        value = raw.get("factors", {}).get(output_key)
        status = finfo["status"]
        score = factor_to_score(fname, value, finfo.get("direction", "正向")) if status == "done" else None
        categories[cat]["factors"].append({
            "name": fname, "display": fname.replace("_", " "),
            "value": round(value, 4) if isinstance(value, float) else value,
            "score": score, "status": status,
            "direction": finfo.get("direction", "中性"),
        })

    for cat_data in categories.values():
        scored = [f["score"] for f in cat_data["factors"] if f["score"] is not None]
        cat_data["score_avg"] = round(sum(scored) / len(scored)) if scored else None
        cat_data["factor_count"] = len(cat_data["factors"])
        cat_data["done_count"] = sum(1 for f in cat_data["factors"] if f["status"] == "done")

    all_scores = [c["score_avg"] for c in categories.values() if c["score_avg"] is not None]
    overall = round(sum(all_scores) / len(all_scores)) if all_scores else None

    return {
        "code": code,
        "price": closes[-1] if closes else None,
        "date": kline.get("dates", [])[-1] if kline.get("dates") else None,
        "overall_score": overall,
        "categories": [{"key": k, **v} for k, v in categories.items()],
        "registry_summary": REGISTRY_SUMMARY,
        "hit_count": raw.get("hit_count", 0),
    }


# ==================== AI 量化解读 ====================

class StockExplainRequest(BaseModel):
    provider: str = ""  # 空则使用默认供应商
    include_kline: bool = False  # 是否包含K线摘要


@router.post("/stock/{code}/explain")
async def stock_explain(code: str, body: StockExplainRequest = None):
    """单股量化 AI 解读：技术面 + 基本面 + 风险提示

    每条 reason 必须引用具体因子值，不做空泛表述。
    异常降级：超时/429/空响应 → 返回 error 字段而非 500。
    """
    from services.ai_service import ai_chat, get_default_provider
    from services.ai_exceptions import AIServiceError
    from services.utils import get_market

    body = body or StockExplainRequest()

    # 收集数据
    from services.technical import get_indicators as calc_indicators
    from services.baostock_adapter import get_stock_factors

    try:
        indicators = calc_indicators(code, get_market(code), days=120)
    except Exception:
        indicators = {}

    try:
        factors = get_stock_factors(code)
    except Exception:
        factors = {}

    price = indicators.get("price") or factors.get("price") or 0
    name = indicators.get("name") or factors.get("industry") or code
    ma = indicators.get("MA") or {}
    macd = indicators.get("MACD") or {}
    rsi_val = indicators.get("RSI")
    signal = indicators.get("signal") or ""

    pe = factors.get("pe")
    pb = factors.get("pb")
    roe = factors.get("roe")
    eps = factors.get("eps")
    mktcap = factors.get("market_cap_billion")
    div = factors.get("dividend")

    # 海龟数据
    turtle_extra = ""
    try:
        highs = []
        lows = []
        closes_t = []
        from services.technical import fetch_kline as _fk
        kline = _fk(code, get_market(code), days=120)
        if "error" not in kline:
            highs = kline.get("highs", [])
            lows = kline.get("lows", [])
            closes_t = kline.get("closes", [])
        if len(closes_t) >= 60:
            trs = [max(highs[i] - lows[i], abs(highs[i] - closes_t[i - 1]), abs(lows[i] - closes_t[i - 1])) for i in range(1, len(closes_t))]
            atr20 = round(sum(trs[-20:]) / 20, 4) if len(trs) >= 20 else None
            s1e = round(max(highs[-21:-1]), 2) if len(highs) >= 21 else None
            s2e = round(max(highs[-56:-1]), 2) if len(highs) >= 56 else None
            s1x = round(min(lows[-11:-1]), 2) if len(lows) >= 11 else None
            s2x = round(min(lows[-21:-1]), 2) if len(lows) >= 21 else None
            cur = closes_t[-1]
            prev = closes_t[-2]
            s1_tri = bool(max(highs[-22:-2]) if len(highs) >= 22 else 0 and cur > max(highs[-22:-2]) and prev <= max(highs[-22:-2]))
            s2_tri = bool(max(highs[-57:-2]) if len(highs) >= 57 else 0 and cur > max(highs[-57:-2]) and prev <= max(highs[-57:-2]))
            dist1 = round((s1e - cur) / s1e * 100, 1) if s1e else None
            dist2 = round((s2e - cur) / s2e * 100, 1) if s2e else None
            turtle_extra = f"""
海龟交易法：
- S1入场(20日高点)={s1e}元，S2入场(55日高点)={s2e}元
- S1出场(10日低点)={s1x}元，S2出场(20日低点)={s2x}元
- ATR(20)={atr20}，距S1入场={dist1}%，距S2入场={dist2}%
- S1突破触发={'是' if s1_tri else '否'}，S2突破触发={'是' if s2_tri else '否'}"""
    except Exception:
        pass

    prompt = f"""你是专业A股分析师。请严格按以下JSON格式输出，不要加任何markdown标记。

股票：{name}（{code}）
最新价：{price}元

技术面数据：
- 均线：MA5={ma.get('MA5')}，MA10={ma.get('MA10')}，MA20={ma.get('MA20')}，MA60={ma.get('MA60')}
- MACD：DIF={macd.get('DIF')}，DEA={macd.get('DEA')}，MACD={macd.get('MACD')}
- RSI(14)：{rsi_val}
- AI信号描述：{signal}
{turtle_extra}

基本面数据（TTM）：
- PE={pe}，PB={pb}，ROE={roe}%，EPS={eps}元
- 市值={mktcap}亿元，股息={div}元/股

请输出JSON（不超过800字）：
{{"technical":{{"verdict":"string","signals":[{{"indicator":"string","value":"string","reason":"必须引用上面具体数值"}}]}},"fundamental":{{"verdict":"string","signals":[{{"indicator":"string","value":"string","reason":"必须引用上面具体数值"}}]}},"risk_alerts":[{{"level":"warn|info","message":"string"}}]}}
"""

    try:
        provider = body.provider or get_default_provider()
        raw = await ai_chat(prompt, function="explain", provider=provider)
    except AIServiceError as e:
        return {"error": str(e), "provider": e.provider_name}

    if not raw or not raw.strip():
        return {"error": "AI 返回为空，请稍后重试"}
    text = raw.strip()

    # 尝试解析 JSON
    import re, json as _json
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.rstrip().endswith("```"):
            text = text[:text.rstrip().rfind("```")].strip()

    try:
        result = _json.loads(text)
        return {
            "stock": {"code": code, "name": name},
            "technical": result.get("technical", {}),
            "fundamental": result.get("fundamental", {}),
            "risk_alerts": result.get("risk_alerts", []),
        }
    except Exception:
        # 尝试从文本中提取 JSON 片段
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                result = _json.loads(m.group(0))
                return {
                    "stock": {"code": code, "name": name},
                    "technical": result.get("technical", {}),
                    "fundamental": result.get("fundamental", {}),
                    "risk_alerts": result.get("risk_alerts", []),
                }
            except Exception:
                pass
        return {"error": "AI 返回格式解析失败，请稍后重试"}



# ==================== 请求体 ====================

class BacktestRequest(BaseModel):
    code: str
    amount: float = 1000.0
    freq: str = "monthly"       # "weekly" | "monthly"
    start_date: str = "2025-01-01"
    end_date: str = ""           # 默认今天


class CompareRequest(BaseModel):
    code: str
    amount: float = 1000.0
    start_date: str = "2025-01-01"
    end_date: str = ""


class MonteCarloRequest(BaseModel):
    code: str
    days: int = 252
    sims: int = 1000


# ==================== 端点 ====================

@router.get("/factors/{code}")
def stock_factors(code: str):
    """获取单只股票的基本面因子（PE/PB/ROE/行业等）"""
    from services.baostock_adapter import get_stock_factors
    result = get_stock_factors(code)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/factors")
def stock_factors_batch(codes: list[str]):
    """批量获取多只股票的基本面因子"""
    from services.baostock_adapter import get_factors_batch
    return get_factors_batch(codes)


@router.get("/portfolio-risk")
def portfolio_risk():
    """获取整个投资组合的风控指标摘要"""
    result = get_portfolio_risk()
    return result


@router.get("/correlation")
def correlation():
    """获取持仓间价格相关性矩阵"""
    from database import query_all
    from services.technical import fetch_kline
    from services.utils import get_market

    from dependencies import get_current_user_id
    holdings = query_all("SELECT * FROM holdings WHERE user_id = ? ORDER BY id DESC", (get_current_user_id(),))
    if not holdings:
        return {"stocks": [], "matrix": [], "error": "无持仓数据"}

    prices_map: dict[str, list[float]] = {}
    for h in holdings:
        code = h["stock_code"]
        kline = fetch_kline(code, get_market(code), days=252)
        if "error" not in kline and kline.get("closes"):
            prices_map[code] = kline["closes"]

    return calc_correlation_matrix(prices_map)


@router.get("/benchmarks")
def benchmarks():
    """获取组合 vs 多个基准指数的对比"""
    return get_benchmark_comparison()


@router.get("/export/{export_type}")
def export_csv(export_type: str):
    """导出量化数据为 CSV

    export_type: "risk" | "correlation" | "backtest"
    其中 backtest 需要 query params: code, amount, freq, start_date, end_date
    """
    if export_type == "risk":
        data = get_portfolio_risk()
        if data.get("error"):
            raise HTTPException(400, data["error"])
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["指标", "值"])
        w.writerow(["持仓数量", data["holdings_count"]])
        w.writerow(["夏普比率", data.get("sharpe", "")])
        w.writerow(["最大回撤", data.get("max_drawdown", "")])
        w.writerow(["年化波动率", data.get("volatility", "")])
        w.writerow(["Beta vs 沪深300", data.get("beta", "")])
        for hr in data.get("holdings_risk", []):
            w.writerow([f"{hr.get('code','')} {hr.get('name','')} Sharpe", hr.get("sharpe", "")])
            w.writerow([f"{hr.get('code','')} {hr.get('name','')} MaxDD", hr.get("max_dd", "")])
            w.writerow([f"{hr.get('code','')} {hr.get('name','')} Vol", hr.get("vol", "")])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=risk-metrics.csv"})

    elif export_type == "correlation":
        data = get_portfolio_risk()
        corr = data.get("correlation", {})
        buf = io.StringIO()
        w = csv.writer(buf)
        stocks = corr.get("stocks", [])
        w.writerow([""] + stocks)
        for i, s in enumerate(stocks):
            row = [s] + corr["matrix"][i] if i < len(corr["matrix"]) else []
            w.writerow(row)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=correlation.csv"})

    else:
        raise HTTPException(400, f"未知导出类型: {export_type}")


@router.post("/backtest")
def backtest(req: BacktestRequest):
    """DCA 定期定额历史回测"""
    result = backtest_dca(req.code, req.amount, req.freq, req.start_date, req.end_date)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/compare")
def compare(req: CompareRequest):
    """对比 4 种策略的历史表现"""
    result = compare_strategies(req.code, req.amount, req.start_date, req.end_date)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/monte-carlo")
def monte_carlo(req: MonteCarloRequest):
    """蒙特卡洛仓位模拟"""
    from services.technical import fetch_kline
    from services.utils import get_market

    kline = fetch_kline(req.code, get_market(req.code), days=252)
    if "error" in kline:
        raise HTTPException(400, f"无法获取 {req.code} 的历史数据")
    if not kline.get("closes"):
        raise HTTPException(400, f"{req.code} 无价格数据")

    result = monte_carlo_sim(kline["closes"], days=req.days, sims=req.sims)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ═══════════════════════════════════════════════════════════════
#  AI 因子解读 — 基于因子面板数据生成总结报告
# ═══════════════════════════════════════════════════════════════

class FactorExplainRequest(BaseModel):
    code: str
    overall_score: float | None = None
    categories: list[dict] = []  # [{name, score_avg, done_count, ...}]


@router.post("/factor-explain")
async def factor_explain(body: FactorExplainRequest):
    """AI 因子解读 — 基于因子面板评分生成结构化报告

    输入因子评分摘要（前端已计算），AI 分析优势/风险维度并给出建议。
    """
    from services.ai_service import ai_chat
    from services.ai_exceptions import AIServiceError

    if not body.categories:
        return {"error": "因子数据为空"}

    # 构建因子摘要
    cat_lines = []
    for c in body.categories:
        name = c.get("name", "")
        score = c.get("score_avg")
        done = c.get("done_count", 0)
        total = c.get("factor_count", 0)
        score_str = f"{score}/100" if score is not None else "无数据"
        cat_lines.append(f"- {name}：{score_str}（{done}/{total}因子）")

    cats_text = "\n".join(cat_lines)
    overall = body.overall_score
    overall_str = f"{overall}/100" if overall is not None else "未计算"

    prompt = f"""你是专业A股量化分析师。请基于以下因子面板数据，生成一份简明的因子解读报告。

股票代码：{body.code}
综合评分：{overall_str}

各维度评分：
{cats_text}

请严格按JSON格式输出（不要加markdown）：
{{"strengths":[{{"dimension":"维度名","score":分数,"insight":"一句话解读"}}],"weaknesses":[{{"dimension":"维度名","score":分数,"insight":"一句话解读"}}],"overall":"综合评估（不超过80字）","suggestion":"操作建议（不超过60字）"}}

要求：
- strengths 列出得分最高的2-3个维度
- weaknesses 列出得分最低的2-3个维度
- insight 必须引用具体分数，不要空泛
- overall 给出综合评价
- suggestion 基于因子画像给1条可操作建议
- 总字数不超过400字"""

    try:
        raw = await ai_chat(prompt, function="explain",
            system_prompt="你是专业A股量化分析师。严格按JSON格式输出。")
    except AIServiceError as e:
        return {"error": str(e), "provider": e.provider_name}

    if not raw or not raw.strip():
        return {"error": "AI 返回为空"}
    text = raw.strip()

    import re, json as _json
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.rstrip().endswith("```"):
            text = text[:text.rfind("```")].strip()

    try:
        result = _json.loads(text)
        return {
            "code": body.code,
            "overall_score": overall,
            "strengths": result.get("strengths", []),
            "weaknesses": result.get("weaknesses", []),
            "overall": result.get("overall", ""),
            "suggestion": result.get("suggestion", ""),
        }
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                result = _json.loads(m.group(0))
                return {
                    "code": body.code,
                    "overall_score": overall,
                    "strengths": result.get("strengths", []),
                    "weaknesses": result.get("weaknesses", []),
                    "overall": result.get("overall", ""),
                    "suggestion": result.get("suggestion", ""),
                }
            except Exception:
                pass
        return {"error": "AI 返回格式解析失败"}


# ═══════════════════════════════════════════════════════════════
#  月度因子回测 — 源自 moonshot 项目
# ═══════════════════════════════════════════════════════════════

class MonthlyBacktestRequest(BaseModel):
    """月度因子回测请求"""
    code: str = ""                  # 单只股票代码 (为空则用持仓)
    factor_col: str = "momentum"    # 因子列名
    quantiles: int = 5              # 分层数
    long_only: bool = True          # 仅做多
    days: int = 252                 # 历史数据天数


@router.post("/monthly-backtest")
def monthly_backtest(req: MonthlyBacktestRequest):
    """
    月度因子回测

    对指定股票/持仓组合运行月度因子分层回测:
      - 连续因子按月 qcut 分层 → -1/0/1 信号
      - 新开仓用 COO 收益，持仓用 MOM 收益
      - 返回策略收益、基准收益、分层收益、绩效指标

    请求示例:
      POST /api/quant/monthly-backtest
      {"code": "600519", "factor_col": "momentum", "quantiles": 5}
    """
    import pandas as pd
    from services.technical import fetch_kline
    from services.utils import get_market
    from services.monthly_backtest import run_monthly_backtest

    code = req.code.strip()
    if not code:
        raise HTTPException(400, "请提供股票代码")

    # 获取日线数据
    market = get_market(code)
    kline = fetch_kline(code, market, days=req.days)
    if "error" in kline:
        raise HTTPException(400, f"无法获取 {code} 的历史数据")

    closes = kline.get("closes", [])
    if len(closes) < 60:
        raise HTTPException(400, f"{code} 历史数据不足 (需要至少60天)")

    dates = kline.get("dates", [])
    opens = kline.get("opens", [])
    highs = kline.get("highs", [])
    lows = kline.get("lows", [])
    volumes = kline.get("volumes", [])

    # 构建日线 DataFrame
    daily = pd.DataFrame({
        "date": pd.to_datetime(dates),
        "asset": code,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    daily = daily.dropna()

    # 构建因子数据 (示例: 20日动量)
    daily["returns"] = daily["close"].pct_change()
    daily["momentum"] = daily["close"].pct_change(20)
    daily["volatility"] = daily["returns"].rolling(20).std()
    daily["rsi"] = (
        daily["returns"].clip(lower=0).rolling(14).mean()
        / daily["returns"].abs().rolling(14).mean()
    )
    daily = daily.dropna()

    factor_data = daily[["date", "asset", req.factor_col]].copy()

    daily_bars = daily[["date", "asset", "open", "high", "low", "close", "volume"]]

    result = run_monthly_backtest(
        daily_bars, factor_data, req.factor_col,
        quantiles=req.quantiles, long_only=req.long_only,
    )

    if "error" in result.get("metrics", {}):
        raise HTTPException(500, result["metrics"]["error"])

    return {
        "code": code,
        "factor": req.factor_col,
        "quantiles": req.quantiles,
        "long_only": req.long_only,
        **result,
    }


# ═══════════════════════════════════════════════════════════════
#  策略回测 — YAML 策略 + 历史数据模拟
# ═══════════════════════════════════════════════════════════════

class StrategyBacktestRequest(BaseModel):
    """策略回测请求"""
    strategy_ids: list[str] = ["turtle_s1"]   # YAML 策略 id 列表
    stock_codes: list[str] = []               # 股票代码列表，空=默认池
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    initial_cash: float = 100000
    hold_days: int = 5
    rebalance_freq: str = "daily"             # daily / weekly / monthly
    max_positions: int = 10
    position_size_pct: float = 0.1            # 单票仓位比例
    benchmark: str = "000300"                 # 基准指数


@router.post("/strategy-backtest")
def strategy_backtest(req: StrategyBacktestRequest):
    """策略回测：用 YAML 策略在历史数据上模拟选股 + 交易 + 绩效报告

    对每个调仓日:
      1. 从 historical_kline 构建历史截面（只用当日及之前数据）
      2. 计算技术字段（MA/RSI/MACD/ATR 等）
      3. 用 condition_engine 执行策略条件筛选
      4. 模拟买入（次日开盘价）/ 卖出（持仓满 hold_days）
      5. 记录每日净值曲线

    返回:
      - config: 回测配置
      - metrics: 绩效指标（年化收益/夏普/最大回撤/胜率/盈亏比/卡玛）
      - equity_curve: 每日净值 + 基准对比
      - trades: 完整交易明细
      - monthly_returns: 月度收益 + 基准对比
    """
    from services.strategy_backtest_service import run_strategy_backtest

    if not req.strategy_ids:
        raise HTTPException(400, "至少选择一个策略")

    if req.hold_days < 1:
        raise HTTPException(400, "持仓天数至少为 1")

    if req.max_positions < 1:
        raise HTTPException(400, "最大持仓数至少为 1")

    if req.position_size_pct <= 0 or req.position_size_pct > 1:
        raise HTTPException(400, "单票仓位比例需在 0.01 ~ 1.00 之间")

    result = run_strategy_backtest(
        strategy_ids=req.strategy_ids,
        stock_codes=req.stock_codes if req.stock_codes else [],
        start_date=req.start_date,
        end_date=req.end_date,
        initial_cash=req.initial_cash,
        hold_days=req.hold_days,
        rebalance_freq=req.rebalance_freq,
        max_positions=req.max_positions,
        position_size_pct=req.position_size_pct,
        benchmark=req.benchmark,
    )

    if "error" in result:
        raise HTTPException(400, result["error"])

    return result


@router.get("/strategies")
def list_backtest_strategies():
    """返回所有可用于回测的策略列表（YAML + 内置）"""
    from services.strategy_backtest_service import _list_available_strategies
    return _list_available_strategies()


# ═══════════════════════════════════════════════════════════════
#  多 Agent 深度分析
# ═══════════════════════════════════════════════════════════════

class MultiAgentRequest(BaseModel):
    code: str
    provider: str = ""
    api_key: str = ""
    model: str = ""


@router.post("/multi-agent-analysis")
async def multi_agent_analysis(req: MultiAgentRequest):
    """多 Agent 深度分析: 技术面+基本面→多空辩论→最终判断

    5 个 Agent，3 轮调用:
      1. 技术面 + 基本面 (并行)
      2. 多头 + 空头 辩论 (并行)
      3. 裁判 裁决

    返回:
      {code, name, price, technical_report, fundamentals_report,
       bull_case, bear_case, verdict, confidence, key_reasons,
       risk_warning, suggested_hold_days, stop_loss_pct}
    """
    from services.multi_agent_service import analyze_stock

    if not req.code or not req.code.strip():
        raise HTTPException(400, "请输入股票代码")

    result = await analyze_stock(
        code=req.code.strip(),
        provider=req.provider,
        api_key=req.api_key,
        model=req.model,
    )

    if "error" in result:
        raise HTTPException(500, result["error"])

    return result
