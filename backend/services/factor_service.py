"""因子计算引擎：10大类57因子，从 qlib Alpha158 精选

因子体系：
  价格(9): ma5/10/20/60, price_position, high_low_ratio, close_open_ratio, typical_price, weighted_close
  动量(10): ret_5d/20d/60d, rsi_14, macd_signal, ma_disposition, momentum_5/10/20, acceleration, momentum_composite
  波动(9): hist_vol_5d/20d, atr_14, amplitude_20d, downside_vol, boll_upper/lower/position, volatility_ratio, bb_width
  成交量(6): vol_ma5/10/20, vol_ratio, vol_std, price_volume_corr
  量价(3): turnover_rate, obv_divergence, avg_amount
  基本面(11): pe, pb, roe, eps_growth, market_cap, dividend_yield, ps_ttm, debt_ratio, gross_margin, revenue_growth, net_profit_growth
  情绪(2): strength_20d, momentum_composite
  资金(2): north_flow, inst_change
  技术指标(3): rsi, macd, boll_upper/lower/position 归入对应类别

所有函数自己消化异常 —— NaN/inf → None，调用方收到 None 时跳过该因子。
"""

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _ema(data: list[float], period: int) -> list[float]:
    """指数移动平均"""
    if len(data) < 2:
        return data[:]
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


def _returns(prices: list[float]) -> list[float]:
    """价格序列 → 日收益率序列"""
    if len(prices) < 2:
        return []
    return [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]


def _safe_div(a: float, b: float) -> Optional[float]:
    """安全除法"""
    if b is None or b == 0:
        return None
    return a / b


