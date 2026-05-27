"""StockAI 共享工具函数"""

import json
import re
import subprocess
import time
from datetime import datetime

def run_curl(url: str, referer: str = "https://quote.eastmoney.com/") -> str:
    """执行 curl 请求，绕过东方财富 TLS 指纹检测，返回响应文本"""
    result = subprocess.run([
        "curl", "-s", "--compressed",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-H", f"Referer: {referer}",
        "--connect-timeout", "5", "--max-time", "10",
        url,
    ], capture_output=True, encoding="utf-8", timeout=12)
    return result.stdout


def get_market(code: str) -> str:
    """从股票代码推断市场：1=上海，0=深圳"""
    return "1" if code.startswith(("60", "68")) else "0"


def normalize_market(code: str) -> str:
    """返回面向用户的市场标签：SH / SZ / BJ"""
    if code.startswith(("60", "68")):
        return "SH"
    if code.startswith(("00", "30", "39")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def to_eastmoney_secid(code: str) -> str:
    """转为东方财富 secid 格式 {market}.{code}"""
    return f"{get_market(code)}.{code}"



def detect_asset_type(code: str) -> str:
    """根据代码前缀自动识别资产类型：stock / etf / fund"""
    # ETF 前缀（沪市 51xxxx, 58xxxx; 深市 159xxx, 56xxxx）
    if code.startswith(("510", "511", "512", "513", "514", "515", "516", "517", "518",
                        "159", "588", "560", "561", "562", "563", "564", "565", "566",
                        "567", "568", "569")):
        return "etf"
    # 明确是股票的前缀：上海 60/68，深圳创业板 30，深圳中小板 002
    if code.startswith(("60", "68", "30", "002")):
        return "stock"
    # 00 开头可能是基金也可能是深市主板股票，默认当基金（用户可手动改）
    if code.startswith("00"):
        return "fund"
    return "fund"


def search_stock(keyword: str) -> list[dict]:
    """搜索股票/基金代码或名称，返回匹配列表 [{code, name, market, asset_type}]"""
    # 优先 AKShare（VM 上 TLS 指纹问题导致东方财富 API 不通）
    try:
        from services.akshare_adapter import search_stock as ak_search
        results = ak_search(keyword)
        if results:
            return results
    except Exception:
        pass

    # 兜底：东方财富搜索 API
    try:
        from config import EASTMONEY_TOKEN
        raw = run_curl(
            f"https://searchapi.eastmoney.com/api/suggest/get?"
            f"input={keyword}&type=14&token={EASTMONEY_TOKEN}&count=8",
            referer="https://www.eastmoney.com/",
        )
        data = json.loads(raw)
        results = []
        for item in data.get("QuotationCodeTable", {}).get("Data", []):
            code = item.get("Code", "")
            name = item.get("Name", "")
            mkt = item.get("MktNum", "")
            if not code or not name:
                continue
            market = normalize_market(code)
            at = detect_asset_type(code)
            results.append({"code": code, "name": name, "market": market, "asset_type": at})
        return results
    except Exception:
        return []


_FUND_CACHE: dict[str, tuple[float, dict]] = {}
_FUND_CACHE_TTL = 60.0  # 基金净值 60 秒缓存


def get_fund_nav(code: str) -> dict | None:
    """获取基金净值（天天基金估算接口，仅对普通基金有意义）"""
    now = time.time()
    if code in _FUND_CACHE:
        ts, data = _FUND_CACHE[code]
        if now - ts < _FUND_CACHE_TTL:
            return data

    try:
        raw = run_curl(
            f"https://fundgz.1234567.com.cn/js/{code}.js",
            referer="https://fund.eastmoney.com/",
        )
        m = re.search(r'jsonpgz\((.+)\)', raw)
        if m:
            d = json.loads(m.group(1))
            result = {
                "code": d.get("fundcode", code),
                "name": d.get("name", ""),
                "nav": float(d.get("dwjz", 0)),       # 单位净值
                "est_nav": float(d.get("gsz", 0)),     # 估算净值
                "est_change_pct": float(d.get("gszzl", 0)),  # 估算涨跌幅
                "nav_date": d.get("jzrq", ""),         # 净值日期
            }
            _FUND_CACHE[code] = (now, result)
            return result
    except Exception:
        pass
    return None


def calc_xirr(cash_flows: list[tuple[str, float]]) -> float | None:
    """XIRR 年化收益率。cash_flows: [(date_str, amount), ...]，负=投入，正=收回"""
    if not cash_flows or all(cf[1] >= 0 for cf in cash_flows):
        return None

    dates = []
    amounts = []
    for cf in cash_flows:
        try:
            d = datetime.strptime(cf[0][:10], "%Y-%m-%d")
        except ValueError:
            continue
        dates.append(d)
        amounts.append(cf[1])

    if len(amounts) < 2:
        return None

    t0 = dates[0]
    years = [(d - t0).days / 365.25 for d in dates]

    def _try_solve(guess: float) -> float | None:
        rate = guess
        for _ in range(200):
            npv = 0.0
            dnpv = 0.0
            for y, amt in zip(years, amounts):
                disc = (1.0 + rate) ** y
                npv += amt / disc
                if y > 0:
                    dnpv += -y * amt / (disc * (1.0 + rate))
            if abs(dnpv) < 1e-9:
                break
            delta = npv / dnpv
            new_rate = rate - delta
            if isinstance(new_rate, complex) or abs(new_rate - rate) < 1e-6:
                rate = new_rate
                break
            rate = new_rate
        if isinstance(rate, complex):
            return None
        if rate <= -1.0 or rate > 100.0:
            return None
        return round(rate.real if isinstance(rate, complex) else rate, 4)

    # Try multiple initial guesses
    for guess in (0.1, 0.0, -0.5, 0.5, 0.01, -0.9):
        result = _try_solve(guess)
        if result is not None:
            return result
    return None
