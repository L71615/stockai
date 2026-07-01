"""技术指标计算：MA / MACD / KDJ / RSI"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger("stockai")

from services.utils import run_curl, get_market

# ── K线数据源健康状态 ──
# 快速源（腾讯/东方财富）连续失败计数，超过阈值后直接使用 Baostock 兜底
_FAST_SOURCE_FAILS = 0
_FAST_SOURCE_SKIP_AFTER = 3
_FAST_SOURCE_CHECKED = False


def fetch_kline(code: str, market: str = None, days: int = 120) -> dict[str, Any]:
    """获取日K线数据（多市场适配：A股/港股/美股，多源兜底）

    A股: akshare(腾讯) → 东方财富 → Baostock
    港股: akshare(ak.stock_hk_hist) → 新浪
    美股: akshare(ak.stock_us_hist)
    """
    from services.utils import is_hk_stock, is_us_stock

    # ── 港股 K 线 ──
    if is_hk_stock(code):
        try:
            from services.akshare_adapter import get_hk_kline
            result = get_hk_kline(code, days)
            if result and "error" not in result:
                return result
        except Exception:
            logger.warning("technical: 港股K线获取失败 (%s)", code, exc_info=True)
        return {"error": "获取港股K线失败", "code": code}

    # ── 美股 K 线 ──
    if is_us_stock(code):
        try:
            from services.akshare_adapter import get_us_kline
            result = get_us_kline(code, days)
            if result and "error" not in result:
                return result
        except Exception:
            logger.warning("technical: 美股K线获取失败 (%s)", code, exc_info=True)
        return {"error": "获取美股K线失败", "code": code}

    # ── A 股 K 线（带数据源健康检测）──
    global _FAST_SOURCE_FAILS

    # 快速源已确认不可用 → 直接 Baostock
    if _FAST_SOURCE_FAILS >= _FAST_SOURCE_SKIP_AFTER:
        try:
            from services.baostock_adapter import get_kline as bs_kline
            result = bs_kline(code, days)
            if result and "error" not in result:
                return result
        except Exception:
            logger.warning("technical: Baostock K线获取失败 (%s)", code, exc_info=True)
        return {"error": "获取K线数据失败", "code": code}

    # 1. akshare / 腾讯财经（HTTP，无锁，可并发）
    try:
        from services.akshare_adapter import get_kline
        result = get_kline(code, days)
        if result and "error" not in result:
            return result
    except Exception:
        pass

    # 2. 新浪财经 JSON API（HTTP，无锁，可并发）
    try:
        from services.sina_adapter import get_kline as sina_kline
        result = sina_kline(code, days)
        if result and "error" not in result:
            return result
    except Exception:
        pass

    # 3. 东方财富 push2his（HTTP，无锁，可并发）
    if market is None:
        market = get_market(code)
    secid = f"{market}.{code}"
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&klt=101&fqt=1&lmt={days}&fields2=f51,f52,f53,f54,f55,f56,f57,f60"
    try:
        raw = run_curl(url)
        data = json.loads(raw)
        klines = data.get("data", {}).get("klines", []) or []
    except Exception:
        klines = []

    if klines:
        dates, closes, highs, lows = [], [], [], []
        for line in klines:
            parts = line.split(",")
            dates.append(parts[0])
            closes.append(float(parts[2]))
            highs.append(float(parts[3]))
            lows.append(float(parts[4]))
        return {
            "code": code, "dates": dates,
            "closes": closes, "highs": highs, "lows": lows,
        }

    # 两个快速源都失败了 → 标记并切换到 Baostock 兜底
    _FAST_SOURCE_FAILS += 1
    if _FAST_SOURCE_FAILS >= _FAST_SOURCE_SKIP_AFTER:
        logger.warning("technical: 腾讯/东方财富K线不可用，后续将直接使用Baostock")

    # 3. Baostock（查询级锁，最后兜底）
    try:
        from services.baostock_adapter import get_kline as bs_kline
        result = bs_kline(code, days)
        if result and "error" not in result:
            return result
    except Exception:
        logger.warning("technical: Baostock K线获取失败 (%s)", code, exc_info=True)

    return {"error": "获取K线数据失败", "code": code}


def _ema(data: list[float], period: int) -> list[float]:
    """指数移动平均"""
    result = []
    multiplier = 2 / (period + 1)
    for i, val in enumerate(data):
        if i == 0:
            result.append(val)
        elif i < period - 1:
            result.append(sum(data[:i + 1]) / (i + 1))
        else:
            result.append(val * multiplier + result[-1] * (1 - multiplier))
    return result


def calc_ma(closes: list[float], periods: list[int] = None) -> dict[str, list[float]]:
    """简单移动均线"""
    if periods is None:
        periods = [5, 10, 20, 60]
    result = {}
    for p in periods:
        ma = []
        for i in range(len(closes)):
            if i < p - 1:
                ma.append(None)
            else:
                ma.append(round(sum(closes[i - p + 1:i + 1]) / p, 2))
        result[f"MA{p}"] = ma
    return result


def calc_macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, list[float]]:
    """MACD 指标"""
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [round(ema_fast[i] - ema_slow[i], 3) for i in range(len(closes))]
    dea = _ema(dif, signal)
    bar = [round((dif[i] - dea[i]) * 2, 3) for i in range(len(closes))]
    return {"DIF": dif, "DEA": dea, "MACD": bar}


def calc_kdj(highs: list[float], lows: list[float], closes: list[float], n: int = 9) -> dict[str, list[float]]:
    """KDJ 指标"""
    k, d, j = [], [], []
    for i in range(len(closes)):
        if i < n - 1:
            k.append(None)
            d.append(None)
            j.append(None)
            continue
        hh = max(highs[i - n + 1:i + 1])
        ll = min(lows[i - n + 1:i + 1])
        rsv = (closes[i] - ll) / (hh - ll) * 100 if hh != ll else 50
        prev_k = k[-1] if k and k[-1] is not None else 50
        prev_d = d[-1] if d and d[-1] is not None else 50
        kv = prev_k * 2 / 3 + rsv / 3
        k.append(round(kv, 2))
        d.append(round(prev_d * 2 / 3 + kv / 3, 2))
        j.append(round(3 * kv - 2 * d[-1], 2))
    return {"K": k, "D": d, "J": j}


def calc_rsi(closes: list[float], period: int = 14) -> list[float]:
    """RSI 指标"""
    rsi = []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    for i in range(len(closes)):
        if i < period:
            rsi.append(None)
        else:
            avg_gain = sum(gains[i - period:i]) / period
            avg_loss = sum(losses[i - period:i]) / period
            if avg_loss == 0:
                rsi.append(100.0)
            elif avg_gain == 0:
                rsi.append(0.0)
            else:
                rsi.append(round(100 - 100 / (1 + avg_gain / avg_loss), 2))
    return rsi


def _latest(values: list[float]) -> float | None:
    valids = [v for v in values if v is not None]
    return round(valids[-1], 2) if valids else None


def _signal_summary(ma_map: dict, macd: dict, kdj: dict, rsi: list[float], closes: list[float]) -> str:
    """生成简要信号文字"""
    signals = []

    # 均线信号
    if ma_map.get("MA5") and ma_map.get("MA20"):
        ma5 = _latest(ma_map["MA5"])
        ma20 = _latest(ma_map["MA20"])
        ma5_prev = ma_map["MA5"][-2] if len(ma_map["MA5"]) > 1 else None
        ma20_prev = ma_map["MA20"][-2] if len(ma_map["MA20"]) > 1 else None
        if ma5 is not None and ma20 is not None and ma5 > ma20:
            if ma5_prev is not None and ma20_prev is not None and ma5_prev <= ma20_prev:
                signals.append("MA5 上穿 MA20（金叉信号）")
            else:
                signals.append("多头排列（MA5 > MA20）")
        elif ma5 is not None and ma20 is not None and ma5 < ma20:
            if ma5_prev is not None and ma20_prev is not None and ma5_prev >= ma20_prev:
                signals.append("MA5 下穿 MA20（死叉信号）")
            else:
                signals.append("空头排列（MA5 < MA20）")

    # MACD 信号
    if macd.get("DIF"):
        dif = _latest(macd["DIF"])
        dea = _latest(macd["DEA"])
        if dif is not None and dea is not None:
            dif_prev = macd["DIF"][-2] if len(macd["DIF"]) > 1 else None
            dea_prev = macd["DEA"][-2] if len(macd["DEA"]) > 1 else None
            if dif_prev is not None and dea_prev is not None:
                if dif_prev <= dea_prev and dif > dea:
                    signals.append("MACD 金叉")
                elif dif_prev >= dea_prev and dif < dea:
                    signals.append("MACD 死叉")
            if dif > 0:
                signals.append("MACD 位于零轴上方（偏多）")
            else:
                signals.append("MACD 位于零轴下方（偏空）")

    # KDJ 信号
    if kdj.get("K") and kdj.get("D"):
        k_val = _latest(kdj["K"])
        d_val = _latest(kdj["D"])
        if k_val is not None and d_val is not None:
            k_prev = kdj["K"][-2] if len(kdj["K"]) > 1 else None
            d_prev = kdj["D"][-2] if len(kdj["D"]) > 1 else None
            if k_prev is not None and d_prev is not None:
                if k_prev <= d_prev and k_val > d_val:
                    signals.append("KDJ 金叉")
                elif k_prev >= d_prev and k_val < d_val:
                    signals.append("KDJ 死叉")
            if k_val > 80:
                signals.append("KDJ 超买区（>80）")
            elif k_val < 20:
                signals.append("KDJ 超卖区（<20）")

    # RSI 信号
    if rsi:
        rsi_val = _latest(rsi)
        if rsi_val is not None:
            if rsi_val > 70:
                signals.append(f"RSI({rsi_val}) 超买")
            elif rsi_val < 30:
                signals.append(f"RSI({rsi_val}) 超卖")
            else:
                signals.append(f"RSI({rsi_val}) 中性")

    # 价格位置
    if ma_map.get("MA60") and closes:
        ma60 = _latest(ma_map["MA60"])
        price = closes[-1]
        if ma60 and price:
            if price > ma60:
                signals.append("股价位于 MA60 上方（中长期偏多）")
            else:
                signals.append("股价位于 MA60 下方（中长期偏空）")

    return "；".join(signals) if signals else "无明显技术信号"


def get_indicators(code: str, market: str = None, days: int = 120) -> dict:
    """一站式返回所有技术指标"""
    kline = fetch_kline(code, market, days)
    if "error" in kline:
        return kline

    closes = kline["closes"]
    highs = kline["highs"]
    lows = kline["lows"]

    ma = calc_ma(closes)
    macd = calc_macd(closes)
    kdj = calc_kdj(highs, lows, closes)
    rsi = calc_rsi(closes)

    # 取最新值
    indicators = {
        "code": code,
        "name": "",
        "price": closes[-1] if closes else None,
        "date": kline["dates"][-1] if kline["dates"] else None,
        "MA": {k: _latest(v) for k, v in ma.items()},
        "MACD": {k: _latest(v) for k, v in macd.items()},
        "KDJ": {k: _latest(v) for k, v in kdj.items()},
        "RSI": _latest(rsi),
        "signal": _signal_summary(ma, macd, kdj, rsi, closes),
        # 保留最近 60 个数据点给前端画简易走势
        "recent": {
            "dates": kline["dates"][-60:],
            "closes": kline["closes"][-60:],
        },
    }

    # 尝试获取名称
    try:
        from services.akshare_adapter import get_stock_name
        name = get_stock_name(code)
        if name:
            indicators["name"] = name
        else:
            m = market or get_market(code)
            raw = run_curl(f"https://push2.eastmoney.com/api/qt/stock/get?secid={m}.{code}&fields=f58")
            indicators["name"] = json.loads(raw).get("data", {}).get("f58", "")
    except Exception:
        logger.warning("technical: 获取股票名称失败 (%s)", code, exc_info=True)

    return indicators
