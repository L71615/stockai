"""股市数据路由 — 行情 / 指数 / 技术指标 / 新闻 / AI复盘 / 预警"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute
from services.news_service import get_matched_news, fetch_news_jsonp, _industry_keyword
from services.ai_service import ai_chat
from services.technical import get_indicators as calc_indicators
from services.utils import run_curl, get_market, detect_asset_type, get_fund_nav

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


def _fetch_quote_sync(code: str, market: str | None = None) -> dict:
    """获取单只股票实时行情（港股→新浪，A股→腾讯→东方财富）"""
    from services.utils import is_hk_stock

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
    """批量获取实时行情（股票走东方财富，基金走天天基金估值）"""
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

    interpretation = await ai_chat(
        prompt,
        provider=body.provider,
        api_key=body.apiKey,
        model=body.model,
    )
    return {"interpretation": interpretation.strip()}


# ==================== 新闻 ====================

# 全球区域 → 新闻搜索关键词映射
_REGION_KEYWORDS = {
    "us":       "美股 美联储 纳斯达克",
    "ca":       "加拿大 央行 多伦多",
    "br":       "巴西 股市 Bovespa",
    "mx":       "墨西哥 经济",
    "uk":       "英国 央行 富时100",
    "de":       "德国 DAX 欧洲央行",
    "fr":       "法国 CAC40 欧洲",
    "jp":       "日本 日经225 央行",
    "kr":       "韩国 KOSPI",
    "in":       "印度 股市 Sensex",
    "au":       "澳大利亚 澳洲联储",
    "hk":       "港股 恒生指数",
    "cn":       "A股 上证指数",
    "ae":       "中东 沙特 阿联酋",
    "za":       "南非 非洲经济",
    "sg":       "东南亚 东盟 新加坡",
    "ru":       "俄罗斯 MOEX 卢布",
    "sa":       "沙特 石油 OPEC",
    "it":       "意大利 欧洲经济",
    "es":       "西班牙 IBEX 欧洲",
}


@router.get("/news/global/{region}")
def get_global_news(region: str):
    """获取全球区域财经新闻"""
    keyword = _REGION_KEYWORDS.get(region)
    if not keyword:
        raise HTTPException(404, f"未知区域: {region}")
    articles = fetch_news_jsonp(keyword, page=1, page_size=15)
    return {"region": region, "keyword": keyword, "news": articles}


@router.get("/news/holdings")
def get_holdings_news():
    """获取持仓相关新闻（按行业+代码匹配）"""
    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1")
    if not holdings:
        return []
    return get_matched_news(holdings)


@router.get("/news/{code}")
def get_stock_news(code: str):
    """获取单只股票相关新闻"""
    articles = fetch_news_jsonp(code, page=1, page_size=10)
    return {"code": code, "news": articles}


# ==================== AI 复盘 ====================

class ReviewRequest(BaseModel):
    provider: str = ""    # 留空从 settings 读取
    apiKey: str = ""      # 留空从 settings 读取
    model: str = ""
    period: str = "all"   # all / month / quarter / year


_PERIOD_CONFIG = {
    "month":   ("本月",   "AND traded_at >= date('now','localtime','start of month')"),
    "quarter": ("本季度", "AND traded_at >= date('now','localtime','start of year','+' || (cast((strftime('%m','now')-1)/3 as int)*3) || ' months')"),
    "year":    ("本年",   "AND traded_at >= date('now','localtime','start of year')"),
    "all":     ("全部",   ""),
}


@router.post("/review")
async def generate_review(body: ReviewRequest):
    """AI 复盘：读取交易记录，生成盈亏分析报告（apiKey 留空则使用已保存的配置）"""

    period_label, period_filter = _PERIOD_CONFIG.get(body.period, ("全部", ""))

    txs = query_all(f"SELECT * FROM transactions WHERE user_id = 1 {period_filter} ORDER BY traded_at ASC")
    if not txs:
        return {"review": f"暂无{period_label}交易记录，无法生成复盘报告。"}

    # 按股票分组
    stock_txs: dict[str, list[dict]] = {}
    for t in txs:
        code = t["stock_code"]
        if code not in stock_txs:
            stock_txs[code] = []
        stock_txs[code].append(t)

    # 聚合统计
    total_buy_amount = 0.0
    total_sell_amount = 0.0
    buy_count = 0
    sell_count = 0
    stock_summaries = []

    for code, trades in stock_txs.items():
        name = trades[0]["stock_name"] or code
        buys = [t for t in trades if t["direction"] == "buy"]
        sells = [t for t in trades if t["direction"] == "sell"]

        buy_total = sum(t["amount"] for t in buys)
        sell_total = sum(t["amount"] for t in sells)
        buy_shares = sum(t["quantity"] for t in buys)
        sell_shares = sum(t["quantity"] for t in sells)

        # 已卖出部分的盈亏（FIFO 简化）
        realized_pnl = 0.0
        if buys and sells:
            avg_buy_price = buy_total / buy_shares if buy_shares > 0 else 0
            sold_qty = min(sell_shares, buy_shares)
            realized_pnl = sum(t["amount"] for t in sells) - sold_qty * avg_buy_price

        remaining = buy_shares - sell_shares

        stock_summaries.append({
            "name": name,
            "code": code,
            "buy_count": len(buys),
            "sell_count": len(sells),
            "total_buy": f"{buy_total:.2f}",
            "total_sell": f"{sell_total:.2f}",
            "realized_pnl": f"{realized_pnl:+.2f}",
            "remaining_shares": remaining,
            "trades": [f"{t['direction']} {t['quantity']}股@{t['price']:.2f} {t['traded_at'][:10]}" for t in trades],
        })

        total_buy_amount += buy_total
        total_sell_amount += sell_total
        buy_count += len(buys)
        sell_count += len(sells)

    total_pnl = total_sell_amount - total_buy_amount

    # 构造 prompt
    lines = [
        f"## {period_label}交易统计",
        f"- 总买入: {buy_count} 笔，共 {total_buy_amount:.2f} 元",
        f"- 总卖出: {sell_count} 笔，共 {total_sell_amount:.2f} 元",
        f"- 已实现盈亏: {total_pnl:+.2f} 元",
        "",
        "## 各股票明细",
    ]
    for s in stock_summaries:
        lines.append(f"\n### {s['name']}（{s['code']}）")
        lines.append(f"- 买入 {s['buy_count']} 笔共 {s['total_buy']} 元，卖出 {s['sell_count']} 笔共 {s['total_sell']} 元")
        lines.append(f"- 已实现盈亏: {s['realized_pnl']} 元，剩余持仓: {s['remaining_shares']} 股")
        for t in s["trades"]:
            lines.append(f"  - {t}")

    data_text = "\n".join(lines)

    prompt = f"""你是专业股票交易复盘分析师。请根据以下交易数据，生成一份复盘报告。

