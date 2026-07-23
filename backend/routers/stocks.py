"""股市数据路由 — 行情 / 指数 / 技术指标 / 新闻 / AI复盘 / 预警"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute
from dependencies import get_current_user_id
from services.news_service import get_matched_news, fetch_news_jsonp, _industry_keyword
from services.ai_service import ai_chat
from services.ai_exceptions import AIServiceError
from services.technical import get_indicators as calc_indicators
from services.utils import run_curl, get_market, detect_asset_type, get_fund_nav
from services.futu_ingest_service import get_minute_kline_with_fallback

router = APIRouter()


# ==================== 实时行情（共享缓存） ====================

_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}  # key -> (expire_time, result)
_CACHE_TTL = 5.0  # 秒


def _cache_key(code: str, market: str | None = None) -> str:
    return f"{code}:{market or ''}"


def _cached_quote(code: str, market: str | None = None) -> dict:
    """带缓存的行情获取"""
    key = _cache_key(code, market)
    entry = _QUOTE_CACHE.get(key)
    if entry and time.time() < entry[0]:
        return entry[1]
    result = _fetch_quote_sync(code, market)
    _QUOTE_CACHE[key] = (time.time() + _CACHE_TTL, result)
    return result


def _fetch_quote_legacy(code: str, market: str | None = None) -> dict:
    """旧实时行情链路：港股→新浪，美股→akshare，A股→腾讯→东方财富。"""
    from services.utils import is_hk_stock, is_us_stock

    # 港股：新浪财经
    if is_hk_stock(code):
        try:
            from services.sina_adapter import get_hk_quote
            q = get_hk_quote(code)
            if q and q.get("price"):
                return {
                    "code": q["code"],
                    "name": q.get("name", ""),
                    "price": q["price"],
                    "change": q.get("change"),
                    "change_pct": q.get("change_pct"),
                    "volume": None,
                    "high": q.get("high"),
                    "low": q.get("low"),
                }
        except Exception:
            pass
        return {"code": code, "error": "获取港股行情失败"}

    # 美股：akshare 东方财富美股接口
    if is_us_stock(code):
        try:
            from services.akshare_adapter import get_us_quote
            q = get_us_quote(code)
            if q and q.get("price"):
                return {
                    "code": q["code"],
                    "name": q.get("name", ""),
                    "price": q["price"],
                    "change": q.get("change"),
                    "change_pct": q.get("change_pct"),
                    "volume": q.get("volume"),
                    "high": q.get("high"),
                    "low": q.get("low"),
                }
        except Exception:
            pass
        return {"code": code, "error": "获取美股行情失败"}

    # A股：腾讯 API
    try:
        from services.akshare_adapter import get_quote
        q = get_quote(code)
        if q and q.get("price"):
            return {
                "code": q["code"],
                "name": q.get("name", ""),
                "price": q["price"],
                "change": q["change"],
                "change_pct": q["change_pct"],
                "volume": q.get("volume"),
                "high": q.get("high"),
                "low": q.get("low"),
            }
    except Exception:
        pass

    # 兜底：东方财富 API
    try:
        if market is None:
            market = get_market(code)
        secid = f"{market}.{code}"
        url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secid}&fields=f2,f3,f4,f5,f12,f14,f15,f16"
        data = json.loads(run_curl(url))
        diff = (data.get("data") or {}).get("diff") or []
        if diff:
            d = diff[0]
            return {
                "code": d.get("f12", code),
                "name": d.get("f14", ""),
                "price": d.get("f2"),
                "change": d.get("f4"),
                "change_pct": d.get("f3"),
                "volume": d.get("f5"),
                "high": d.get("f15"),
                "low": d.get("f16"),
            }
    except Exception as e:
        print(f"[Quote Error] {code}: {e}")
    return {"code": code, "error": "获取失败"}


def _fetch_quote_sync(code: str, market: str | None = None) -> dict:
    """获取单只股票实时行情（港股→新浪，美股→akshare，A股→vendor_router配置驱动）"""
    from services.utils import is_hk_stock, is_us_stock

    if is_hk_stock(code) or is_us_stock(code):
        return _fetch_quote_legacy(code, market)

    # A 股：配置驱动的多源 fallback（默认 futu → akshare）
    from services.vendor_router import route
    result = route("get_realtime_quote", code=code)
    if result.get("source") == "futu":
        return {
            "code": result["code"],
            "name": result.get("name", ""),
            "price": result.get("price"),
            "change": result.get("change"),
            "change_pct": result.get("change_pct"),
            "volume": result.get("volume"),
            "high": result.get("high_price"),
            "low": result.get("low_price"),
        }
    if "error" not in result:
        return result
    # 路由器全部失败，回退旧逻辑
    return _fetch_quote_legacy(code, market)


@router.get("/quote/{code}")
def get_quote(code: str):
    """单只股票/基金实时行情"""
    at = detect_asset_type(code)
    if at == "fund":
        nav = get_fund_nav(code)
        if nav:
            return {
                "code": code, "name": nav.get("name", ""),
                "price": nav.get("nav"), "est_nav": nav.get("est_nav"),
                "change_pct": nav.get("est_change_pct"),
                "nav_date": nav.get("nav_date"), "asset_type": "fund",
            }
        raise HTTPException(500, "获取基金净值失败")

    # ETF: 优先用天天基金净值（腾讯接口对部分ETF返回错误数据）
    if at == "etf":
        fund_info = get_fund_nav(code)
        # 如果是交易日盘中，用估算净值；非交易时间用单位净值
        est = fund_info.get("est_nav", 0) if fund_info else 0
        nav_val = fund_info.get("nav", 0) if fund_info else 0
        price = est if est > 0 else nav_val

    result = _cached_quote(code)
    if "error" in result:
        raise HTTPException(500, result["error"])

    # ETF: 用天天基金净值覆盖腾讯的假数据
    if at == "etf" and fund_info and price > 0:
        result["name"] = fund_info.get("name", result.get("name", ""))
        result["price"] = price
        result["nav"] = fund_info.get("nav")
        result["est_nav"] = fund_info.get("est_nav")

    return result


@router.get("/lookup/{code}")
def lookup(code: str):
    """输入代码自动查询：识别类型并返回名称、价格、涨跌幅"""
    at = detect_asset_type(code)

    # Try the most likely data source first, then fall back to the other
    try_quote_first = at in ("stock", "etf")

    q = _cached_quote(code) if try_quote_first else None
    nav = None if try_quote_first else get_fund_nav(code)

    if q and "error" not in q:
        # ETF: 检测假数据（腾讯 API 对部分 ETF 返回 name="北京XXXX" price=100.0）
        if at == "etf" and q.get("name", "").startswith("北京") and q.get("price") == 100.0:
            nav = get_fund_nav(code)
            if nav:
                return {"code": code, "name": nav.get("name", q.get("name", "")), "type": "etf",
                        "price": nav.get("nav"), "change_pct": nav.get("est_change_pct")}
        # ETF: 天天基金的名字更准确，优先使用
        name = q.get("name", "")
        if at == "etf":
            fund_info = get_fund_nav(code)
            if fund_info and fund_info.get("name"):
                name = fund_info["name"]
        return {"code": code, "name": name, "type": at,
                "price": q.get("price"), "change_pct": q.get("change_pct")}
    if nav:
        return {"code": code, "name": nav.get("name", ""), "type": "fund",
                "price": nav.get("nav"), "change_pct": nav.get("est_change_pct")}

    # Fallback: try the other source
    if try_quote_first:
        nav = get_fund_nav(code)
        if nav:
            fallback_type = at if at in ("etf", "stock") else "fund"
            return {"code": code, "name": nav.get("name", ""), "type": fallback_type,
                    "price": nav.get("nav"), "change_pct": nav.get("est_change_pct")}
    else:
        q = _cached_quote(code)
        if q and "error" not in q:
            name = q.get("name", "")
            at2 = "etf" if code.startswith(("51", "159", "588", "56")) else "stock"
            if at2 == "etf":
                fund_info = get_fund_nav(code)
                if fund_info and fund_info.get("name"):
                    name = fund_info["name"]
            return {"code": code, "name": name,
                    "type": at2,
                    "price": q.get("price"), "change_pct": q.get("change_pct")}

    raise HTTPException(404, f"未找到 {code} 的信息")


class BatchQuoteBody(BaseModel):
    codes: list[str]
    markets: list[str | None] | None = None  # 可选，与 codes 一一对应
    asset_types: list[str] | None = None  # 可选，与 codes 一一对应，用于区分基金


@router.post("/quotes")
def get_quotes_batch(body: BatchQuoteBody):
    """批量获取实时行情（优先 Futu 批量，不可用则本地 DB 兜底）"""
    # 快速路径：Futu 批量获取（300只/次，不阻塞）
    codes = body.codes
    if codes:
        # 先 healthcheck (1 秒 socket 探测), OpenD 不可达直接跳到本地兜底,
        # 避免 Futu SDK 内部死循环重试 (每 8 秒一次, 永不抛异常) 导致请求悬挂
        from services.futu_client import FutuClient
        futu = FutuClient()
        futu_ok = futu.healthcheck().get("ok", False)
        if futu_ok:
            try:
                results = []
                for i in range(0, len(codes), 300):
                    batch = codes[i:i+300]
                    for s in futu.get_snapshot(batch):
                        if "error" not in s:
                            results.append({
                                "code": s["code"], "name": s.get("name",""), "price": s.get("price"),
                                "change": s.get("change"), "change_pct": s.get("change_pct"),
                                "high": s.get("high_price"), "low": s.get("low_price"),
                                "open": s.get("open_price"), "volume": s.get("volume"),
                                "source": "futu",
                            })
                if results:
                    return results
            except Exception:
                pass
        # Futu 不可用：从本地 historical_kline 取最新收盘价
        from database import query_all
        results = []
        for code in codes:
            row = query_all(
                "SELECT close FROM historical_kline WHERE stock_code=? ORDER BY trade_date DESC LIMIT 1",
                (code,),
            )
            if row:
                results.append({"code": code, "name": "", "price": float(row[0]["close"]) if row[0]["close"] else 0, "source": "local"})
            else:
                results.append({"code": code, "error": "无数据", "source": "local"})
        return results

    # 以下为旧代码（fund 路径保留，基本不会走到）
    results = []
    for i, code in enumerate(body.codes):
        m = body.markets[i] if body.markets and i < len(body.markets) else None
        at = body.asset_types[i] if body.asset_types and i < len(body.asset_types) else ""
        if not at:
            at = detect_asset_type(code)

        if at == "fund":
            # 基金：走天天基金估值
            key = _cache_key(code, "fund")
            entry = _QUOTE_CACHE.get(key)
            if entry and time.time() < entry[0]:
                results.append(entry[1])
            else:
                nav = get_fund_nav(code)
                if nav:
                    result = {
                        "code": code,
                        "name": nav.get("name", ""),
                        "price": nav.get("nav"),
                        "est_nav": nav.get("est_nav"),
                        "change": round(nav.get("est_nav", 0) - nav.get("nav", 0), 4),
                        "change_pct": nav.get("est_change_pct"),
                        "high": None,
                        "low": None,
                        "volume": None,
                        "asset_type": "fund",
                        "nav_date": nav.get("nav_date"),
                    }
                else:
                    result = {"code": code, "error": "获取基金净值失败"}
                _QUOTE_CACHE[key] = (time.time() + 60, result)  # 基金缓存 60 秒
                results.append(result)
                time.sleep(0.2)  # 基金 API 限速
        else:
            # 股票/ETF：走东方财富行情；ETF 假数据兜底到天天基金净值
            key = _cache_key(code, m)
            entry = _QUOTE_CACHE.get(key)
            if entry and time.time() < entry[0]:
                results.append(entry[1])
            else:
                q = _fetch_quote_sync(code, m or None)
                # ETF：检测腾讯/东方财富返回的假数据，兜底到天天基金
                if at == "etf":
                    is_bad = ("error" in q or
                              (q.get("name", "").startswith("北京") and q.get("price") == 100.0) or
                              (q.get("name", "").startswith("重庆") and q.get("price") == 100.0))
                    if is_bad:
                        nav = get_fund_nav(code)
                        if nav:
                            q = {
                                "code": code,
                                "name": nav.get("name", q.get("name", "")),
                                "price": nav.get("nav"),
                                "est_nav": nav.get("est_nav"),
                                "change": round(nav.get("est_nav", 0) - nav.get("nav", 0), 4),
                                "change_pct": nav.get("est_change_pct"),
                                "high": None,
                                "low": None,
                                "volume": None,
                                "asset_type": "etf",
                                "nav_date": nav.get("nav_date"),
                            }
                results.append(q)
                _QUOTE_CACHE[key] = (time.time() + _CACHE_TTL, results[-1])
                time.sleep(0.3)
    return results


# ==================== 全球指数 ====================

_GLOBAL_INDICES = [
    {"code": "1.000001",  "name": "上证指数",       "region": "中国"},
    {"code": "0.399001",  "name": "深证成指",       "region": "中国"},
    {"code": "0.399006",  "name": "创业板指",       "region": "中国"},
    {"code": "100.HSI",   "name": "恒生指数",       "region": "中国香港"},
    {"code": "100.TWII",  "name": "台湾加权",       "region": "中国台湾"},
    {"code": "100.IXIC",  "name": "纳斯达克",       "region": "美国"},
    {"code": "100.INX",   "name": "标普500",        "region": "美国"},
    {"code": "100.DJI",   "name": "道琼斯",         "region": "美国"},
    {"code": "100.N225",  "name": "日经225",        "region": "日本"},
    {"code": "100.KS11",  "name": "韩国KOSPI",      "region": "韩国"},
    {"code": "100.FTSE",  "name": "英国富时100",    "region": "英国"},
    {"code": "100.GDAXI", "name": "德国DAX30",      "region": "德国"},
    {"code": "100.SENSEX","name": "印度SENSEX",     "region": "印度"},
    {"code": "100.BVSP",  "name": "巴西BOVESPA",    "region": "巴西"},
    {"code": "100.STI",   "name": "新加坡海峡时报", "region": "新加坡"},
]

_INDEX_CACHE_TTL = 5.0
_INDEX_BATCH_EXPIRY = 0.0
_INDEX_CACHED_DATA: list[dict] = []


@router.get("/indices/global")
def get_global_indices():
    """获取全球主要指数行情（东方财富 ulist 优先，AKShare 补充）"""
    global _INDEX_BATCH_EXPIRY, _INDEX_CACHED_DATA
    now = time.time()
    if _INDEX_CACHED_DATA and now < _INDEX_BATCH_EXPIRY:
        return _INDEX_CACHED_DATA

    results = []
    code_set: set[str] = set()

    # 1. 东方财富 ulist API — 覆盖全球15个主要指数
    try:
        secids = ",".join([idx["code"] for idx in _GLOBAL_INDICES])
        url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f14"
        data = json.loads(run_curl(url))
        diff_list = data.get("data", {}).get("diff", [])
        code_map = {idx["code"].split(".")[-1]: idx for idx in _GLOBAL_INDICES}
        for d in diff_list:
            code = d.get("f12", "")
            info = code_map.get(code)
            if info:
                code_set.add(code)
                results.append({
                    "code": code,
                    "name": info["name"],
                    "region": info["region"],
                    "price": d.get("f2"),
                    "change": d.get("f4"),
                    "change_pct": d.get("f3"),
                })
    except Exception as e:
        print(f"[Global Index Error] eastmoney: {e}")

    # 2. AKShare 补充 — 用腾讯 API 填充 eastmoney 缺失或不支持的数据
    try:
        from services.akshare_adapter import get_global_indices as ak_indices
        for item in ak_indices():
            code = item["code"]
            if code not in code_set and item.get("price") is not None:
                results.append(item)
    except Exception as e:
        print(f"[Global Index Error] akshare: {e}")

    # 3. 新浪财经补充 — 日经/富时/DAX/巴西等腾讯不覆盖的全球指数
    try:
        from services.sina_adapter import get_global_indices as sina_indices
        for item in sina_indices():
            code = item["code"]
            if code not in code_set and item.get("price") is not None:
                results.append(item)
                code_set.add(code)
    except Exception as e:
        print(f"[Global Index Error] sina: {e}")

    # 4. 兜底：对于没有任何数据源的指数，用 _GLOBAL_INDICES 作为占位
    for idx in _GLOBAL_INDICES:
        short_code = idx["code"].split(".")[-1]
        if short_code not in {r["code"] for r in results}:
            results.append({
                "code": short_code,
                "name": idx["name"],
                "region": idx["region"],
                "price": None,
                "change": None,
                "change_pct": None,
            })

    order_map = {idx["code"].split(".")[-1]: i for i, idx in enumerate(_GLOBAL_INDICES)}
    results.sort(key=lambda x: order_map.get(x["code"], 99))
    _INDEX_CACHED_DATA = results
    _INDEX_BATCH_EXPIRY = now + _INDEX_CACHE_TTL
    return results


# ==================== 技术指标 ====================

@router.get("/indicators/{code}")
def get_technical_indicators(code: str):
    """获取技术指标：MA/MACD/KDJ/RSI + 简要信号"""
    result = calc_indicators(code)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


class IndicatorInterpretBody(BaseModel):
    provider: str = ""  # 留空从 settings 读取
    apiKey: str = ""    # 留空从 settings 读取
    model: str = ""


@router.post("/indicators/{code}/interpret")
async def interpret_indicators(code: str, body: IndicatorInterpretBody):
    """AI 解读技术指标（apiKey 留空则使用已保存的配置）"""

    result = calc_indicators(code)
    if "error" in result:
        raise HTTPException(500, result["error"])

    prompt = f"""你是专业股票技术分析师。请根据以下技术指标数据，给出简洁的解读和操作建议。

