"""StockAI 共享工具函数"""

import json
import re
import subprocess
import time
from datetime import datetime

def run_curl(url: str, referer: str = "https://quote.eastmoney.com/", retries: int = 2) -> str:
    """执行 curl 请求，返回响应文本

    - 强制 IPv4（东方财富 IPv6 不通）
    - 失败时自动重试（最多 retries 次）
    """
    last_stdout = ""
    for attempt in range(retries):
        result = subprocess.run([
            "curl", "-4", "-s", "--compressed",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "-H", f"Referer: {referer}",
            "--connect-timeout", "8", "--max-time", "15",
            url,
        ], capture_output=True, encoding="utf-8", timeout=20)
        last_stdout = result.stdout
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        if attempt < retries - 1:
            time.sleep(0.5)

    return last_stdout


def get_market(code: str) -> str:
    """从股票代码推断市场：1=上海，0=深圳，116=港股"""
    c = code.strip()
    if c.startswith(("60", "68")):
        return "1"
    # 港股：5位数字以0开头（如 00700, 09988）
    if len(c) == 5 and c.startswith("0") and c.isdigit():
        return "116"
    return "0"


def is_hk_stock(code: str) -> bool:
    """判断是否为港股代码：5位数字以0开头"""
    c = code.strip()
    return len(c) == 5 and c.startswith("0") and c.isdigit()



def detect_asset_type(code: str) -> str:
    """根据代码前缀自动识别资产类型：stock / etf / fund / hk"""
    c = code.strip()
    # 港股：5位数字以0开头（如 00700, 09988）
    if len(c) == 5 and c.startswith("0") and c.isdigit():
        return "stock"  # 港股股票
    # ETF 前缀（沪市 51xxxx, 58xxxx; 深市 159xxx, 56xxxx）
    if c.startswith(("510", "511", "512", "513", "514", "515", "516", "517", "518",
                     "159", "588", "560", "561", "562", "563", "564", "565", "566",
                     "567", "568", "569")):
        return "etf"
    # 明确是股票的前缀：上海 60/68，深圳创业板 30，深圳中小板 002
    if c.startswith(("60", "68", "30", "002")):
        return "stock"
    # 00 开头6位=深市主板股票（如 000001），其余=基金
    if c.startswith("00"):
        if len(c) == 6 and c.isdigit():
            return "stock"
        return "fund"
    return "fund"


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
