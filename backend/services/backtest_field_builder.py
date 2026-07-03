"""回测字段构建器 — 从历史 K 线数据构建 condition_engine 所需的 stock_data dict

纯函数模块，无副作用，可被回测引擎和实时选股共用。

关键原则：
- 输入是 {dates, opens, highs, lows, closes, volumes} 格式的 K 线数据
- 输出是 condition_engine.evaluate() 能直接使用的 stock_data dict
- 所有字段都必须从 K 线数据中计算，不调用任何外部 API
- 序列字段以 _seq 后缀存储（用于 cross_above/cross_below 操作符）
"""

import logging

logger = logging.getLogger(__name__)


def build_stock_data(kline: dict) -> dict:
    """从 K 线数据构建完整的 stock_data dict

    Args:
        kline: {dates, opens, highs, lows, closes, volumes} — 已按时间升序排列

    Returns:
        stock_data dict，包含所有 screener.py LAYER4_FIELDS 对应的字段
        以及 _seq 后缀的序列版本
    """
    closes = kline.get("closes", [])
    highs = kline.get("highs", [])
    lows = kline.get("lows", [])
    volumes = kline.get("volumes", [])
    opens = kline.get("opens", [])

    if len(closes) < 20:
        logger.warning("backtest_field_builder: insufficient data (%d bars)", len(closes))
        return {"error": "数据不足，需要至少 20 根 K 线"}

    sd = {}

    # ── 基础价格 ──
    price = closes[-1]
    sd["close"] = price
    sd["open"] = opens[-1] if opens else price
    sd["high"] = highs[-1] if highs else price
    sd["low"] = lows[-1] if lows else price

    # ── 均线 MA5/MA10/MA20/MA60 ──
    _build_ma_fields(sd, closes)

    # ── 均线交叉字段（ma5_vs_ma10, close_vs_ma20, close_vs_ma60）──
    # 这些字段由 condition_engine 的 _field_vs_field 通过 compare_field 机制自动处理
    # 只需要提供基础字段（close, ma5, ma10, ma20, ma60）即可

    # ── 高低点参考 ──
    if len(highs) >= 21:
        sd["high_20d"] = round(max(highs[-21:-1]), 2)
    if len(highs) >= 56:
        sd["high_55d"] = round(max(highs[-56:-1]), 2)
    if len(lows) >= 6:
        sd["low_5d"] = round(min(lows[-6:-1]), 2)

    # ── RSI(14) ──
    sd["rsi_14_seq"] = _calc_rsi(closes, 14)
    sd["rsi_14"] = _latest(sd["rsi_14_seq"])

    # ── MACD ──
    macd_data = _calc_macd(closes)
    sd["dif_seq"] = macd_data.get("DIF", [])
    sd["dea_seq"] = macd_data.get("DEA", [])
    sd["dif"] = _latest(sd["dif_seq"])
    sd["dea"] = _latest(sd["dea_seq"])
    # 简化字段：DIF 是否在 DEA 之上（用于 macd_dif_dea 字段 > 0 判断）
    sd["macd_dif_dea_seq"] = [
        round(dif - dea, 4) if dif is not None and dea is not None else None
        for dif, dea in zip(macd_data.get("DIF", []), macd_data.get("DEA", []))
    ]
    sd["macd_dif_dea"] = _latest(sd["macd_dif_dea_seq"])

    # ── 量比 / 日均成交额 ──
    if volumes and len(volumes) >= 20:
        valid_v = [v for v in volumes[-21:-1] if v is not None]
        vm = sum(valid_v) / len(valid_v) if valid_v else 0
        sd["vol_ratio"] = round(volumes[-1] / vm, 2) if vm > 0 and volumes[-1] is not None else 1.0
        amounts = []
        for i in range(min(len(volumes), len(closes))):
            v = volumes[i]
            c = closes[i]
            if v is not None and c is not None:
                amounts.append(v * c)
        sd["avg_amount_20d"] = sum(amounts[-20:]) / min(len(amounts), 20) if amounts else 0
    else:
        sd["vol_ratio"] = 1.0
        sd["avg_amount_20d"] = 0

    # ── 布林带位置 ──
    if len(closes) >= 20:
        bb_ma = sum(closes[-20:]) / 20
        bb_std = (sum((c - bb_ma) ** 2 for c in closes[-20:]) / 20) ** 0.5
        bb_upper = bb_ma + 2 * bb_std
        bb_lower = bb_ma - 2 * bb_std
        sd["boll_position"] = round(
            (price - bb_lower) / (bb_upper - bb_lower), 3
        ) if bb_upper != bb_lower else 0.5
    else:
        sd["boll_position"] = 0.5

    # ── 动量因子（百分比）──
    sd["ret_5d"] = round(_ret_n(closes, 5) * 100, 2) if _ret_n(closes, 5) is not None else None
    sd["ret_20d"] = round(_ret_n(closes, 20) * 100, 2) if _ret_n(closes, 20) is not None else None

    # ── ATR 百分比 ──
    atr_val = _calc_atr(highs, lows, closes, 20)
    sd["atr_pct"] = round(atr_val / price * 100, 2) if atr_val and price > 0 else None

    # ── 20日相对强度 ──
    sd["strength_20d"] = round(
        (price / closes[-20] - 1) * 100, 2
    ) if len(closes) >= 20 and closes[-20] > 0 else None

    # ── 序列版本（用于 cross_above/cross_below）──
    # MA 序列已在 _build_ma_fields 中添加
    # close 序列
    sd["close_seq"] = closes
    sd["open_seq"] = opens

    return sd


