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


def get_stock_factors(code: str) -> dict:
    """获取股票核心因子数据：PE/PB/ROE/市值/行业

    用于因子选股策略。数据来源 Baostock 最新财报 + 当前价格。
    """
    cache_key = f"factors:{code}"
    now = time.time()
    if cache_key in _FIN_CACHE:
        ts, data = _FIN_CACHE[cache_key]
        if now - ts < _FIN_TTL:
            return data

    result = {"code": code}

    with _bs_lock:
        if not _ensure_login():
            return {"error": "Baostock 登录失败", "code": code}

        sym = _bs_symbol(code)
        result["symbol"] = sym

        # 1. 行业分类
        try:
            rs = bs.query_stock_industry(sym)
            if rs.error_code == "0":
                while rs.next():
                    row = rs.get_row_data()
                    result["industry"] = row[2] if len(row) > 2 else ""
                    result["industry_type"] = row[3] if len(row) > 3 else ""
        except Exception:
            pass

        # 2. 最新利润表（eps, roe, net_profit, revenue, total_shares）
        try:
            import datetime
            year = datetime.date.today().year
            for y in (year, year - 1):
                rs = bs.query_profit_data(sym, year=y, quarter=4)
                if rs.error_code == "0":
                    while rs.next():
                        row = rs.get_row_data()
                        # 字段映射: [3]ROE(小数) [6]净利润 [7]EPS_TTM [8]营收 [9]总股本
                        roe_raw = _f(row[3]) if len(row) > 3 else None  # 小数，如 0.34 = 34%
                        result["roe"] = round(roe_raw * 100, 2) if roe_raw is not None else None
                        result["eps"] = _f(row[7]) if len(row) > 7 else None
                        result["net_profit"] = _f(row[6]) if len(row) > 6 else None
                        result["revenue"] = _f(row[8]) if len(row) > 8 else None
                        result["total_shares"] = _f(row[9]) if len(row) > 9 else None
                        break
                if "eps" in result:
                    break
        except Exception:
            pass

    # ── 以下计算不依赖 Baostock 连接，在锁外执行 ──

    # 4. 当前股价（从 K 线取最新收盘价）— get_kline 内部有自己的锁
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
