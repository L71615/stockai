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


def is_us_stock(code: str) -> bool:
    """判断是否为美股代码：纯字母（如 AAPL, TSLA, GOOGL）"""
    c = code.strip()
    return bool(re.match(r'^[A-Za-z]+$', c)) and len(c) <= 5



def detect_asset_type(code: str) -> str:
    """根据代码前缀自动识别资产类型：stock / etf / fund / hk"""
    c = code.strip()
    # 港股：5位数字以0开头（如 00700, 09988）
    if len(c) == 5 and c.startswith("0") and c.isdigit():
        return "stock"  # 港股股票
    # 美股：纯字母代码（如 AAPL, TSLA, GOOGL）
    if is_us_stock(c):
        return "us_stock"
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


def detect_market_status(code: str) -> str:
    """检测股票所属市场的交易状态

    Returns: "open" (盘中) / "closed" (已收盘) / "pre" (盘前) / "unknown"
    基于北京时间判断，简化版（不处理节假日）。
    """
    from datetime import datetime, time

    now = datetime.now()
    t = now.time()
    wd = now.weekday()  # 0=Mon, 6=Sun

    if wd >= 5:
        return "closed"

    if is_us_stock(code):
        if time(22, 0) <= t or t <= time(5, 0):
            return "open"
        if time(17, 0) <= t < time(22, 0):
            return "pre"
        return "closed"

    if is_hk_stock(code) or (len(code.strip()) == 5 and code.strip().startswith("0")):
        if time(9, 30) <= t <= time(12, 0) or time(13, 0) <= t <= time(16, 0):
            return "open"
        if time(9, 0) <= t < time(9, 30):
            return "pre"
        return "closed"

    # A 股：9:30-11:30, 13:00-15:00
    if time(9, 30) <= t <= time(11, 30) or time(13, 0) <= t <= time(15, 0):
        return "open"
    if time(9, 0) <= t < time(9, 30):
        return "pre"
    return "closed"


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


def parse_ai_json(raw: str) -> dict:
    """通用 AI JSON 响应解析器——渐进降级

    5 步降级策略：
    1. 去 markdown 代码块包裹
    2. 直接 json.loads
    3. 正则截取首个 {} 片段再解析
    4. 修复常见 JSON 错误（缺逗号等）后再解析
    5. 降级——返回 raw 原文

    返回: 解析成功的 dict，或 {"raw": raw, "parse_error": True}
    """
    if not raw or not raw.strip():
        return {"raw": "", "parse_error": True}

    text = raw.strip()

    # Step 1: Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Step 2: Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Step 3: Extract JSON fragment between { and }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Step 4: Repair common errors
    if match:
        repaired = match.group(0)
        repaired = re.sub(r'\}\s*"', '}, "', repaired)   # missing comma after }
        repaired = re.sub(r'\]\s*"', '], "', repaired)   # missing comma after ]
        repaired = re.sub(r'"\s+"', '", "', repaired)    # missing comma between strings
        repaired = re.sub(r'(\d+)\s+"', r'\1, "', repaired)  # missing comma after number
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # Step 5: Fallback — return raw text
    return {"raw": raw, "parse_error": True}


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


# ==================== 交易手续费 ====================

from dataclasses import dataclass

@dataclass
class FeeConfig:
    commission_rate: float = 0.00025   # 佣金 0.025%
    commission_min: float = 5.0        # 最低佣金 5 元
    transfer_fee_rate: float = 0.00002 # 过户费 0.002%
    stamp_tax_rate: float = 0.0005     # 印花税 0.05%（仅卖出）


def get_fee_config() -> FeeConfig:
    """从 settings 表读取手续费配置，未配置时返回默认值"""
    try:
        from database import query_one
        import json as _json
        row = query_one("SELECT value FROM settings WHERE key = 'fee_config'")
        if row and row.get("value"):
            data = _json.loads(row["value"])
            return FeeConfig(
                commission_rate=float(data.get("commission_rate", FeeConfig.commission_rate)),
                commission_min=float(data.get("commission_min", FeeConfig.commission_min)),
            )
    except Exception:
        pass
    return FeeConfig()


def save_fee_config(cfg: FeeConfig) -> None:
    """保存手续费配置到 settings 表"""
    from database import execute
    import json as _json
    execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('fee_config', ?)",
        (_json.dumps({"commission_rate": cfg.commission_rate, "commission_min": cfg.commission_min}),),
    )


def calc_fee(price: float, quantity: float, direction: str, asset_type: str) -> float | None:
    """计算 A 股交易手续费。fund/hk 返回 None（需手动输入）。

    规则：
      Stock 买入: 佣金 max(费率 * 金额, 最低) + 过户费 0.002% * 金额
      Stock 卖出: 以上 + 印花税 0.05% * 金额
      ETF 买/卖:  佣金 max(费率 * 金额, 最低)，无印花税/过户费
      Fund / HK:  返回 None

    费率从 settings 表 fee_config 读取，默认 0.025% / 最低 5 元。
    """
    at = (asset_type or "").strip().lower()

    if at in ("fund", "hk"):
        return None

    amount = abs(price * quantity)
    if amount <= 0:
        return 0.0

    cfg = get_fee_config()

    if at == "etf":
        commission = max(amount * cfg.commission_rate, cfg.commission_min)
        return round(commission, 2)

    # Stock：佣金 + 过户费 + (卖出时) 印花税
    commission = max(amount * cfg.commission_rate, cfg.commission_min)
    transfer_fee = amount * FeeConfig.transfer_fee_rate
    fee = commission + transfer_fee

    if direction == "sell":
        stamp_tax = amount * FeeConfig.stamp_tax_rate
        fee += stamp_tax

    return round(fee, 2)