def _build_ma_fields(sd: dict, closes: list[float]) -> None:
    """计算 MA5/MA10/MA20/MA60 及其序列"""
    mas = _calc_mas(closes, [5, 10, 20, 60])
    for period, ma_seq in mas.items():
        key = f"ma{period}"
        sd[f"{key}_seq"] = ma_seq
        sd[key] = _latest(ma_seq)


# ═══════════════════════════════════════════════════════════════
#  技术指标纯函数（不依赖外部 API）
# ═══════════════════════════════════════════════════════════════


def _latest(values: list[float]) -> float | None:
    """获取序列最新有效值"""
    valids = [v for v in values if v is not None]
    return round(valids[-1], 2) if valids else None


def _calc_mas(closes: list[float], periods: list[int]) -> dict[int, list[float]]:
    """计算多个周期的简单移动均线"""
    result = {}
    for p in periods:
        ma = []
        for i in range(len(closes)):
            if i < p - 1:
                ma.append(None)
            else:
                ma.append(round(sum(closes[i - p + 1:i + 1]) / p, 2))
        result[p] = ma
    return result


def _calc_rsi(closes: list[float], period: int = 14) -> list[float]:
    """计算 RSI 序列"""
    rsi = []
    gains = []
    losses = []
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


def _calc_macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, list[float]]:
    """计算 MACD 指标"""
    def _ema(data, period):
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

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [round(ema_fast[i] - ema_slow[i], 3) for i in range(len(closes))]
    dea = _ema(dif, signal)
    bar = [round((dif[i] - dea[i]) * 2, 3) for i in range(len(closes))]
    return {"DIF": dif, "DEA": dea, "MACD": bar}


def _calc_atr(highs: list[float], lows: list[float], closes: list[float],
              period: int = 20) -> float | None:
    """计算 ATR（平均真实波幅）"""
    if len(closes) < period + 1:
        return None
    tr_list = []
    for i in range(1, len(closes)):
        if highs[i] is None or lows[i] is None or closes[i - 1] is None:
            continue
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        tr_list.append(max(high_low, high_close, low_close))
    if len(tr_list) < period:
        return None
    return round(sum(tr_list[-period:]) / period, 4)


def _ret_n(closes: list[float], n: int) -> float | None:
    """N 日收益率"""
    if len(closes) < n + 1:
        return None
    try:
        return round((closes[-1] - closes[-n - 1]) / closes[-n - 1], 6)
    except (TypeError, ZeroDivisionError):
        return None
