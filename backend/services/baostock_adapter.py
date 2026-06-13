"""数据适配层 — Baostock（证券宝），免费历史K线 + 财报数据

Baostock 无需注册、无调用频率限制、历史数据覆盖 2005 年至今。
缺点是无实时行情，所以本适配器只提供历史K线和基本面数据，
实时行情仍走腾讯 API（akshare_adapter.py）。

文档: http://baostock.com
"""

import time
import threading
import logging
from typing import Optional

import baostock as bs

logger = logging.getLogger(__name__)

# ==================== 线程安全 ====================
# Baostock 使用全局连接，多线程并发调用会死锁或数据错乱。
# 所有 Baostock API 调用必须持有此锁。

_bs_lock = threading.RLock()  # 可重入锁，防止同一线程内嵌套调用自死锁

# ==================== 缓存 ====================

_KLINE_CACHE: dict[str, tuple[float, dict]] = {}
_KLINE_TTL = 300.0  # 历史K线缓存 5 分钟

_logged_in = False


def _ensure_login():
    """幂等登录，首次调用自动 login，后续复用连接。需在 _bs_lock 持有下调用。"""
    global _logged_in
    if not _logged_in:
        lg = bs.login()
        if lg.error_code != "0":
            logger.warning(f"Baostock login failed: {lg.error_msg}")
            return False
        _logged_in = True
    return True


# ==================== 符号转换 ====================

def _bs_symbol(code: str) -> str:
    """A股代码 → Baostock 格式: 600519 → sh.600519, 300750 → sz.300750"""
    c = code.strip()
    if c.startswith(("60", "68")):
        return f"sh.{c}"
    return f"sz.{c}"


# ==================== K 线 ====================

def get_kline(code: str, days: int = 252, freq: str = "d") -> dict:
    """获取日K线历史数据（Baostock，前复权）

    Args:
        code: 股票代码，如 "600519"
        days: 获取最近多少天的数据（默认 252 = 约1年）
        freq: 频率 "d"=日线, "w"=周线, "m"=月线

    Returns:
        {"code": str, "dates": [...], "opens": [...], "closes": [...],
         "highs": [...], "lows": [...], "volumes": [...]}
        失败返回 {"error": str, "code": str}
    """
    cache_key = f"{code}:{days}:{freq}"
    now = time.time()
    if cache_key in _KLINE_CACHE:
        ts, data = _KLINE_CACHE[cache_key]
        if now - ts < _KLINE_TTL:
            return data

    with _bs_lock:
        if not _ensure_login():
            return {"error": "Baostock 登录失败", "code": code}

        sym = _bs_symbol(code)
        try:
            rs = bs.query_history_k_data_plus(
                sym,
                "date,open,high,low,close,volume,amount,adjustflag",
                frequency=freq,
                adjustflag="2",  # 前复权
            )
            if rs.error_code != "0":
                return {"error": rs.error_msg, "code": code}

            dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
            while rs.next():
                row = rs.get_row_data()
                if not row or row[0] == "":
                    continue
                dates.append(row[0])
                opens.append(_f(row[1]))
                highs.append(_f(row[2]))
                lows.append(_f(row[3]))
                closes.append(_f(row[4]))
                volumes.append(_f(row[5]))

            if not closes:
                return {"error": "无K线数据", "code": code}

            # 截取最近 days 条
            result = {
                "code": code,
                "dates": dates[-days:],
                "opens": opens[-days:],
                "highs": highs[-days:],
                "lows": lows[-days:],
                "closes": closes[-days:],
                "volumes": volumes[-days:],
                "source": "baostock",
            }
            _KLINE_CACHE[cache_key] = (now, result)
            return result

        except Exception as e:
            logger.warning(f"get_kline({code}): {e}")
            return {"error": f"Baostock K线获取失败: {e}", "code": code}


# ==================== 股票基本信息 ====================

_STOCK_BASIC_CACHE: dict[str, tuple[float, dict]] = {}
_STOCK_BASIC_TTL = 86400.0  # 基本信息缓存 24 小时


