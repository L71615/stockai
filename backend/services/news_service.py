"""新闻搜索 + 行业匹配服务

数据源：东方财富搜索 API（search-api-web.eastmoney.com，JSONP）
行业分类：push2 API f127（申万行业二级分类）
"""

import json
import logging
import re
import time
import urllib.parse

from services.utils import run_curl, get_market

logger = logging.getLogger("stockai")

# 新闻缓存（15 分钟 TTL）
_NEWS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_NEWS_CACHE_TTL = 900

# 行业缓存（1 小时 TTL）
_INDUSTRY_CACHE: dict[str, tuple[float, dict]] = {}
_INDUSTRY_CACHE_TTL = 3600


def _industry_keyword(industry_raw: str) -> str:
    """从行业名称提取搜索关键词（去除罗马数字后缀）"""
    if not industry_raw:
        return ""
    return re.sub(r'[Ⅰ-Ⅻ]+$', '', industry_raw).strip()


def get_industry(code: str, market: str | None = None) -> dict | None:
    """获取单只股票的行业分类信息（带缓存）
    优先 AKShare，东方财富 API 兜底（VM 上可能 TLS 指纹不通）。
    """
    if market is None:
        market = get_market(code)

    now = time.time()
    cache_key = f"{market}.{code}"
    if cache_key in _INDUSTRY_CACHE:
        ts, data = _INDUSTRY_CACHE[cache_key]
        if now - ts < _INDUSTRY_CACHE_TTL:
            return data

    # 优先 AKShare adapter
    try:
        from services.akshare_adapter import get_stock_info
        result = get_stock_info(code)
        if result and result.get("industry"):
            _INDUSTRY_CACHE[cache_key] = (now, result)
            return result
    except Exception:
        logger.warning("news_service: akshare get_stock_info failed for %s", code, exc_info=True)

    # 兜底：东方财富 API
    try:
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={cache_key}&fields=f57,f58,f127,f128,f129"
        raw = run_curl(url)
        d = json.loads(raw).get("data")
        if d and d.get("f57"):
            result = {
                "code": d["f57"],
                "name": d.get("f58", ""),
                "industry": d.get("f127", ""),
                "region": d.get("f128", ""),
                "concepts": d.get("f129", ""),
            }
            _INDUSTRY_CACHE[cache_key] = (now, result)
            return result
    except Exception as e:
        print(f"[Industry Error] {code}: {e}")
    return None


def fetch_news_jsonp(keyword: str, page: int = 1, page_size: int = 5) -> list[dict]:
    """搜索东方财富新闻（JSONP API）"""
    param = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": page,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        }
    }
    param_str = json.dumps(param, separators=(",", ":"))
    encoded = urllib.parse.quote(param_str, safe="")
    url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param={encoded}"

    try:
        raw = run_curl(url)
        m = re.search(r'jQuery\((.+)\)\s*$', raw, re.DOTALL)
        if not m:
            print(f"[News Error] JSONP parse failed: {raw[:200]}")
            return []
        data = json.loads(m.group(1))
        articles = data.get("result", {}).get("cmsArticleWebOld", [])
        results = []
        for a in articles:
            results.append({
                "title": a.get("title", ""),
                "date": a.get("date", ""),
                "source": a.get("mediaName", ""),
                "url": a.get("url", a.get("content", "")),
            })
        # 按日期降序排列（东方财富 API sort 参数不总是生效）
        results.sort(key=lambda x: x.get("date", ""), reverse=True)
        # 只保留最近 5 天的新闻
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=5)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        results = [r for r in results if r.get("date", "") >= cutoff_str]
        return results
    except Exception as e:
        print(f"[News Error] keyword={keyword}: {e}")
        return []


def _fetch_news_cached(keyword: str, page: int = 1, page_size: int = 5) -> list[dict]:
    """带缓存的新闻搜索"""
    cache_key = f"news:{keyword}:{page}:{page_size}"
    now = time.time()
    if cache_key in _NEWS_CACHE:
        ts, data = _NEWS_CACHE[cache_key]
        if now - ts < _NEWS_CACHE_TTL:
            return data

    articles = fetch_news_jsonp(keyword, page, page_size)
    _NEWS_CACHE[cache_key] = (now, articles)
    time.sleep(0.5)  # 速率控制
    return articles


def get_matched_news(holdings: list[dict]) -> list[dict]:
    """根据持仓列表获取行业+代码匹配的新闻"""
    if not holdings:
        return []

    # 按行业去重：同一行业只查一次
    industry_map: dict[str, list[dict]] = {}
    for h in holdings:
        code = h.get("stock_code", "")
        market_val = h.get("market", "")
        # 标准化市场格式
        if market_val and len(market_val) > 1:
            market_val = "1" if market_val.startswith("SH") else "0"

        ind = get_industry(code, market_val)
        kw = _industry_keyword(ind.get("industry", "")) if ind else ""

        if kw:
            if kw not in industry_map:
                industry_map[kw] = []
            industry_map[kw].append({
                "code": code,
                "name": ind.get("name", h.get("stock_name", "")),
                "industry": kw,
            })

    # 按行业搜索新闻
    results: list[dict] = []
    seen_urls: set[str] = set()

    for ind_kw, stocks in industry_map.items():
        articles = _fetch_news_cached(ind_kw, page=1, page_size=5)

        for stock in stocks:
            # 也按股票代码搜索 2 条
            code_news = _fetch_news_cached(stock["code"], page=1, page_size=2)

            merged = []
            for n in articles + code_news:
                url = n.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    merged.append(n)

            results.append({
                "stock_code": stock["code"],
                "stock_name": stock["name"],
                "industry": stock["industry"],
                "news": merged[:5],
            })

    return results