{data_text}

要求：
1. 先总结总体盈亏情况
2. 逐只股票分析交易表现
3. 指出做得好的和可以改进的地方
4. 给出 2-3 条具体的改进建议
5. 语言简洁专业，不超过 500 字
6. 直接输出报告正文，不要加"复盘报告"等标题"""

    review = await ai_chat(
        prompt,
        provider=body.provider,
        api_key=body.apiKey,
        model=body.model,
    )

    return {"review": review.strip()}


# ==================== 分散度分析 ====================

def _classify_fund(name: str, code: str) -> tuple[str, str]:
    """根据基金名称和代码分类，返回 (分类, 市场区域)"""
    n = name or ""
    c = code or ""
    # QDII 分类
    if "纳斯达克" in n or "纳指" in n:
        return ("美股科技", "美股")
    if "标普500" in n or "标普" in n:
        return ("美股大盘", "美股")
    if "全球精选" in n or "全球" in n:
        return ("全球股票", "全球")
    # 行业/主题分类（场内外均适用）
    if "机器人" in n:
        return ("AI/机器人", "A股")
    if "卫星" in n or "航天" in n or "军工" in n:
        return ("航天军工", "A股")
    if "电力" in n or "公用" in n or "绿色" in n:
        return ("公用事业", "A股")
    if "A500" in n or "沪深300" in n or "上证50" in n or "中证500" in n:
        return ("A股宽基", "A股")
    if "业绩驱动" in n or "混合" in n or "灵活" in n:
        return ("主动混合", "A股")
    if c.startswith("0") and len(c) == 6:
        return ("其他基金", "A股")
    return ("其他", "未知")

@router.get("/diversification")
def get_diversification():
    """持仓分散度分析：行业占比、市场占比、集中风险"""
    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1")
    if not holdings:
        return {"by_industry": [], "by_market": [], "risk_level": "无持仓", "max_single_pct": 0}

    # 同时获取行情数据（含估值）
    results = []
    total_value = 0.0
    for h in holdings:
        at = h.get("asset_type", "")
        mkt = get_market(h["stock_code"])
        name = h.get("stock_name", "")

        if at in ("fund", "etf"):
            # 基金/ETF：用天天基金净值（腾讯接口对部分ETF返回假数据）
            nav_info = get_fund_nav(h["stock_code"])
            price = (nav_info.get("est_nav") or nav_info.get("nav")) if nav_info else h["cost_price"]
            cat, region = _classify_fund(name, h["stock_code"])
            ind_raw = cat
        else:
            q = _cached_quote(h["stock_code"], mkt)
            if q and "error" not in q:
                price = q.get("price") or h["cost_price"]
                ind_raw = q.get("industry", "")
                region = q.get("region", "")
            else:
                price = h["cost_price"]
                ind_raw = ""
                region = ""

        mv = price * (h.get("shares") or h.get("quantity") or 0)
        total_value += mv
        results.append({
            "code": h["stock_code"],
            "name": name,
            "industry": _industry_keyword(ind_raw) if ind_raw and at not in ("fund", "etf") else (cat if at in ("fund", "etf") else ""),
            "region": region,
            "market": h.get("market", ""),
            "market_value": mv,
        })

    if total_value == 0:
        return {"by_industry": [], "by_market": [], "risk_level": "无数据", "max_single_pct": 0}

    # 按行业聚合
    industry_map: dict[str, dict] = {}
    for r in results:
        kw = r["industry"] or "未分类"
        if kw not in industry_map:
            industry_map[kw] = {"name": kw, "count": 0, "market_value": 0.0}
        industry_map[kw]["count"] += 1
        industry_map[kw]["market_value"] += r["market_value"]

    by_industry = sorted(industry_map.values(), key=lambda x: x["market_value"], reverse=True)
    for item in by_industry:
        item["pct"] = round(item["market_value"] / total_value * 100, 1)
        item["market_value"] = round(item["market_value"], 2)

    # 按市场聚合（基金/ETF用分类区域，股票用交易所）
    market_map: dict[str, dict] = {}
    for r in results:
        mkt = r.get("region") or r["market"] or "未知"
        mkt_label = {"SH": "上海", "SZ": "深圳", "BJ": "北京",
                     "美股": "美股", "A股": "A股", "全球": "全球"}.get(mkt, mkt)
        if mkt_label not in market_map:
            market_map[mkt_label] = {"name": mkt_label, "count": 0, "market_value": 0.0}
        market_map[mkt_label]["count"] += 1
        market_map[mkt_label]["market_value"] += r["market_value"]

    by_market = sorted(market_map.values(), key=lambda x: x["market_value"], reverse=True)
    for item in by_market:
        item["pct"] = round(item["market_value"] / total_value * 100, 1)
        item["market_value"] = round(item["market_value"], 2)

    # 风险等级
    max_single = max(r["market_value"] for r in results) / total_value * 100
    max_ind_pct = by_industry[0]["pct"] if by_industry else 0
    if max_ind_pct > 60 or len(holdings) <= 1:
        risk = "集中"
    elif max_ind_pct > 40 or len(holdings) <= 2:
        risk = "适中"
    else:
        risk = "分散"

    return {
        "by_industry": by_industry,
        "by_market": by_market,
        "risk_level": risk,
        "max_single_pct": round(max_single, 1),
    }


# ==================== 大盘对比 ====================

@router.get("/peer-comparison")
def get_peer_comparison():
    """持仓 vs 大盘指数对比（仅股票和ETF，基金不参与）"""
    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1 AND asset_type IN ('stock', 'etf', '')")
    if not holdings:
        return {"items": [], "indices": {}}

    # 获取三大指数行情
    sh_idx = _cached_quote("000001", "1")
    sz_idx = _cached_quote("399001", "0")
    bj_idx = _cached_quote("899050", "0")

    indices = {}
    for idx, key in [(sh_idx, "sh"), (sz_idx, "sz"), (bj_idx, "bj")]:
        if idx and "error" not in idx:
            indices[key] = f"{idx.get('name', '')} {idx.get('change_pct', 0):+.2f}%"

    items = []
    for h in holdings:
        mkt = get_market(h["stock_code"])
        bench = sh_idx if mkt == "1" else sz_idx
        bench_name = bench.get("name", "上证指数" if mkt == "1" else "深证成指") if bench and "error" not in bench else ("上证指数" if mkt == "1" else "深证成指")
        bench_pct = bench.get("change_pct", 0) if bench and "error" not in bench else 0

        q = _cached_quote(h["stock_code"], mkt)
        if q and "error" not in q:
            my_pct = q.get("change_pct") or 0
            excess = round(my_pct - bench_pct, 2)
            items.append({
                "code": h["stock_code"],
                "name": h["stock_name"],
                "my_pct": my_pct,
                "bench_name": bench_name,
                "bench_pct": bench_pct,
                "excess": excess,
                "tag": "跑赢" if excess > 0 else ("持平" if excess == 0 else "跑输"),
            })

    return {"items": items, "indices": indices}


# ==================== 价格预警 ====================

class AlertBody(BaseModel):
    stock_code: str
    alert_type: str      # above / below / pct_change
    target_value: float


@router.get("/alerts")
def list_alerts():
    return query_all("SELECT * FROM price_alerts WHERE user_id = 1 ORDER BY id DESC")


@router.post("/alerts")
def add_alert(body: AlertBody):
    # 同股同类型去重
    existing = query_one(
        "SELECT id FROM price_alerts WHERE user_id = 1 AND stock_code = ? AND alert_type = ?",
        (body.stock_code, body.alert_type),
    )
    if existing:
        execute("DELETE FROM price_alerts WHERE id = ?", (existing["id"],))
    result = execute(
        "INSERT INTO price_alerts (user_id, stock_code, alert_type, target_value) VALUES (1, ?, ?, ?)",
        (body.stock_code, body.alert_type, body.target_value),
    )
    return {"id": result["lastrowid"], "message": "预警已设置"}


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int):
    execute("DELETE FROM price_alerts WHERE id = ? AND user_id = 1", (alert_id,))
    return {"message": "已删除"}


# ==================== 股息记录 ====================

class DividendBody(BaseModel):
    stock_code: str
    stock_name: str = ""
    amount_per_share: float
    ex_date: str
    total_amount: float
    note: str = ""


@router.get("/dividends")
def list_dividends():
    return query_all("SELECT * FROM dividends WHERE user_id = 1 ORDER BY ex_date DESC")


@router.post("/dividends")
def add_dividend(body: DividendBody):
    result = execute(
        """INSERT INTO dividends (user_id, stock_code, stock_name, amount_per_share, ex_date, total_amount, note)
           VALUES (1, ?, ?, ?, ?, ?, ?)""",
        (body.stock_code, body.stock_name, body.amount_per_share, body.ex_date, body.total_amount, body.note),
    )
    return {"id": result["lastrowid"], "message": "已记录"}


@router.delete("/dividends/{div_id}")
def delete_dividend(div_id: int):
    execute("DELETE FROM dividends WHERE id = ? AND user_id = 1", (div_id,))
    return {"message": "已删除"}


@router.get("/dividends/summary")
def dividends_summary():
    """股息汇总：总股息、按股票汇总"""
    rows = query_all(
        """SELECT stock_code, stock_name, SUM(total_amount) as total_div
           FROM dividends WHERE user_id = 1
           GROUP BY stock_code ORDER BY total_div DESC"""
    )
    total = sum(r["total_div"] for r in rows)
    return {"total_dividends": total, "by_stock": rows}


# ==================== AI 复盘（结构化） ====================

class StructuredReviewRequest(BaseModel):
    report_type: str = "daily"   # daily / weekly / monthly
    user_id: int = 1
    provider: str = ""           # 留空从 settings 读取
    api_key: str = ""            # 留空从 settings 读取
    model: str = ""


@router.post("/review/structured")
async def generate_review_structured(body: StructuredReviewRequest):
    """生成结构化 AI 复盘报告"""
    from services.review_service import generate_review_report

    report = await generate_review_report(
        user_id=body.user_id,
        provider=body.provider,
        api_key=body.api_key,
        model=body.model,
    )
    return report


@router.get("/reviews")
def list_reviews(user_id: int = 1, limit: int = 20, offset: int = 0):
    """返回历史复盘报告列表，最新的在前"""
    return query_all(
        """SELECT id, report_type, period_start, period_end, transactions_count,
                  summary, score_data, created_at
           FROM review_reports
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (user_id, limit, offset),
    )