def _safe_mean(data: list[float]) -> Optional[float]:
    """安全均值"""
    if not data:
        return None
    clean = [x for x in data if x is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _safe_std(data: list[float]) -> Optional[float]:
    """安全标准差"""
    if not data or len(data) < 2:
        return None
    clean = [x for x in data if x is not None]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    variance = sum((x - mean) ** 2 for x in clean) / (len(clean) - 1)
    return math.sqrt(variance)


# ═══════════════════════════════════════════════════════════
# 价格因子 (Price)
# ═══════════════════════════════════════════════════════════

def factor_ma5(closes: list[float]) -> Optional[float]:
    """5日均线偏离度：(收盘价 - MA5) / MA5，正值=站上均线"""
    if len(closes) < 5:
        return None
    try:
        ma5 = sum(closes[-5:]) / 5
        if ma5 == 0:
            return None
        return round((closes[-1] - ma5) / ma5, 6)
    except Exception:
        return None


def factor_ma10(closes: list[float]) -> Optional[float]:
    """10日均线偏离度"""
    if len(closes) < 10:
        return None
    try:
        ma10 = sum(closes[-10:]) / 10
        if ma10 == 0:
            return None
        return round((closes[-1] - ma10) / ma10, 6)
    except Exception:
        return None


def factor_ma20(closes: list[float]) -> Optional[float]:
    """20日均线偏离度"""
    if len(closes) < 20:
        return None
    try:
        ma20 = sum(closes[-20:]) / 20
        if ma20 == 0:
            return None
        return round((closes[-1] - ma20) / ma20, 6)
    except Exception:
        return None


def factor_ma60(closes: list[float]) -> Optional[float]:
    """60日均线偏离度"""
    if len(closes) < 60:
        return None
    try:
        ma60 = sum(closes[-60:]) / 60
        if ma60 == 0:
            return None
        return round((closes[-1] - ma60) / ma60, 6)
    except Exception:
        return None


def factor_price_position(closes: list[float], period: int = 20) -> Optional[float]:
    """价格区间位置：类似随机指标 %K，(收盘 - N日最低) / (N日最高 - N日最低) ∈ [0,1]"""
    if len(closes) < period:
        return None
    try:
        segment = closes[-period:]
        high, low = max(segment), min(segment)
        if high == low:
            return 0.5
        return round((closes[-1] - low) / (high - low), 4)
    except Exception:
        return None


def factor_high_low_ratio(highs: list[float], lows: list[float]) -> Optional[float]:
    """最高最低价比率：今日最高 / 今日最低"""
    if not highs or not lows:
        return None
    try:
        if lows[-1] <= 0:
            return None
        return round(highs[-1] / lows[-1], 6)
    except Exception:
        return None


def factor_close_open_ratio(closes: list[float]) -> Optional[float]:
    """收盘相对开盘涨跌幅：(收盘 - 开盘) / 开盘，用前日收盘近似开盘价"""
    if len(closes) < 2:
        return None
    try:
        prev_close = closes[-2]
        if prev_close <= 0:
            return None
        return round((closes[-1] - prev_close) / prev_close, 6)
    except Exception:
        return None


def factor_typical_price(highs: list[float], lows: list[float], closes: list[float]) -> Optional[float]:
    """典型价格归一化：(H+L+C)/3 相对收盘价的比率，>1 表示收盘偏低"""
    if not highs or not lows or not closes:
        return None
    try:
        tp = (highs[-1] + lows[-1] + closes[-1]) / 3
        if closes[-1] <= 0:
            return None
        return round(tp / closes[-1], 6)
    except Exception:
        return None


def factor_weighted_close(highs: list[float], lows: list[float], closes: list[float]) -> Optional[float]:
    """加权收盘归一化：(H+L+2*C)/4 相对收盘价的比率"""
    if not highs or not lows or not closes:
        return None
    try:
        wc = (highs[-1] + lows[-1] + 2 * closes[-1]) / 4
        if closes[-1] <= 0:
            return None
        return round(wc / closes[-1], 6)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 动量因子 (Momentum)
# ═══════════════════════════════════════════════════════════

def factor_ret_5d(closes: list[float]) -> Optional[float]:
    """5日收益率"""
    if len(closes) < 6:
        return None
    try:
        return round((closes[-1] - closes[-6]) / closes[-6], 6)
    except (TypeError, ZeroDivisionError):
        return None


def factor_ret_20d(closes: list[float]) -> Optional[float]:
    """20日收益率（1个月动量）"""
    if len(closes) < 21:
        return None
    try:
        return round((closes[-1] - closes[-21]) / closes[-21], 6)
    except (TypeError, ZeroDivisionError):
        return None


def factor_ret_60d(closes: list[float]) -> Optional[float]:
    """60日收益率（3个月动量）"""
    if len(closes) < 61:
        return None
    try:
        return round((closes[-1] - closes[-61]) / closes[-61], 6)
    except (TypeError, ZeroDivisionError):
        return None


def factor_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """相对强弱指标 RSI"""
    if len(closes) < period + 1:
        return None
    try:
        gains, losses = 0.0, 0.0
        rets = _returns(closes)
        if len(rets) < period:
            return None
        for r in rets[-period:]:
            if r > 0:
                gains += r
            else:
                losses += abs(r)
        if losses == 0:
            return 100.0
        rs = gains / losses
        return round(100 - 100 / (1 + rs), 2)
    except Exception:
        logger.debug("factor_rsi: calculation failed, returning None", exc_info=True)
        return None


def factor_macd_signal(closes: list[float]) -> Optional[float]:
    """MACD信号强度：DIF与DEA的差值相对价格（越大越强）"""
    if len(closes) < 26 + 9:
        return None
    try:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        dif = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
        dea = _ema(dif, 9)
        if not dif or not dea:
            return None
        # MACD柱 / 价格 = 信号强度百分比
        macd_bar = 2 * (dif[-1] - dea[-1])
        return round(macd_bar / closes[-1], 6)
    except Exception:
        logger.debug("factor_macd_signal: calculation failed, returning None", exc_info=True)
        return None


def factor_ma_disposition(closes: list[float]) -> Optional[float]:
    """均线排列度：短中长均线方向一致性（正=多头排列，负=空头）"""
    if len(closes) < 60:
        return None
    try:
        def _sma(data, n):
            if len(data) < n:
                return None
            return sum(data[-n:]) / n

        ma5 = _sma(closes, 5)
        ma10 = _sma(closes, 10)
        ma20 = _sma(closes, 20)
        ma60 = _sma(closes, 60)

        if not all([ma5, ma10, ma20, ma60]):
            return None

        # 各均线间距标准化
        score = 0.0
        score += 1 if ma5 > ma10 else -1
        score += 1 if ma10 > ma20 else -1
        score += 1 if ma20 > ma60 else -1
        # 归一化到 [-1, 1]
        return score / 3
    except Exception:
        logger.debug("factor_ma_disposition: calculation failed, returning None", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════
# 波动因子 (Volatility)
# ═══════════════════════════════════════════════════════════

def factor_hist_vol(returns: list[float], period: int = 20) -> Optional[float]:
    """历史波动率（年化）"""
    if len(returns) < period:
        return None
    try:
        recent = returns[-period:]
        std = _safe_std(recent)
        if std is None:
            return None
        return round(std * math.sqrt(252), 6)
    except Exception:
        logger.debug("factor_hist_vol: calculation failed, returning None", exc_info=True)
        return None


def factor_atr(highs: list[float], lows: list[float], closes: list[float],
               period: int = 14) -> Optional[float]:
    """平均真实波幅 ATR"""
    if len(closes) < period + 1:
        return None
    try:
        tr_list = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            tr_list.append(max(high_low, high_close, low_close))

        if len(tr_list) < period:
            return None
        return round(sum(tr_list[-period:]) / period, 4)
    except Exception:
        logger.debug("factor_atr: calculation failed, returning None", exc_info=True)
        return None


def factor_amplitude(closes: list[float], period: int = 20) -> Optional[float]:
    """振幅：周期内(最高-最低)/期初价格"""
    if len(closes) < period:
        return None
    try:
        segment = closes[-period:]
        high = max(segment)
        low = min(segment)
        if high is None or low is None or segment[0] == 0:
            return None
        return round((high - low) / segment[0], 6)
    except Exception:
        logger.debug("factor_amplitude: calculation failed, returning None", exc_info=True)
        return None


def factor_downside_vol(returns: list[float], period: int = 60) -> Optional[float]:
    """下行波动率：只看负收益的标准差"""
    if len(returns) < period:
        return None
    try:
        neg = [r for r in returns[-period:] if r < 0]
        if len(neg) < 5:
            return 0.0
        std = _safe_std(neg)
        if std is None:
            return None
        return round(std * math.sqrt(252), 6)
    except Exception:
        logger.debug("factor_downside_vol: calculation failed, returning None", exc_info=True)
        return None


def factor_boll_upper(closes: list[float], period: int = 20, nbdev: float = 2.0) -> Optional[float]:
    """布林上轨偏离度：(上轨 - 收盘) / 收盘，正值=价格在上轨下方，负值=突破上轨"""
    if len(closes) < period:
        return None
    try:
        segment = closes[-period:]
        ma = sum(segment) / period
        std = _safe_std(segment)
        if std is None or ma == 0:
            return None
        upper = ma + nbdev * std
        return round((upper - closes[-1]) / closes[-1], 6)
    except Exception:
        return None


def factor_boll_lower(closes: list[float], period: int = 20, nbdev: float = 2.0) -> Optional[float]:
    """布林下轨偏离度：(收盘 - 下轨) / 收盘，正值=价格在下轨上方，负值=跌破下轨"""
    if len(closes) < period:
        return None
    try:
        segment = closes[-period:]
        ma = sum(segment) / period
        std = _safe_std(segment)
        if std is None or ma == 0:
            return None
        lower = ma - nbdev * std
        return round((closes[-1] - lower) / closes[-1], 6)
    except Exception:
        return None


def factor_boll_position(closes: list[float], period: int = 20, nbdev: float = 2.0) -> Optional[float]:
    """布林带位置 %B：(收盘 - 下轨) / (上轨 - 下轨) ∈ [0,1]，>1=突破上轨，<0=跌破下轨"""
    if len(closes) < period:
        return None
    try:
        segment = closes[-period:]
        ma = sum(segment) / period
        std = _safe_std(segment)
        if std is None:
            return None
        upper = ma + nbdev * std
        lower = ma - nbdev * std
        if upper == lower:
            return 0.5
        return round((closes[-1] - lower) / (upper - lower), 4)
    except Exception:
        return None


def factor_volatility_ratio(closes: list[float]) -> Optional[float]:
    """波动率比率：20日HV / 5日HV，>1=短期波动收缩（看涨），<1=波动扩张（看跌）"""
    if len(closes) < 21:
        return None
    try:
        rets = _returns(closes)
        hv5 = factor_hist_vol(rets, 5)
        hv20 = factor_hist_vol(rets, 20)
        if hv5 is None or hv20 is None or hv5 == 0:
            return None
        return round(hv20 / hv5, 4)
    except Exception:
        return None


def factor_bb_width(closes: list[float], period: int = 20, nbdev: float = 2.0) -> Optional[float]:
    """布林带宽度：(上轨 - 下轨) / 中轨 = 4*标准差/均线，越大=波动越大"""
    if len(closes) < period:
        return None
    try:
        segment = closes[-period:]
        ma = sum(segment) / period
        std = _safe_std(segment)
        if std is None or ma == 0:
            return None
        return round((2 * nbdev * std) / ma, 4)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 成交量因子 (Volume)
# ═══════════════════════════════════════════════════════════

def factor_vol_ma5(volumes: list[float]) -> Optional[float]:
    """5日均量偏离度：(5日均量 - 20日均量) / 20日均量，正值=放量"""
    if len(volumes) < 20:
        return None
    try:
        ma5 = sum(volumes[-5:]) / 5
        ma20 = sum(volumes[-20:]) / 20
        if ma20 == 0:
            return None
        return round((ma5 - ma20) / ma20, 4)
    except Exception:
        return None


def factor_vol_ma10(volumes: list[float]) -> Optional[float]:
    """10日均量偏离度：(10日均量 - 20日均量) / 20日均量"""
    if len(volumes) < 20:
        return None
    try:
        ma10 = sum(volumes[-10:]) / 10
        ma20 = sum(volumes[-20:]) / 20
        if ma20 == 0:
            return None
        return round((ma10 - ma20) / ma20, 4)
    except Exception:
        return None


def factor_vol_ma20(volumes: list[float]) -> Optional[float]:
    """20日均量偏离度：(20日均量 - 60日均量) / 60日均量"""
    if len(volumes) < 60:
        return None
    try:
        ma20 = sum(volumes[-20:]) / 20
        ma60 = sum(volumes[-60:]) / 60
        if ma60 == 0:
            return None
        return round((ma20 - ma60) / ma60, 4)
    except Exception:
        return None


def factor_vol_std(volumes: list[float], period: int = 20) -> Optional[float]:
    """成交量波动：20日成交量变异系数 = std(vol) / mean(vol)，越大越异动"""
    if len(volumes) < period:
        return None
    try:
        recent = volumes[-period:]
        mean_v = sum(recent) / period
        if mean_v == 0:
            return None
        std_v = _safe_std(recent)
        if std_v is None:
            return None
        return round(std_v / mean_v, 4)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 量价因子 (Volume & Price)
# ═══════════════════════════════════════════════════════════

def factor_vol_ratio(volumes: list[float], period: int = 20) -> Optional[float]:
    """量比：最近5日均量 / 20日均量"""
    if len(volumes) < period:
        return None
    try:
        vol_5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else sum(volumes) / len(volumes)
        vol_20 = sum(volumes[-period:]) / period
        if vol_20 == 0:
            return None
        return round(vol_5 / vol_20, 4)
    except Exception:
        logger.debug("factor_vol_ratio: calculation failed, returning None", exc_info=True)
        return None


def factor_turnover_rate(volumes: list[float], total_shares: Optional[float] = None) -> Optional[float]:
    """换手率估算：日均成交量 / 总股本（需要 total_shares 外部传入）"""
    if not volumes or not total_shares or total_shares <= 0:
        return None
    try:
        avg_vol_20 = sum(volumes[-20:]) / min(len(volumes), 20)
        if total_shares == 0:
            return None
        return round(avg_vol_20 / total_shares, 6)
    except Exception:
        logger.debug("factor_turnover_rate: calculation failed, returning None", exc_info=True)
        return None


def factor_obv_divergence(closes: list[float], volumes: list[float]) -> Optional[float]:
    """OBV价格背离度：OBV变动方向 vs 价格变动方向一致性"""
    min_len = min(len(closes), len(volumes))
    if min_len < 20:
        return None
    try:
        closes = closes[-min_len:]
        volumes = volumes[-min_len:]

        # 计算 OBV
        obv = [0.0]
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv.append(obv[-1] + volumes[i])
            elif closes[i] < closes[i - 1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])

        # 20日 OBV 趋势 vs 价格趋势
        obv_ret = (obv[-1] - obv[-20]) / abs(obv[-20]) if obv[-20] != 0 else 0
        price_ret = (closes[-1] - closes[-20]) / closes[-20] if closes[-20] != 0 else 0

        # 背离度 = sign(price) * (obv_change - price_change) → 正值=OBV确认价格趋势
        return round(obv_ret - price_ret, 6)
    except Exception:
        logger.debug("factor_obv_divergence: calculation failed, returning None", exc_info=True)
        return None


def factor_price_volume_corr(closes: list[float], volumes: list[float]) -> Optional[float]:
    """量价相关性：过去20日收盘价与成交量的皮尔逊相关系数"""
    min_len = min(len(closes), len(volumes), 20)
    if min_len < 5:
        return None
    try:
        p = closes[-min_len:]
        v = volumes[-min_len:]
        n = len(p)
        mean_p = sum(p) / n
        mean_v = sum(v) / n
        cov = sum((p[i] - mean_p) * (v[i] - mean_v) for i in range(n))
        std_p = math.sqrt(sum((x - mean_p) ** 2 for x in p))
        std_v = math.sqrt(sum((x - mean_v) ** 2 for x in v))
        if std_p == 0 or std_v == 0:
            return None
        return round(cov / (std_p * std_v), 4)
    except Exception:
        logger.debug("factor_price_volume_corr: calculation failed, returning None", exc_info=True)
        return None


def factor_avg_amount(volumes: list[float], closes: list[float],
                      period: int = 20) -> Optional[float]:
    """日均成交额：vol * avg_close（对数化，跨股票可比）"""
    if len(volumes) < period or len(closes) < period:
        return None
    try:
        amounts = [volumes[i] * closes[i] for i in range(-period, 0)]
        avg = sum(amounts) / period
        if avg <= 0:
            return None
        return round(math.log10(avg), 4)
    except Exception:
        logger.debug("factor_avg_amount: calculation failed, returning None", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════
# 基本面因子 (Fundamental)
# ═══════════════════════════════════════════════════════════

def factor_pe(pe: Optional[float]) -> Optional[float]:
    """市盈率（取倒数 = 盈利率，PE 越低得分越高）"""
    if pe is None or pe <= 0:
        return None
    try:
        return round(1 / pe, 6)  # 盈利率
    except Exception:
        logger.debug("factor_pe: calculation failed, returning None", exc_info=True)
        return None


def factor_pb(pb: Optional[float]) -> Optional[float]:
    """市净率（取倒数 = 净资产收益率价格比，PB 越低越好）"""
    if pb is None or pb <= 0:
        return None
    try:
        return round(1 / pb, 6)
    except Exception:
        logger.debug("factor_pb: calculation failed, returning None", exc_info=True)
        return None


def factor_roe(roe: Optional[float]) -> Optional[float]:
    """ROE：净资产收益率"""
    if roe is None:
        return None
    try:
        return round(float(roe) / 100, 4)  # % → 小数
    except Exception:
        logger.debug("factor_roe: calculation failed, returning None", exc_info=True)
        return None


def factor_eps_growth(eps: Optional[float], prev_eps: Optional[float] = None) -> Optional[float]:
    """EPS 增长率"""
    if eps is None or prev_eps is None or prev_eps == 0:
        return None
    try:
        return round((eps - prev_eps) / abs(prev_eps), 4)
    except Exception:
        logger.debug("factor_eps_growth: calculation failed, returning None", exc_info=True)
        return None


def factor_market_cap(market_cap_billion: Optional[float]) -> Optional[float]:
    """市值因子：对数化市值（亿单位），对数化后跨量级可比"""
    if market_cap_billion is None or market_cap_billion <= 0:
        return None
    try:
        return round(math.log10(market_cap_billion), 4)
    except Exception:
        logger.debug("factor_market_cap: calculation failed, returning None", exc_info=True)
        return None


def factor_dividend_yield(dividend: Optional[float], price: Optional[float]) -> Optional[float]:
    """股息率"""
    if dividend is None or price is None or price <= 0:
        return None
    try:
        return round(dividend / price, 6)
    except Exception:
        logger.debug("factor_dividend_yield: calculation failed, returning None", exc_info=True)
        return None


def factor_ps_ttm(price: Optional[float], revenue: Optional[float],
                  total_shares: Optional[float]) -> Optional[float]:
    """市销率倒数：1/(市值/营收)，PS越低越好"""
    if not price or not revenue or not total_shares or revenue <= 0 or total_shares <= 0:
        return None
    try:
        ps = (price * total_shares) / revenue
        if ps <= 0:
            return None
        return round(1 / ps, 6)
    except Exception:
        return None


def factor_debt_ratio(debt_ratio_pct: Optional[float]) -> Optional[float]:
    """资产负债率：debt_ratio越低越好，取(100 - debt_ratio)/100归一化"""
    if debt_ratio_pct is None:
        return None
    try:
        return round(1 - debt_ratio_pct / 100, 4)
    except Exception:
        return None


def factor_gross_margin(gross_margin_pct: Optional[float]) -> Optional[float]:
    """毛利率：直接使用百分比值，越高越好"""
    if gross_margin_pct is None:
        return None
    try:
        return round(float(gross_margin_pct) / 100, 4)
    except Exception:
        return None


def factor_revenue_growth(revenue: Optional[float], prev_revenue: Optional[float]) -> Optional[float]:
    """营收同比增长率：(当期 - 上期) / |上期|"""
    if revenue is None or prev_revenue is None or prev_revenue == 0:
        return None
    try:
        return round((revenue - prev_revenue) / abs(prev_revenue), 4)
    except Exception:
        return None


def factor_net_profit_growth(net_profit: Optional[float], prev_net_profit: Optional[float]) -> Optional[float]:
    """净利润同比增长率"""
    if net_profit is None or prev_net_profit is None or prev_net_profit == 0:
        return None
    try:
        return round((net_profit - prev_net_profit) / abs(prev_net_profit), 4)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 情绪因子 (Sentiment)
# ═══════════════════════════════════════════════════════════

def factor_strength(closes: list[float], period: int = 20) -> Optional[float]:
    """相对强度：20日涨幅 / 20日波动率（类似信息比率）"""
    if len(closes) < period + 1:
        return None
    try:
        ret_20 = factor_ret_20d(closes)
        if ret_20 is None:
            return None
        rets = _returns(closes)[-period:]
        vol = _safe_std(rets)
        if vol is None or vol == 0:
            return ret_20
        return round(ret_20 / (vol * math.sqrt(period)), 4)
    except Exception:
        logger.debug("factor_strength: calculation failed, returning None", exc_info=True)
        return None


def factor_momentum_score(closes: list[float]) -> Optional[float]:
    """动量综合分：短中长期收益率的加权和"""
    r5 = factor_ret_5d(closes)
    r20 = factor_ret_20d(closes)
    r60 = factor_ret_60d(closes)
    vals = [r5, r20, r60]
    if all(v is None for v in vals):
        return None
    # 短周期权重更大
    weights = [0.5, 0.3, 0.2]
    score = 0.0
    total_w = 0.0
    for v, w in zip(vals, weights):
        if v is not None:
            score += v * w
            total_w += w
    return round(score / total_w, 6) if total_w > 0 else None


def factor_acceleration(closes: list[float]) -> Optional[float]:
    """动量加速度：短周期动量 − 长周期动量，正值=趋势加速中"""
    r5 = factor_ret_5d(closes)
    r20 = factor_ret_20d(closes)
    if r5 is None or r20 is None:
        return None
    try:
        return round(r5 - r20, 6)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 资金因子 (Capital Flow) — 北向资金 + 融资融券 + 机构持仓
# ═══════════════════════════════════════════════════════════

def factor_north_flow(north_flow_data: Optional[dict]) -> Optional[float]:
    """北向资金因子：个股沪深港通净流入强度（原始值）

    north_flow_data 来自 akshare_adapter.get_north_flow()
    包含 net_flow（净流入，亿元）。
    返回原始净流入值，由 normalize_factors() 做横截面 Z-Score 标准化。
    正值=净流入（看多），负值=净流出（看空）。
    """
    if north_flow_data is None:
        return None
    try:
        net_flow = north_flow_data.get("net_flow")
        if net_flow is None:
            return None
        return float(net_flow)  # 亿元，横截面 Z-Score 标准化
    except Exception:
        logger.debug("factor_north_flow: calculation failed, returning None", exc_info=True)
        return None


def factor_inst_change(inst_data: Optional[dict]) -> Optional[float]:
    """机构持仓因子：机构持股比例变动（原始值）

    inst_data 来自 akshare_adapter.get_inst_holding()
    change_pct = (本期比例 - 上期比例) / |上期比例|。
    返回原始变化率，由 normalize_factors() 做横截面 Z-Score 标准化。
    正值=机构加仓（看多），负值=机构减仓。
    """
    if inst_data is None:
        return None
    try:
        change_pct = inst_data.get("change_pct")
        if change_pct is None:
            return None
        return float(change_pct)  # 横截面 Z-Score 标准化
    except Exception:
        logger.debug("factor_inst_change: calculation failed, returning None", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════
# 单只股票全因子计算
# ═══════════════════════════════════════════════════════════

def compute_all_factors(
    code: str,
    closes: list[float],
    highs: list[float] = None,
    lows: list[float] = None,
    volumes: list[float] = None,
    fundamentals: dict = None,
    prev_eps: float = None,
    dividend: float = None,
    north_flow_data: dict = None,
    inst_data: dict = None,
) -> dict:
    """计算单只股票的全部 29 个因子

    Args:
        code: 股票代码
        closes: 收盘价序列（至少 120 条）
        highs: 最高价序列
        lows: 最低价序列
        volumes: 成交量序列
        fundamentals: 基本面数据 (来自 baostock_adapter.get_stock_factors)
        prev_eps: 去年同期 EPS
        dividend: 每股分红
        north_flow_data: 北向资金数据 (来自 akshare_adapter.get_north_flow)
        inst_data: 机构持仓数据 (来自 akshare_adapter.get_inst_holding)

    Returns:
        {code, factors: {name: value_or_None}, hit_count: int}
    """
    highs = highs or []
    lows = lows or []
    volumes = volumes or []
    fundamentals = fundamentals or {}

    rets = _returns(closes)

    # 确保序列长度一致
    n = min(len(closes), len(highs) or len(closes), len(lows) or len(closes),
            len(volumes) or len(closes))

    factors = {}

    # ── 动量类 ──
    factors["ret_5d"] = factor_ret_5d(closes)
    factors["ret_20d"] = factor_ret_20d(closes)
    factors["ret_60d"] = factor_ret_60d(closes)
    factors["rsi_14"] = factor_rsi(closes)
    factors["macd_signal"] = factor_macd_signal(closes)
    factors["ma_disposition"] = factor_ma_disposition(closes)

    # ── 价格类 ──
    factors["ma5"] = factor_ma5(closes)
    factors["ma10"] = factor_ma10(closes)
    factors["ma20"] = factor_ma20(closes)
    factors["ma60"] = factor_ma60(closes)
    factors["price_position"] = factor_price_position(closes)
    if highs and lows:
        factors["high_low_ratio"] = factor_high_low_ratio(highs[-n:] if highs else [], lows[-n:] if lows else [])
    else:
        factors["high_low_ratio"] = None
    factors["close_open_ratio"] = factor_close_open_ratio(closes)
    if highs and lows:
        factors["typical_price"] = factor_typical_price(highs[-n:], lows[-n:], closes[-n:])
        factors["weighted_close"] = factor_weighted_close(highs[-n:], lows[-n:], closes[-n:])
    else:
        factors["typical_price"] = None
        factors["weighted_close"] = None

    # ── 波动类 ──
    factors["hist_vol_5d"] = factor_hist_vol(rets, 5)
    factors["hist_vol_20d"] = factor_hist_vol(rets, 20)
    if highs and lows:
        atr_raw = factor_atr(highs[-n:], lows[-n:], closes[-n:])
        factors["atr_14"] = round(atr_raw / closes[-1], 6) if atr_raw and closes[-1] else None
    else:
        factors["atr_14"] = None
    factors["amplitude_20d"] = factor_amplitude(closes)
    factors["downside_vol"] = factor_downside_vol(rets, 60)
    factors["boll_upper"] = factor_boll_upper(closes)
    factors["boll_lower"] = factor_boll_lower(closes)
    factors["boll_position"] = factor_boll_position(closes)
    factors["volatility_ratio"] = factor_volatility_ratio(closes)
    factors["bb_width"] = factor_bb_width(closes)

    # ── 成交量类 ──
    if volumes:
        factors["vol_ma5"] = factor_vol_ma5(volumes[-n:])
        factors["vol_ma10"] = factor_vol_ma10(volumes[-n:])
        factors["vol_ma20"] = factor_vol_ma20(volumes[-n:])
        factors["vol_std"] = factor_vol_std(volumes[-n:])
    else:
        factors["vol_ma5"] = None
        factors["vol_ma10"] = None
        factors["vol_ma20"] = None
        factors["vol_std"] = None

    # ── 量价类 ──
    if volumes:
        factors["vol_ratio"] = factor_vol_ratio(volumes[-n:])
        factors["turnover_rate"] = factor_turnover_rate(
            volumes[-n:], fundamentals.get("total_shares"))
        factors["obv_divergence"] = factor_obv_divergence(closes[-n:], volumes[-n:])
        factors["price_volume_corr"] = factor_price_volume_corr(closes[-n:], volumes[-n:])
        factors["avg_amount"] = factor_avg_amount(volumes[-n:], closes[-n:])
    else:
        factors["vol_ratio"] = None
        factors["turnover_rate"] = None
        factors["obv_divergence"] = None
        factors["price_volume_corr"] = None
        factors["avg_amount"] = None

    # ── 基本面类 ──
    factors["pe_inverse"] = factor_pe(fundamentals.get("pe"))
    # PB: 优先用 Baostock 真实 pbMRQ，取不到时回退到 PE×ROE 反推
    pe = fundamentals.get("pe")
    roe_pct = fundamentals.get("roe")
    pb = fundamentals.get("pb")
    if pb is None or pb <= 0:
        if pe and roe_pct and pe > 0:
            pb = pe * (roe_pct / 100)
    factors["pb_inverse"] = factor_pb(pb) if pb and pb > 0 else None
    factors["roe"] = factor_roe(roe_pct)
    factors["eps_growth"] = factor_eps_growth(fundamentals.get("eps"), prev_eps)
    factors["market_cap_ln"] = factor_market_cap(fundamentals.get("market_cap_billion"))
    factors["dividend_yield"] = factor_dividend_yield(dividend, fundamentals.get("price"))
    rev = fundamentals.get("revenue") or fundamentals.get("prev_revenue")
    factors["ps_ttm"] = factor_ps_ttm(
        fundamentals.get("price"), rev,
        fundamentals.get("total_shares"))
    factors["debt_ratio"] = factor_debt_ratio(fundamentals.get("debt_ratio"))
    factors["gross_margin"] = factor_gross_margin(fundamentals.get("gross_margin"))
    factors["revenue_growth"] = factor_revenue_growth(
        fundamentals.get("revenue"), fundamentals.get("prev_revenue"))
    factors["net_profit_growth"] = factor_net_profit_growth(
        fundamentals.get("net_profit"), fundamentals.get("prev_net_profit"))

    # ── 情绪类 ──
    factors["strength_20d"] = factor_strength(closes)
    factors["momentum_composite"] = factor_momentum_score(closes)
    factors["acceleration"] = factor_acceleration(closes)

    # ── 资金类（北向资金 + 机构持仓） ──
    factors["north_flow"] = factor_north_flow(north_flow_data)
    factors["inst_change"] = factor_inst_change(inst_data)

    # 统计有效因子数
    hit_count = sum(1 for v in factors.values() if v is not None)

    return {"code": code, "factors": factors, "hit_count": hit_count}


# ═══════════════════════════════════════════════════════════
# 因子标准化（截面上的 Z-Score）
# ═══════════════════════════════════════════════════════════

def normalize_factors(all_factors: list[dict]) -> list[dict]:
    """对一批股票的因子值做截面 Z-Score 标准化

    Args:
        all_factors: [{"code": ..., "factors": {...}, "hit_count": ...}, ...]

    Returns:
        标准化后的同结构列表，每个因子值变为 z-score（均值0，标准差1）
    """
    if not all_factors:
        return all_factors

    # 收集每个因子的所有值
    factor_names = all_factors[0]["factors"].keys()
    factor_values: dict[str, list[Optional[float]]] = {fn: [] for fn in factor_names}

    code_index: dict[str, int] = {}
    for i, f in enumerate(all_factors):
        code_index[f["code"]] = i
        for fn in factor_names:
            factor_values[fn].append(f["factors"].get(fn))

    # 逐因子算 Z-Score
    factor_stats: dict[str, tuple[float, float]] = {}  # {name: (mean, std)}
    for fn in factor_names:
        vals = [v for v in factor_values[fn] if v is not None]
        if len(vals) < 3:
            factor_stats[fn] = (0.0, 1.0)  # 样本不够，不标准化
            continue
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1))
        if std == 0:
            std = 1e-8
        factor_stats[fn] = (mean, std)

    # 应用 Z-Score
    result = []
    for f in all_factors:
        new_factors = {}
        for fn in factor_names:
            raw = f["factors"].get(fn)
            if raw is None:
                new_factors[fn] = None
            else:
                mean, std = factor_stats[fn]
                new_factors[fn] = round((raw - mean) / std, 6)
        result.append({
            "code": f["code"],
            "name": f.get("name", ""),         # 透传：股票名称（来自 stock_info 缓存）
            "industry": f.get("industry", ""), # 透传：行业（来自 stock_info 缓存）
            "price": f.get("price"),           # 透传：最新收盘价（来自 historical_kline）
            "factors": new_factors,
            "hit_count": f["hit_count"],
        })

    return result


# ═══════════════════════════════════════════════════════════════
# 因子注册表 — 源自 qlib_factor_platform presets.py (158因子)
#
# status: "done" = 已实现 / "pending" = 待实现 / "planned" = 规划中
# ═══════════════════════════════════════════════════════════════

FACTOR_REGISTRY: dict[str, dict] = {
    # ── 价格因子 (9) ──
    "MA5":     {"status": "done", "fn": "factor_ma5",              "category": "价格因子", "direction": "正向"},
    "MA10":    {"status": "done", "fn": "factor_ma10",             "category": "价格因子", "direction": "正向"},
    "MA20":    {"status": "done", "fn": "factor_ma20",             "category": "价格因子", "direction": "正向"},
    "MA60":    {"status": "done", "fn": "factor_ma60",             "category": "价格因子", "direction": "正向"},
    "PRICE_POS":       {"status": "done", "fn": "factor_price_position",      "category": "价格因子", "direction": "正向"},
    "HIGH_LOW_RATIO":  {"status": "done", "fn": "factor_high_low_ratio",        "category": "价格因子", "direction": "正向"},
    "CLOSE_OPEN_RATIO":{"status": "done", "fn": "factor_close_open_ratio",      "category": "价格因子", "direction": "正向"},
    "TYPICAL_PRICE":   {"status": "done", "fn": "factor_typical_price",         "category": "价格因子", "direction": "中性"},
    "WEIGHTED_CLOSE":  {"status": "done", "fn": "factor_weighted_close",        "category": "价格因子", "direction": "中性"},

    # ── 成交量因子 (6) ──
    "VOL_MA5":     {"status": "done",    "fn": "factor_vol_ma5",      "category": "成交量因子", "direction": "正向"},
    "VOL_MA10":    {"status": "done",    "fn": "factor_vol_ma10",     "category": "成交量因子", "direction": "正向"},
    "VOL_MA20":    {"status": "done",    "fn": "factor_vol_ma20",     "category": "成交量因子", "direction": "正向"},
    "VOL_RATIO":   {"status": "done",    "fn": "factor_vol_ratio",    "category": "成交量因子", "direction": "正向"},
    "VOL_STD":     {"status": "done",    "fn": "factor_vol_std",      "category": "成交量因子", "direction": "正向"},
    "PRICE_VOLUME": {"status": "done",   "fn": "factor_price_volume_corr", "category": "成交量因子", "direction": "正向"},

    # ── 技术指标因子 (5) ──
    "RSI":          {"status": "done",    "fn": "factor_rsi_14",       "category": "技术指标因子", "direction": "正向"},
    "MACD":         {"status": "done",    "fn": "factor_macd_signal",  "category": "技术指标因子", "direction": "正向"},
    "BOLL_UPPER":   {"status": "done", "fn": "factor_boll_upper",   "category": "技术指标因子", "direction": "正向"},
    "BOLL_LOWER":   {"status": "done", "fn": "factor_boll_lower",   "category": "技术指标因子", "direction": "正向"},
    "BOLL_POSITION":{"status": "done", "fn": "factor_boll_position","category": "技术指标因子", "direction": "正向"},

    # ── 动量因子 (9) ──
    "RET_5D":       {"status": "done",    "fn": "factor_ret_5d",       "category": "动量因子", "direction": "正向"},
    "RET_20D":      {"status": "done",    "fn": "factor_ret_20d",      "category": "动量因子", "direction": "正向"},
    "RET_60D":      {"status": "done",    "fn": "factor_ret_60d",      "category": "动量因子", "direction": "正向"},
    "MOMENTUM_5":   {"status": "done",    "fn": "factor_ret_5d",       "category": "动量因子", "direction": "正向"},
    "MOMENTUM_10":  {"status": "done",    "fn": "factor_ret_20d",      "category": "动量因子", "direction": "正向"},
    "MOMENTUM_20":  {"status": "done",    "fn": "factor_ret_60d",      "category": "动量因子", "direction": "正向"},
    "ACCELERATION": {"status": "done", "fn": "factor_acceleration","category": "动量因子", "direction": "正向"},
    "TREND_STRENGTH":{"status": "done",   "fn": "factor_strength_20d", "category": "动量因子", "direction": "正向"},
    "MOMENTUM_COMPOSITE":{"status": "done","fn": "factor_momentum_composite", "category": "动量因子", "direction": "正向"},

    # ── 波动率因子 (8) ──
    "VOLATILITY_5":     {"status": "done",    "fn": "factor_hist_vol_5d",  "category": "波动率因子", "direction": "负向"},
    "VOLATILITY_20":    {"status": "done",    "fn": "factor_hist_vol_20d", "category": "波动率因子", "direction": "负向"},
    "VOLATILITY_RATIO": {"status": "done",    "fn": "factor_volatility_ratio",  "category": "波动率因子", "direction": "正向"},
    "RANGE_VOLATILITY": {"status": "done",    "fn": "factor_amplitude_20d","category": "波动率因子", "direction": "负向"},
    "ATR":              {"status": "done",    "fn": "factor_atr_14",       "category": "波动率因子", "direction": "负向"},
    "DOWNSIDE_VOL":     {"status": "done",    "fn": "factor_downside_vol", "category": "波动率因子", "direction": "负向"},
    "BB_WIDTH":         {"status": "done",    "fn": "factor_bb_width",     "category": "波动率因子", "direction": "中性"},
    "HV_20":            {"status": "done",    "fn": "factor_hist_vol_20d", "category": "波动率因子", "direction": "负向"},

    # ── 量价因子 (3) ──
    "TURNOVER_RATE": {"status": "done",  "fn": "factor_turnover_rate",   "category": "量价因子", "direction": "正向"},
    "OBV_DIVERGENCE":{"status": "done",  "fn": "factor_obv_divergence",  "category": "量价因子", "direction": "正向"},
    "AVG_AMOUNT":    {"status": "done",  "fn": "factor_avg_amount",      "category": "量价因子", "direction": "正向"},

    # ── 基本面因子 (11) ──
    "PE":            {"status": "done",   "fn": "factor_pe_inverse",      "category": "基本面因子", "direction": "正向"},
    "PB":            {"status": "done",   "fn": "factor_pb_inverse",      "category": "基本面因子", "direction": "正向"},
    "ROE":           {"status": "done",   "fn": "factor_roe",             "category": "基本面因子", "direction": "正向"},
    "EPS_GROWTH":    {"status": "done",   "fn": "factor_eps_growth",      "category": "基本面因子", "direction": "正向"},
    "MARKET_CAP":    {"status": "done",   "fn": "factor_market_cap_ln",   "category": "基本面因子", "direction": "负向"},
    "DIVIDEND_YIELD":{"status": "done",   "fn": "factor_dividend_yield",  "category": "基本面因子", "direction": "正向"},
    "PS_TTM":        {"status": "done",   "fn": "factor_ps_ttm",               "category": "基本面因子", "direction": "正向"},
    "DEBT_RATIO":    {"status": "done",   "fn": "factor_debt_ratio",     "category": "基本面因子", "direction": "负向"},
    "GROSS_MARGIN":  {"status": "done",   "fn": "factor_gross_margin",  "category": "基本面因子", "direction": "正向"},
    "REVENUE_GROWTH":{"status": "done",   "fn": "factor_revenue_growth",   "category": "基本面因子", "direction": "正向"},
    "NET_PROFIT_GROWTH":{"status": "done","fn": "factor_net_profit_growth", "category": "基本面因子", "direction": "正向"},

    # ── 情绪因子 (2) ──
    "STRENGTH_20D":       {"status": "done","fn": "factor_strength_20d",       "category": "情绪因子", "direction": "正向"},
    "MOMENTUM_COMPOSITE_2":{"status": "done","fn": "factor_momentum_composite","category": "情绪因子", "direction": "正向"},

    # ── 资金因子 (2) ──
    "NORTH_FLOW":    {"status": "done", "fn": "factor_north_flow",      "category": "资金因子", "direction": "正向"},
    "INST_CHANGE":   {"status": "done", "fn": "factor_inst_change",     "category": "资金因子", "direction": "正向"},

}

# ── Alpha158 扩展因子 (规划中, 待 Pine Script 翻译后接入) ──
ALPHA158_PLANNED = [
    "KMID", "KLEN", "KMID2", "KUP", "KUP2", "KLOW", "KLOW2", "KSFT",
    "OPEN", "HIGH", "LOW", "CLOSE", "VWAP", "OPEN0", "HIGH0", "LOW0",
    "ROC5", "ROC10", "ROC20", "ROC60", "MA5", "MA10", "MA20", "MA60",
    "DEVIATION5", "DEVIATION10", "DEVIATION20", "DEVIATION60",
    "STD5", "STD10", "STD20", "STD60", "BETA5", "BETA10",
    "VOL5", "VOL10", "VOL20", "VOL60", "VMA5", "VMA10", "VMA20", "VMA60",
    "CORR5", "CORR10", "CORR20", "CORR60",
    "CORD5", "CORD10", "CORD20", "CORD60",
]

# 因子统计摘要
_done = sum(1 for v in FACTOR_REGISTRY.values() if v["status"] == "done")
_pending = sum(1 for v in FACTOR_REGISTRY.values() if v["status"] == "pending")
REGISTRY_SUMMARY = {
    "total_registered": len(FACTOR_REGISTRY),  # 59
    "done": _done,          # 29
    "pending": _pending,    # 30
    "planned_alpha158": len(ALPHA158_PLANNED),  # 54
    "grand_total": len(FACTOR_REGISTRY) + len(ALPHA158_PLANNED),  # 113
    "categories": sorted(set(v["category"] for v in FACTOR_REGISTRY.values())),
}


# ═══════════════════════════════════════════════════════════════
#  因子退场机制 — 源自 multi-factor-stock-selection
# ═══════════════════════════════════════════════════════════════

def track_factor_performance(
    ic_history: dict[str, list[float]],
    icir_threshold: float = 0.3,
    streak_months: int = 3,
) -> dict:
    """
    因子绩效追踪 + 退场判定

    连续 streak_months 个月 ICIR < icir_threshold 的因子标记为 "retired"。

    Args:
        ic_history: {factor_name: [最近N个月的ICIR值]}
        icir_threshold: ICIR 阈值 (默认 0.3)
        streak_months: 连续不达标月数 (默认 3)

    Returns:
        {
            "retired": [...],       # 退场因子列表
            "warned": [...],        # 警告因子 (连续1-2月不达标)
            "healthy": [...],       # 健康因子
            "details": {factor: {"streak": N, "avg_icir": X}}
        }
    """
    from collections import defaultdict

    result = {"retired": [], "warned": [], "healthy": [], "details": {}}

    for factor_name, icir_values in ic_history.items():
        # 计算连续不达标月数
        streak = 0
        for val in reversed(icir_values):  # 从最近往前数
            if val is None or (isinstance(val, (int, float)) and val < icir_threshold):
                streak += 1
            else:
                break

        avg_icir = (sum(v for v in icir_values if v is not None) /
                    max(len([v for v in icir_values if v is not None]), 1))

        result["details"][factor_name] = {
            "streak": streak,
            "avg_icir": round(avg_icir, 4),
            "latest_icir": round(icir_values[-1], 4) if icir_values else None,
        }

        if streak >= streak_months:
            result["retired"].append(factor_name)
            # 更新注册表状态
            if factor_name in FACTOR_REGISTRY:
                FACTOR_REGISTRY[factor_name]["status"] = "retired"
        elif streak >= 1:
            result["warned"].append(factor_name)
        else:
            result["healthy"].append(factor_name)

    return result


def apply_factor_retirement(ic_history: dict) -> dict:
    """
    一键因子退场评估 + 更新注册表

    Returns: track_factor_performance 结果 + 更新后的统计
    """
    result = track_factor_performance(ic_history)

    # 更新全局统计
    global REGISTRY_SUMMARY
    _done = sum(1 for v in FACTOR_REGISTRY.values() if v["status"] == "done")
    _retired = sum(1 for v in FACTOR_REGISTRY.values() if v["status"] == "retired")
    REGISTRY_SUMMARY.update({
        "done": _done,
        "retired": _retired,
    })

    result["registry_updated"] = {
        "done": _done,
        "retired": _retired,
        "total": len(FACTOR_REGISTRY),
    }
    return result

