"""因子计算引擎：5大类25因子，从 qlib Alpha158 精选

因子体系：
  动量类(6): ret_5d, ret_20d, ret_60d, rsi_14, macd_signal, ma_disposition
  波动类(4): hist_vol_20d, atr_14, amplitude_20d, downside_vol
  量价类(5): vol_ratio, turnover_rate, obv_divergence, price_volume_corr, avg_amount
  基本面(6): pe, pb, roe, eps_growth, market_cap, dividend_yield
  情绪类(4): north_flow, margin_change, inst_change, strength_20d

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
        return None


def factor_pb(pb: Optional[float]) -> Optional[float]:
    """市净率（取倒数 = 净资产收益率价格比，PB 越低越好）"""
    if pb is None or pb <= 0:
        return None
    try:
        return round(1 / pb, 6)
    except Exception:
        return None


def factor_roe(roe: Optional[float]) -> Optional[float]:
    """ROE：净资产收益率"""
    if roe is None:
        return None
    try:
        return round(float(roe) / 100, 4)  # % → 小数
    except Exception:
        return None


def factor_eps_growth(eps: Optional[float], prev_eps: Optional[float] = None) -> Optional[float]:
    """EPS 增长率"""
    if eps is None or prev_eps is None or prev_eps == 0:
        return None
    try:
        return round((eps - prev_eps) / abs(prev_eps), 4)
    except Exception:
        return None


def factor_market_cap(market_cap_billion: Optional[float]) -> Optional[float]:
    """市值因子：对数化市值（亿单位），对数化后跨量级可比"""
    if market_cap_billion is None or market_cap_billion <= 0:
        return None
    try:
        return round(math.log10(market_cap_billion), 4)
    except Exception:
        return None


def factor_dividend_yield(dividend: Optional[float], price: Optional[float]) -> Optional[float]:
    """股息率"""
    if dividend is None or price is None or price <= 0:
        return None
    try:
        return round(dividend / price, 6)
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
) -> dict:
    """计算单只股票的全部 25 个因子

    Args:
        code: 股票代码
        closes: 收盘价序列（至少 120 条）
        highs: 最高价序列
        lows: 最低价序列
        volumes: 成交量序列
        fundamentals: 基本面数据 (来自 baostock_adapter.get_stock_factors)
        prev_eps: 去年同期 EPS
        dividend: 每股分红

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

    # ── 波动类 ──
    factors["hist_vol_20d"] = factor_hist_vol(rets, 20)
    if highs and lows:
        factors["atr_14"] = factor_atr(highs[-n:], lows[-n:], closes[-n:])
    else:
        factors["atr_14"] = None
    factors["amplitude_20d"] = factor_amplitude(closes)
    factors["downside_vol"] = factor_downside_vol(rets, 60)

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
    # PB 不直接支持，从 PE/ROE 反推：PB = PE * ROE/100
    pe = fundamentals.get("pe")
    roe_pct = fundamentals.get("roe")
    if pe and roe_pct and pe > 0:
        pb_est = pe * (roe_pct / 100)
        factors["pb_inverse"] = factor_pb(pb_est)
    else:
        factors["pb_inverse"] = None
    factors["roe"] = factor_roe(roe_pct)
    factors["eps_growth"] = factor_eps_growth(fundamentals.get("eps"), prev_eps)
    factors["market_cap_ln"] = factor_market_cap(fundamentals.get("market_cap_billion"))
    factors["dividend_yield"] = factor_dividend_yield(dividend, fundamentals.get("price"))

    # ── 情绪类 ──
    factors["strength_20d"] = factor_strength(closes)
    factors["momentum_composite"] = factor_momentum_score(closes)

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
            "factors": new_factors,
            "hit_count": f["hit_count"],
        })

    return result