@router.get("/reviews/{review_id}")
def get_review(review_id: int):
    """返回单条历史复盘报告的完整数据"""
    import json as _json
    from database import query_one

    row = query_one(
        """SELECT id, report_type, period_start, period_end, transactions_count,
                  score_data, ai_response, summary, created_at
           FROM review_reports
           WHERE id = ?""",
        (review_id,),
    )
    if not row:
        return {"error": "报告不存在"}

    report = {
        "id": row["id"],
        "report_type": row["report_type"],
        "transactions_count": row["transactions_count"],
        "summary": row["summary"] or "",
        "created_at": str(row["created_at"]) if row["created_at"] else "",
    }

    # Parse dimensions and suggestions from stored AI response
    raw = row["ai_response"] or ""
    if raw:
        from services.review_service import parse_review_response
        parsed = parse_review_response(raw)
        report["dimensions"] = parsed.get("dimensions", [])
        report["suggestions"] = parsed.get("suggestions", [])
    else:
        report["dimensions"] = []
        report["suggestions"] = []

    # Parse score_data
    score_data = row.get("score_data") or "{}"
    try:
        scores = _json.loads(score_data) if isinstance(score_data, str) else score_data
    except (_json.JSONDecodeError, TypeError):
        scores = {}
    report["avg_score"] = round(sum(scores.values()) / len(scores)) if scores else 0

    return report