股票: {result.get('name') or code} ({code})
最新价: {result['price']}
日期: {result['date']}

均线: MA5={result['MA'].get('MA5')}, MA10={result['MA'].get('MA10')}, MA20={result['MA'].get('MA20')}, MA60={result['MA'].get('MA60')}
MACD: DIF={result['MACD'].get('DIF')}, DEA={result['MACD'].get('DEA')}, 柱={result['MACD'].get('MACD')}
KDJ: K={result['KDJ'].get('K')}, D={result['KDJ'].get('D')}, J={result['KDJ'].get('J')}
RSI(14): {result['RSI']}

自动信号: {result['signal']}

要求：
1. 简要概括当前技术面状态（多头/空头/震荡）
2. 指出 1-2 个关键信号
3. 给出短线操作建议（一句话）
4. 不超过 200 字，直接输出不要标题"""

    try:
        interpretation = await ai_chat(
            prompt,
            function="watchdog",
            provider=body.provider,
            api_key=body.apiKey,
            model=body.model,
        )
    except AIServiceError as e:
        return {"error": str(e), "provider": e.provider_name}
    return {"interpretation": interpretation.strip()}



# ==================== 新闻 ====================


@router.get("/news/holdings")
def get_holdings_news():
    """获取持仓相关新闻（按行业+代码匹配）"""
    holdings = query_all("SELECT * FROM holdings WHERE user_id = ?", (get_current_user_id(),))
    if not holdings:
        return []
    return get_matched_news(holdings)


@router.get("/news/{code}")
def get_stock_news(code: str):
    """获取单只股票相关新闻"""
    articles = fetch_news_jsonp(code, page=1, page_size=10)
    return {"code": code, "news": articles}


# ==================== 交易记忆（复盘） ====================

@router.get("/memory/stats")
def get_memory_stats():
    """获取交易记忆统计摘要"""
    from services.review_service import get_memory_stats
    return get_memory_stats()


@router.get("/memory/entries")
def get_memory_entries(limit: int = 50):
    """获取交易记忆条目列表（最新在前）"""
    from services.review_service import get_memory_entries
    return get_memory_entries(limit=limit)


@router.get("/memory/context/{code}")
def get_memory_context(code: str):
    """获取某只股票的历史交易上下文（供 AI 分析使用）"""
    from services.trading_memory import TradingMemoryLog
    mem = TradingMemoryLog()
    ctx = mem.get_past_context(code, n_same=5, n_cross=3)
    return {"code": code, "context": ctx, "has_context": bool(ctx)}


# ═══════════════════════════════════════════════════════════
# 持仓详情 — K 线图表数据
# ═══════════════════════════════════════════════════════════

PERIOD_DAYS = {"5d": 5, "1m": 22, "3m": 66, "6m": 130}


def _aggregate_bars(dates: list[str], opens: list[float], highs: list[float],
                    lows: list[float], closes: list[float], volumes: list[float],
                    freq: str) -> tuple[list, list, list, list, list, list]:
    """将日线聚合成周线/月线"""
    if freq not in ("week", "month"):
        return dates, opens, highs, lows, closes, volumes

    groups: dict[str, dict] = {}
    for i in range(len(dates)):
        if freq == "week":
            # ISO week key
            key = dates[i][:7] if len(dates[i]) >= 7 else dates[i]
            from datetime import datetime as _dt
            try:
                d = _dt.strptime(dates[i], "%Y-%m-%d")
                key = f"{d.year}-W{d.isocalendar()[1]:02d}"
            except Exception:
                pass
        else:
            key = dates[i][:7]  # YYYY-MM

        if key not in groups:
            groups[key] = {"open": opens[i], "high": highs[i], "low": lows[i],
                           "close": closes[i], "volume": volumes[i], "date": dates[i]}
        else:
            g = groups[key]
            g["high"] = max(g["high"], highs[i])
            g["low"] = min(g["low"], lows[i])
            g["close"] = closes[i]
            g["volume"] += volumes[i]
            g["date"] = dates[i]

    keys = sorted(groups.keys())
    return (
        [groups[k]["date"] for k in keys],
        [groups[k]["open"] for k in keys],
        [groups[k]["high"] for k in keys],
        [groups[k]["low"] for k in keys],
        [groups[k]["close"] for k in keys],
        [groups[k]["volume"] for k in keys],
    )


@router.get("/kline/{code}")
def get_kline_data(code: str, period: str = "1m"):
    """获取 K 线数据（供持仓详情抽屉图表使用）

    period: 5d(5日) / 1m(日K,22天) / 3m(周K) / 6m(月K)
    返回: {dates, opens, highs, lows, closes, volumes, ma5, ma10, ma20}
    """
    from services.technical import fetch_kline, calc_ma

    if period not in PERIOD_DAYS:
        period = "1m"

    days = PERIOD_DAYS[period]
    mkt = get_market(code)

    def _legacy_daily_kline_for_chart() -> dict:
        return fetch_kline(code, mkt, days=max(days + 60, 120))

    if period == "1m":
        kline = get_minute_kline_with_fallback(
            code,
            count=max(days + 10, 60),
            fallback=_legacy_daily_kline_for_chart,
        )
    else:
        kline = _legacy_daily_kline_for_chart()

    if "error" in kline:
        raise HTTPException(500, kline["error"])

    dates = kline["dates"]
    opens = kline.get("opens", [])
    highs = kline["highs"]
    lows = kline["lows"]
    closes = kline["closes"]
    volumes = kline.get("volumes", [0] * len(closes))

    # 如果 fetch_kline 没返回 opens/volumes，用 closes 模拟
    if not opens:
        opens = [closes[0]] + closes[:-1]  # 用前日收盘当开盘
        opens = opens[:len(closes)]
    if not volumes or all(v == 0 for v in volumes):
        volumes = [0] * len(closes)

    # 聚合（周/月）
    freq = {"3m": "week", "6m": "month"}.get(period)
    if freq:
        dates, opens, highs, lows, closes, volumes = _aggregate_bars(
            dates, opens, highs, lows, closes, volumes, freq)

    # 截断到需要长度
    n = min(len(dates), days + 10)
    dates = dates[-n:]
    opens = opens[-n:]
    highs = highs[-n:]
    lows = lows[-n:]
    closes = closes[-n:]
    volumes = volumes[-n:]

    # MA 计算
    ma = calc_ma(closes, [5, 10, 20])
    ma5 = [round(v, 2) if v is not None else None for v in ma.get("MA5", [])][-n:]
    ma10 = [round(v, 2) if v is not None else None for v in ma.get("MA10", [])][-n:]
    ma20 = [round(v, 2) if v is not None else None for v in ma.get("MA20", [])][-n:]

    return {
        "code": code,
        "period": period,
        "dates": dates,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
    }


# ═══════════════════════════════════════════════════════════════
#  热点板块/资金 (2026-07-16 移除: akshare 接口全坏, 用户决定不需要)
# ═══════════════════════════════════════════════════════════════

@router.get("/hot-sectors")
def hot_sectors():
    """板块资金流向排名（单独调用）"""
    from services.akshare_adapter import get_sector_fund_flow
    return get_sector_fund_flow()


@router.get("/sync-status")
def sync_status():
    """本地数据源状态 — Futu连通性 + 各表最后同步时间"""
    from services.futu_client import FutuClient
    from database import query_one

    futu_ok = False
    try:
        hc = FutuClient().healthcheck()
        futu_ok = hc.get("ok", False)
    except Exception:
        pass

    # 各表最新数据时间
    tables = {}
    for table in ["local_fundamentals", "local_plate_daily", "historical_kline"]:
        try:
            row = query_one(f"SELECT MAX(trade_date) as dt FROM {table}")
            tables[table] = row["dt"] if row else None
        except Exception:
            tables[table] = None

    # 股票池统计
    from database import query_all
    watchlist_count = query_all("SELECT COUNT(*) as n FROM watchlist WHERE user_id = 1")[0]["n"]
    kline_count = query_all("SELECT COUNT(*) as n FROM historical_kline")[0]["n"]

    return {
        "futu_online": futu_ok,
        "tables": tables,
        "stats": {
            "watchlist": watchlist_count,
            "kline_rows": kline_count,
        },
        "message": "🟢 数据正常" if futu_ok else "🟡 Futu 离线，使用本地缓存",
    }


@router.post("/sync-fundamentals")
def trigger_fundamentals_sync():
    """手动触发基本面+板块同步（立即执行）"""
    from services.futu_sync_service import run_nightly_fundamentals
    result = run_nightly_fundamentals()
    return result