def get_stock_basic(code: str) -> Optional[dict]:
    """获取股票基本信息（名称、行业、上市日期等）"""
    now = time.time()
    if code in _STOCK_BASIC_CACHE:
        ts, data = _STOCK_BASIC_CACHE[code]
        if now - ts < _STOCK_BASIC_TTL:
            return data

    with _bs_lock:
        if not _ensure_login():
            return None

        sym = _bs_symbol(code)
        try:
            rs = bs.query_stock_basic(sym)
            if rs.error_code != "0":
                return None

            while rs.next():
                row = rs.get_row_data()
                result = {
                    "code": row[0],
                    "name": row[1],
                    "ipo_date": row[2],
                    "type": row[3],  # 1=股票 2=指数 3=其他
                    "status": row[4],  # 1=上市 0=退市
                }
                _STOCK_BASIC_CACHE[code] = (now, result)
                return result
        except Exception as e:
            logger.warning(f"get_stock_basic({code}): {e}")

    return None


# ==================== 财务数据（因子量化） ====================

_FIN_CACHE: dict[str, tuple[float, dict]] = {}
_FIN_TTL = 7200.0  # 财务数据缓存 2 小时

# 全局行业分类缓存（一次查询全市场，避免逐只 Baostock 调用）
_INDUSTRY_CACHE: dict[str, dict] = {}
_INDUSTRY_TTL = 86400.0  # 24 小时
_industry_ts = 0.0


def _get_industry_map() -> dict[str, dict]:
    """获取全市场行业分类映射表（全局缓存 24 小时）
    Returns: {code: {industry, industry_type}}
    """
    global _INDUSTRY_CACHE, _industry_ts
    now = time.time()
    if _INDUSTRY_CACHE and (now - _industry_ts) < _INDUSTRY_TTL:
        return _INDUSTRY_CACHE

    with _bs_lock:
        if not _ensure_login():
            return _INDUSTRY_CACHE or {}
        try:
            rs = bs.query_stock_industry()
            if rs.error_code == "0":
                new_map: dict[str, dict] = {}
                while rs.next():
                    row = rs.get_row_data()
                    code = row[1].replace("sh.", "").replace("sz.", "")
                    new_map[code] = {
                        "industry": row[2] if len(row) > 2 else "",
                        "industry_type": row[3] if len(row) > 3 else "",
                    }
                _INDUSTRY_CACHE = new_map
                _industry_ts = now
        except Exception:
            pass
    return _INDUSTRY_CACHE


def _bs_locked(fn):
    """在 Baostock 锁内执行 fn()，自动确保登录。fn 在锁保护下运行。"""
    with _bs_lock:
        if not _ensure_login():
            return None
        return fn()


def get_stock_factors(code: str) -> dict:
    """获取股票核心因子数据：PE/ROE/市值/行业 + prev_eps + dividend

    用于因子选股策略。数据来源 Baostock 最新财报 + 当前价格。
    返回 prev_eps（去年同期EPS）和 dividend（每股分红）供因子计算使用。

    锁策略：每个独立 Baostock 查询单独加锁，查询间隙释放锁让其他线程执行。
    """
    cache_key = f"factors:{code}"
    now = time.time()
    if cache_key in _FIN_CACHE:
        ts, data = _FIN_CACHE[cache_key]
        if now - ts < _FIN_TTL:
            return data

    result = {"code": code}

    sym = _bs_symbol(code)
    result["symbol"] = sym

    # 1. 行业分类（全局缓存，无需锁）
    try:
        ind_map = _get_industry_map()
        if code in ind_map:
            result.update(ind_map[code])
    except Exception:
        pass

    # 2. 利润表（当年 → 去年 → 前年，Q4→Q1 逐季回退，每次查询独立加锁）
    try:
        import datetime
        year = datetime.date.today().year

        def _query_latest_row(target_year: int) -> tuple[list | None, int]:
            """查询某年最新报表（Q4→Q1），每次调用独立加锁"""
            def _do():
                for q in (4, 3, 2, 1):
                    rs = bs.query_profit_data(sym, year=target_year, quarter=q)
                    if rs.error_code == "0":
                        while rs.next():
                            return (rs.get_row_data(), q)
                return (None, 0)
            return _bs_locked(_do)

        def _extract_financials(row: list, quarter: int) -> dict:
            """从 Baostock 利润表行提取字段，季报 ROE 自动年化"""
            roe_raw = _f(row[3]) if len(row) > 3 else None
            roe_pct = round(roe_raw * 100, 2) if roe_raw is not None else None
            if roe_pct is not None and quarter != 4:
                factors = {1: 4.0, 2: 2.0, 3: 4.0 / 3.0}
                roe_pct = round(roe_pct * factors.get(quarter, 1.0), 2)
            return {
                "roe": roe_pct,
                "eps": _f(row[7]) if len(row) > 7 else None,
                "net_profit": _f(row[6]) if len(row) > 6 else None,
                "revenue": _f(row[8]) if len(row) > 8 else None,
                "total_shares": _f(row[9]) if len(row) > 9 else None,
            }

        # 2a. 逐级回退取主财务数据
        fin = {}
        for y_offset in (0, 1, 2):
            row, qtr = _query_latest_row(year - y_offset)
            if row:
                fin = _extract_financials(row, qtr)
                result.update(fin)
                break

        # 2b. 往前取 prev_eps
        if "eps" in result and result["eps"] is not None:
            eps_found = False
            for y_offset in (0, 1, 2):
                row, _ = _query_latest_row(year - y_offset)
                if row and _f(row[7]) == result["eps"]:
                    prev_row, _ = _query_latest_row(year - y_offset - 1)
                    if prev_row:
                        prev_eps = _f(prev_row[7]) if len(prev_row) > 7 else None
                        if prev_eps is not None and prev_eps != 0:
                            result["prev_eps"] = prev_eps
                            eps_found = True
                    if not eps_found:
                        prev_row, _ = _query_latest_row(year - y_offset - 2)
                        if prev_row:
                            prev_eps = _f(prev_row[7]) if len(prev_row) > 7 else None
                            if prev_eps is not None and prev_eps != 0:
                                result["prev_eps"] = prev_eps
                    break
    except Exception:
        pass

    # 3. 分红数据（每年独立加锁查询）
    try:
        import datetime
        year = datetime.date.today().year
        for y in (year, year - 1, year - 2):
            def _query_div():
                rs = bs.query_dividend_data(sym, year=y, yearType="report")
                if rs.error_code == "0":
                    while rs.next():
                        row = rs.get_row_data()
                        div = _f(row[9]) if len(row) > 9 else None
                        if div is not None and div > 0:
                            return div
                return None

            div = _bs_locked(_query_div)
            if div is not None:
                result["dividend"] = div
                break
    except Exception:
        pass

    # 4. 真实 PB（从 K 线 pbMRQ 字段，独立加锁）
    try:
        import datetime as _dt
        today = _dt.date.today()
        start = (today - _dt.timedelta(days=30)).strftime("%Y-%m-%d")

        def _query_pb():
            rs = bs.query_history_k_data_plus(sym, "date,pbMRQ", frequency="d",
                                               adjustflag="2", start_date=start)
            if rs.error_code == "0":
                while rs.next():
                    row = rs.get_row_data()
                    pb = _f(row[1]) if len(row) > 1 else None
                    if pb is not None and pb > 0:
                        return pb
            return None

        pb = _bs_locked(_query_pb)
        if pb is not None:
            result["pb"] = pb
    except Exception:
        pass

    # ── 以下不依赖 Baostock 连接 ──

    # 5. 当前股价（get_kline 内部已自己管理锁）
    try:
        kline = get_kline(code, days=5)
        if "error" not in kline and kline.get("closes"):
            result["price"] = kline["closes"][-1]
    except Exception:
        pass

    # 5. 计算 PE / 市值
    price = result.get("price")
    eps = result.get("eps")
    total_shares = result.get("total_shares")
    if price and eps and eps > 0:
        result["pe"] = round(price / eps, 2)
    if price and total_shares and total_shares > 0:
        result["market_cap"] = round(price * total_shares, 2)
        result["market_cap_billion"] = round(price * total_shares / 1e8, 2)  # 亿

    _FIN_CACHE[cache_key] = (now, result)
    return result


def get_factors_batch(codes: list[str]) -> dict[str, dict]:
    """批量获取多只股票的因子数据"""
    results = {}
    for code in codes:
        results[code] = get_stock_factors(code)
    return results


# ==================== 辅助 ====================

def _f(val) -> Optional[float]:
    """安全转 float"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
