"""因子实验室 — IC 分析 / 相关性矩阵 / 散点图

核心算法:
  IC = Pearson(factor_value_t, return_{t+k}) for each day t
  IR  = IC.mean() / IC.std()
  胜率 = IC>0 的天数 / 总天数
  衰减 = 在 N 日后的 IC (1/3/5/10/20 日)

数据源:
  historical_kline (历史 K 线) — 用纯价格因子 (不需要历史 PE/PB)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from database import query_all

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#  因子定义 (纯价格/技术因子, 不依赖历史 PE/PB)
# ═══════════════════════════════════════════════════════════

def _factor_ret_n(closes: np.ndarray, n: int) -> np.ndarray:
    """N 日收益率"""
    out = np.full_like(closes, np.nan)
    if len(closes) > n:
        out[n:] = (closes[n:] - closes[:-n]) / closes[:-n]
    return out


def _factor_ma(closes: np.ndarray, n: int) -> np.ndarray:
    """N 日均线"""
    return pd.Series(closes).rolling(n).mean().values


def _factor_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI"""
    diff = np.diff(closes, prepend=closes[0])
    gains = np.where(diff > 0, diff, 0)
    losses = np.where(diff < 0, -diff, 0)
    avg_gain = pd.Series(gains).rolling(period).mean().values
    avg_loss = pd.Series(losses).rolling(period).mean().values
    rs = avg_gain / np.where(avg_loss == 0, 1e-9, avg_loss)
    return 100 - 100 / (1 + rs)


def _factor_macd_signal(closes: np.ndarray) -> np.ndarray:
    """MACD 信号: DIF - DEA > 0 ? 1 : -1"""
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    return np.where(dif > dea, 1.0, -1.0)


def _factor_volatility(closes: np.ndarray, n: int = 20) -> np.ndarray:
    """N 日波动率 (年化)"""
    rets = pd.Series(closes).pct_change().values
    return pd.Series(rets).rolling(n).std().values * np.sqrt(252)


def _factor_amplitude(closes: np.ndarray, n: int = 20) -> np.ndarray:
    """N 日振幅"""
    out = np.full_like(closes, np.nan)
    for i in range(n, len(closes)):
        window = closes[i - n:i + 1]
        out[i] = (window.max() - window.min()) / window[i - n]
    return out


def _factor_ma_disp(closes: np.ndarray) -> np.ndarray:
    """MA5 > MA20 ? 1 : -1 (均线多头排列)"""
    ma5 = _factor_ma(closes, 5)
    ma20 = _factor_ma(closes, 20)
    return np.where(ma5 > ma20, 1.0, -1.0)


def _factor_vol_ratio(volumes: np.ndarray, n: int = 5) -> np.ndarray:
    """成交量比 = VOL_N / VOL_N*5 (短期量能)"""
    vol_n = _factor_ma(volumes, n)
    vol_5n = _factor_ma(volumes, n * 5)
    return vol_n / np.where(vol_5n == 0, 1e-9, vol_5n)


def _factor_price_pos(closes: np.ndarray, n: int = 20) -> np.ndarray:
    """价格在 N 日布林带位置"""
    ma = _factor_ma(closes, n)
    std = pd.Series(closes).rolling(n).std().values
    upper = ma + 2 * std
    lower = ma - 2 * std
    return (closes - lower) / np.where(upper - lower == 0, 1e-9, upper - lower)


def _factor_autocorr_beta(closes: np.ndarray, n: int = 20) -> np.ndarray:
    """v4.0 B1: N 日自回归 beta(收益持续性 1-day lag)

    对每个时点 t,计算 rets[t-N+1:t+1] 与 lag1 rets 的协方差 / 方差。
    趋近 1 = 强趋势;趋近 0 = 均值回归。
    """
    n_total = len(closes)
    out = np.zeros(n_total)
    if n_total < n + 2:
        return out
    rets = np.diff(closes) / np.where(closes[:-1] == 0, 1e-9, closes[:-1])
    for t in range(n, n_total - 1):
        window_now = rets[t - n + 1:t + 1]    # 长度 n
        window_lag = rets[t - n:t]            # 长度 n,lag1
        if len(window_now) < 5 or len(window_lag) < 5:
            continue
        m_now = window_now.mean()
        m_lag = window_lag.mean()
        cov = ((window_now - m_now) * (window_lag - m_lag)).mean()
        var_lag = ((window_lag - m_lag) ** 2).mean()
        if var_lag > 1e-12:
            out[t + 1] = cov / var_lag
    return out


# 因子注册表: name -> (function, requires_volume)
FACTOR_REGISTRY = {
    "ret_5d":       (lambda c, v: _factor_ret_n(c, 5),    False),
    "ret_10d":      (lambda c, v: _factor_ret_n(c, 10),   False),
    "ret_20d":      (lambda c, v: _factor_ret_n(c, 20),   False),
    "ret_60d":      (lambda c, v: _factor_ret_n(c, 60),   False),
    "ma5":          (lambda c, v: _factor_ma(c, 5),       False),
    "ma10":         (lambda c, v: _factor_ma(c, 10),      False),
    "ma20":         (lambda c, v: _factor_ma(c, 20),      False),
    "ma60":         (lambda c, v: _factor_ma(c, 60),      False),
    "rsi_14":       (lambda c, v: _factor_rsi(c, 14),     False),
    "macd_signal":  (lambda c, v: _factor_macd_signal(c), False),
    "volatility":   (lambda c, v: _factor_volatility(c),  False),
    "amplitude":    (lambda c, v: _factor_amplitude(c),   False),
    "ma_disposition": (lambda c, v: _factor_ma_disp(c),   False),
    "vol_ratio":    (lambda c, v: _factor_vol_ratio(v),   True),
    "price_pos":    (lambda c, v: _factor_price_pos(c),   False),

    # ── v4.0 B1 Alpha158 Batch 1 (11 个 — K线形态 4 个需 OHLC,本注册表不接) ──
    # 变化率(基于 ret_n)
    "roc5":         (lambda c, v: _factor_ret_n(c, 5),    False),
    "roc10":        (lambda c, v: _factor_ret_n(c, 10),   False),
    "roc20":        (lambda c, v: _factor_ret_n(c, 20),   False),
    "roc60":        (lambda c, v: _factor_ret_n(c, 60),   False),
    # 偏离度(基于 MA)
    "deviation10":  (lambda c, v: (c - _factor_ma(c, 10)) / np.where(_factor_ma(c, 10) == 0, 1e-9, _factor_ma(c, 10)), False),
    "deviation20":  (lambda c, v: (c - _factor_ma(c, 20)) / np.where(_factor_ma(c, 20) == 0, 1e-9, _factor_ma(c, 20)), False),
    # 价格变异系数(std/mean)
    "std5":         (lambda c, v: pd.Series(c).rolling(5).std().div(pd.Series(c).rolling(5).mean()).fillna(0).values if len(c) >= 5 else np.zeros_like(c), False),
    "std20":        (lambda c, v: pd.Series(c).rolling(20).std().div(pd.Series(c).rolling(20).mean()).fillna(0).values if len(c) >= 20 else np.zeros_like(c), False),
    # 自回归 beta
    "beta20":       (lambda c, v: _factor_autocorr_beta(c, 20), False),
    # 量能变化率
    "vroc10":       (lambda c, v: pd.Series(v).pct_change(10).fillna(0).values if v is not None and len(v) > 10 else np.zeros_like(c), True),
    # 价量相关性
    "corr20":       (lambda c, v: pd.Series(c).rolling(20).corr(pd.Series(v)).fillna(0).values if v is not None and len(c) >= 20 else np.zeros_like(c), True),
}

# ═══════════════════════════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════════════════════════

# 股票池预设
STOCK_POOLS = {
    "all":      "全 A 股",
    "hs300":    "沪深 300",
    "csi500":   "中证 500",
    "csi800":   "沪深 300 + 中证 500",
}


def get_stock_pool(pool: str) -> list[str]:
    """获取股票池代码列表"""
    con = None
    try:
        if pool == "all":
            rows = query_all("SELECT stock_code FROM stock_info")
        elif pool == "hs300":
            rows = query_all("SELECT stock_code FROM stock_info WHERE industry IS NOT NULL LIMIT 300")
        elif pool == "csi500":
            rows = query_all("SELECT stock_code FROM stock_info WHERE industry IS NOT NULL LIMIT 500")
        elif pool == "csi800":
            rows = query_all("SELECT stock_code FROM stock_info WHERE industry IS NOT NULL LIMIT 800")
        else:
            rows = query_all("SELECT stock_code FROM stock_info")
        return [r["stock_code"] for r in rows]
    except Exception as e:
        logger.error("get_stock_pool(%s) failed: %s", pool, str(e)[:200])
        return []


def load_kline_panel(stock_codes: list[str], start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    """加载一批股票的 K 线面板 (dict: code -> DataFrame)

    使用 SQL: SELECT stock_code, trade_date, close, volume FROM historical_kline
              WHERE trade_date BETWEEN ? AND ? AND stock_code IN (...)
    """
    if not stock_codes:
        return {}

    placeholders = ",".join("?" * len(stock_codes))
    sql = f"""
        SELECT stock_code, trade_date, close, volume
        FROM historical_kline
        WHERE trade_date BETWEEN ? AND ?
          AND stock_code IN ({placeholders})
        ORDER BY stock_code, trade_date
    """
    params = [start_date, end_date] + list(stock_codes)
    rows = query_all(sql, tuple(params))

    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=["stock_code", "trade_date", "close", "volume"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    # 按 stock_code 切分
    panels = {}
    for code, group in df.groupby("stock_code"):
        g = group.set_index("trade_date").sort_index()
        if len(g) >= 60:  # 至少 60 个交易日
            panels[code] = g
    return panels


# ═══════════════════════════════════════════════════════════
#  IC 计算
# ═══════════════════════════════════════════════════════════

def _build_factor_panel(panels: dict[str, pd.DataFrame], factor_name: str) -> pd.DataFrame:
    """对所有股票计算某个因子, 返回 wide panel (index=date, columns=stock_code)"""
    func, needs_volume = FACTOR_REGISTRY[factor_name]
    series_dict = {}
    for code, df in panels.items():
        closes = df["close"].values
        volumes = df["volume"].values if needs_volume else None
        try:
            values = func(closes, volumes)
            s = pd.Series(values, index=df.index, name=code)
            series_dict[code] = s
        except Exception:
            continue
    if not series_dict:
        return pd.DataFrame()
    return pd.DataFrame(series_dict)


def _pearson_daily(factor_panel: pd.DataFrame, return_panel: pd.DataFrame) -> pd.Series:
    """每日计算 Pearson(factor_t, return_{t+1})"""
    # shift(-1) 让 return_t 对应 t+1 日的收益
    forward_returns = return_panel.shift(-1)
    ic_values = {}
    for date in factor_panel.index:
        f = factor_panel.loc[date].dropna()
        r = forward_returns.loc[date].dropna()
        common = f.index.intersection(r.index)
        if len(common) < 30:  # 至少 30 只股票
            continue
        f_vals = f[common].values.astype(float)
        r_vals = r[common].values.astype(float)
        if np.std(f_vals) < 1e-9 or np.std(r_vals) < 1e-9:
            continue
        try:
            corr = np.corrcoef(f_vals, r_vals)[0, 1]
            if not np.isnan(corr):
                ic_values[date] = float(corr)
        except Exception:
            continue
    return pd.Series(ic_values).sort_index()


def _compute_decay_score(ic_decay: dict) -> dict:
    """根据 IC 衰减速度打分 (0-100)

    规则（基于明日计划 2026-07-17）：
      - 取 1 日 IC 和 5 日 IC 计算相对衰减
      - 衰减 > 50%   → "rapid_decay" / red    (建议退役)
      - 衰减 20-50%  → "decay_warning" / yellow (观察)
      - 衰减 ≤ 20%   → "stable" / green (健康)

    Args:
        ic_decay: {1: float, 5: float, 10: float, 20: float} 各周期 IC

    Returns:
        {
            "score": int,           # 0-100，越高越稳定
            "status": str,          # stable | decay_warning | rapid_decay | insufficient_data
            "color": str,           # green | yellow | red | gray
            "decay_pct": float,     # 1→5 日 IC 相对衰减（绝对值）
            "label": str,           # 人类可读中文标签
        }
    """
    ic_1 = ic_decay.get(1)
    ic_5 = ic_decay.get(5)
    if ic_1 is None or ic_5 is None:
        return {"score": None, "status": "insufficient_data", "color": "gray",
                "decay_pct": None, "label": "数据不足"}

    # IC_1 接近 0 → 因子本身信号弱，无衰减意义
    if abs(ic_1) < 1e-4:
        return {"score": 50, "status": "weak_signal", "color": "gray",
                "decay_pct": 0.0, "label": "信号弱"}

    # 相对衰减：只看幅度，方向由分数反映
    decay_pct = (ic_1 - ic_5) / abs(ic_1)
    decay_pct_abs = abs(decay_pct)

    # 0-100 分数：衰减 0% → 100 分，衰减 100% → 0 分
    score = max(0, min(100, round(100 * (1 - decay_pct_abs))))

    if decay_pct_abs > 0.5:
        status, color, label = "rapid_decay", "red", "快速衰减"
    elif decay_pct_abs > 0.2:
        status, color, label = "decay_warning", "yellow", "缓慢衰减"
    else:
        status, color, label = "stable", "green", "稳定"

    return {
        "score": score,
        "status": status,
        "color": color,
        "decay_pct": round(decay_pct_abs, 4),
        "label": label,
    }


def compute_factor_metrics(factor_names: list[str], stock_pool: str = "all",
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> dict:
    """计算一组因子的 IC 指标

    Returns:
        {
            'period': {'start': ..., 'end': ...},
            'pool': stock_pool,
            'stock_count': N,
            'factors': {
                'ret_5d': {
                    'ic_mean': 0.023,
                    'ic_std': 0.045,
                    'ir': 0.51,
                    'win_rate': 0.62,
                    'ic_decay': {1: 0.023, 5: 0.018, 10: 0.012, 20: 0.005},
                    'turnover': 0.85,
                    'ic_series': [(date_str, ic_value), ...],
                    'valid_days': 240,
                },
                ...
            }
        }
    """
    # 默认日期范围
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    logger.info("IC compute: pool=%s, dates=%s..%s, factors=%d",
                stock_pool, start_date, end_date, len(factor_names))

    # 加载股票池和 K 线
    stock_codes = get_stock_pool(stock_pool)
    if not stock_codes:
        return {"error": "股票池为空", "factors": {}}

    panels = load_kline_panel(stock_codes, start_date, end_date)
    if not panels:
        return {"error": "K 线数据为空", "factors": {}}

    # 计算 return panel (close-to-close 日收益)
    return_panel = pd.DataFrame({
        code: df["close"].pct_change() for code, df in panels.items()
    })

    result_factors = {}
    for factor_name in factor_names:
        if factor_name not in FACTOR_REGISTRY:
            continue
        try:
            factor_panel = _build_factor_panel(panels, factor_name)
            if factor_panel.empty:
                continue

            ic_series = _pearson_daily(factor_panel, return_panel)
            if len(ic_series) < 30:
                continue

            # 指标
            ic_mean = float(ic_series.mean())
            ic_std = float(ic_series.std())
            ir = ic_mean / ic_std if ic_std > 1e-9 else 0.0
            win_rate = float((ic_series > 0).sum() / len(ic_series))

            # 衰减: 计算 N 日后的 IC
            decay = {}
            for n_days in [1, 5, 10, 20]:
                # N 日 forward return
                fwd_ret = (1 + return_panel).rolling(n_days).apply(np.prod, raw=True) - 1
                fwd_ret = fwd_ret.shift(-n_days)
                ic_n = {}
                for date in factor_panel.index:
                    f = factor_panel.loc[date].dropna()
                    r = fwd_ret.loc[date].dropna() if date in fwd_ret.index else pd.Series()
                    common = f.index.intersection(r.index)
                    if len(common) < 30:
                        continue
                    f_vals = f[common].values.astype(float)
                    r_vals = r[common].values.astype(float)
                    if np.std(f_vals) < 1e-9 or np.std(r_vals) < 1e-9:
                        continue
                    try:
                        c = np.corrcoef(f_vals, r_vals)[0, 1]
                        if not np.isnan(c):
                            ic_n[date] = float(c)
                    except Exception:
                        continue
                if ic_n:
                    decay[n_days] = float(np.mean(list(ic_n.values())))

            # 换手率: 因子排名日变化
            daily_rank_changes = []
            for date in factor_panel.index:
                if date not in factor_panel.index:
                    continue
                pass
            # 简化: 用 IC 时序的 1 日自相关 (1 - |corr|) 作为换手代理
            turnover = float(1 - abs(np.corrcoef(ic_series.values[:-1], ic_series.values[1:])[0, 1])) \
                if len(ic_series) > 2 else 0.0

            # IC 时序精简: 每 5 个交易日取 1 个 (避免返回太大)
            ic_series_sparse = [
                (d.strftime("%Y-%m-%d"), round(float(v), 5))
                for d, v in ic_series.iloc[::5].items()
            ]

            result_factors[factor_name] = {
                "ic_mean": round(ic_mean, 5),
                "ic_std": round(ic_std, 5),
                "ir": round(ir, 3),
                "win_rate": round(win_rate, 3),
                "ic_decay": {k: round(v, 5) for k, v in decay.items()},
                "decay_score": _compute_decay_score(decay),
                "turnover": round(turnover, 3),
                "ic_series": ic_series_sparse,
                "valid_days": int(len(ic_series)),
            }
        except Exception as e:
            logger.warning("compute_factor_metrics(%s) failed: %s", factor_name, str(e)[:200])

    return {
        "period": {"start": start_date, "end": end_date},
        "pool": stock_pool,
        "stock_count": len(panels),
        "factor_count": len(result_factors),
        "factors": result_factors,
    }


# ═══════════════════════════════════════════════════════════
#  相关性矩阵
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  因子排行榜 (P0-1) — 一张可排序表,聚合 IC / IR / Turnover / Decay
#  复用 compute_factor_metrics 计算结果,按 |IR| 排序
# ═══════════════════════════════════════════════════════════════


def compute_factor_leaderboard(
    factors: list[str] | None = None,
    stock_pool: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """全因子排行榜 — 给前端做可排序表格

    返回扁平列表,每行一个因子:
      [{name, ic_mean, ic_std, ir, win_rate, turnover,
        decay_score, decay_status, decay_color, valid_days}, ...]

    前端按 ir / abs_ic / win_rate 排序,加 🟢🟡🔴 状态徽章。
    """
    if not factors:
        factors = list(FACTOR_REGISTRY.keys())

    logger.info(
        "leaderboard: pool=%s, dates=%s..%s, factors=%d",
        stock_pool, start_date, end_date, len(factors),
    )

    # 复用现有 IC 计算(已含 turnover / decay_score)
    metrics = compute_factor_metrics(
        factors, stock_pool, start_date, end_date,
    )

    rows = []
    for name, m in metrics.get("factors", {}).items():
        if "error" in m or m.get("valid_days", 0) < 30:
            continue
        decay = m.get("decay_score") or {}
        rows.append({
            "name": name,
            "ic_mean": m.get("ic_mean", 0),
            "ic_std": m.get("ic_std", 0),
            "ir": m.get("ir", 0),
            "win_rate": m.get("win_rate", 0),
            "turnover": m.get("turnover", 0),
            "decay_score": decay.get("score"),
            "decay_status": decay.get("status", "unknown"),
            "decay_color": decay.get("color", "gray"),
            "decay_label": decay.get("label", ""),
            "decay_pct": decay.get("decay_pct"),
            "valid_days": m.get("valid_days", 0),
        })

    # 默认按 |IR| 降序(最强因子在前)
    rows.sort(key=lambda r: abs(r["ir"]), reverse=True)

    return {
        "period": metrics.get("period", {}),
        "pool": stock_pool,
        "stock_count": metrics.get("stock_count", 0),
        "total": len(rows),
        "rows": rows,
    }


# ═══════════════════════════════════════════════════════════════
#  分位数收益 (P0-2) — 教科书级 quant 图:5 等分累计收益 + 多空对冲
#
#  算法 (alphalens 风格):
#    1. 对每个交易日,按因子值对股票排序
#    2. 分成 N 组(Q1=最差 ~ QN=最好)
#    3. 每组等权持有,次日 close-to-close 收益
#    4. 累计收益 = cumprod(1 + daily_ret)
#    5. 多空对冲 = QN - Q1 每日收益 → cumprod
#
#  这是验证因子"区分度"的金标准:一条单调上升的 5 条线 = 好因子
# ═══════════════════════════════════════════════════════════════


def compute_quantile_returns(
    factor_name: str,
    stock_pool: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    n_groups: int = 5,
) -> dict:
    """分位数收益图数据

    Args:
        factor_name: 因子名
        n_groups: 分组数(默认 5)

    Returns:
        {
            'factor': factor_name,
            'period': {...},
            'pool': ...,
            'n_groups': 5,
            'dates': [...],
            'groups': [{'group': 1, 'label': ..., 'daily_ret': [...], 'cumret': [...]}, ...],
            'long_short': {'daily_ret': [...], 'cumret': [...]},
            'summary': {
                'q1_cumret': ..., 'q5_cumret': ..., 'long_short_cumret': ...,
                'monotonic': bool, 'long_short_sharpe': ...,
            },
        }
    """
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    if factor_name not in FACTOR_REGISTRY:
        return {"error": f"未知因子: {factor_name}"}

    stock_codes = get_stock_pool(stock_pool)
    if not stock_codes:
        return {"error": "股票池为空", "groups": []}

    panels = load_kline_panel(stock_codes, start_date, end_date)
    if not panels:
        return {"error": "K 线数据为空", "groups": []}

    # 因子 panel (date × stock)
    factor_panel = _build_factor_panel(panels, factor_name)
    if factor_panel.empty:
        return {"error": f"因子 {factor_name} 数据为空", "groups": []}

    # 收益 panel (t 日因子 → t+1 日 close-to-close return)
    return_panel = pd.DataFrame({
        code: df["close"].pct_change() for code, df in panels.items()
    })
    fwd_ret = return_panel.shift(-1)

    # 对每个交易日,把股票按因子值排序,分组成 N 等分
    common_dates = factor_panel.index.intersection(fwd_ret.index)
    if len(common_dates) < 30:
        return {"error": f"有效日期不足: {len(common_dates)}", "groups": []}

    daily_group_ret: dict[int, list[float]] = {g: [] for g in range(1, n_groups + 1)}
    daily_dates: list[str] = []

    for date in common_dates:
        f_vals = factor_panel.loc[date].dropna()
        r_vals = fwd_ret.loc[date].dropna() if date in fwd_ret.index else pd.Series()
        common = f_vals.index.intersection(r_vals.index)
        if len(common) < n_groups * 2:  # 每组至少 2 只
            continue
        f_aligned = f_vals[common]
        r_aligned = r_vals[common]

        try:
            groups = pd.qcut(
                f_aligned.rank(method="first"),
                q=n_groups,
                labels=False,
            ) + 1  # 1-indexed
        except ValueError:
            continue  # qcut 失败(太多重复值)

        for g in range(1, n_groups + 1):
            mask = (groups == g)
            if mask.sum() == 0:
                continue
            group_ret = float(r_aligned[mask].mean())
            daily_group_ret[g].append(group_ret)

        daily_dates.append(date.strftime("%Y-%m-%d"))

    if not daily_dates:
        return {"error": "无有效分组数据", "groups": []}

    # 累计收益 (cumprod)
    groups_result = []
    for g in range(1, n_groups + 1):
        rets = daily_group_ret[g]
        cumret = np.cumprod(1 + np.array(rets)) - 1
        groups_result.append({
            "group": g,
            "label": f"Q{g} ({'最差' if g == 1 else '最好' if g == n_groups else '中位'})",
            "daily_ret": [round(float(r), 6) for r in rets],
            "cumret": [round(float(c), 6) for c in cumret],
        })

    # 多空对冲: QN - Q1
    long = np.array(daily_group_ret[n_groups])
    short = np.array(daily_group_ret[1])
    ls_daily = long - short
    ls_cumret = np.cumprod(1 + ls_daily) - 1
    long_short = {
        "daily_ret": [round(float(r), 6) for r in ls_daily],
        "cumret": [round(float(c), 6) for c in ls_cumret],
    }

    # 摘要 + 单调性检查
    q1_final = groups_result[0]["cumret"][-1]
    q5_final = groups_result[-1]["cumret"][-1]
    ls_final = ls_cumret[-1]

    # 单调: 5 组期末累计收益递增
    final_cumrets = [g["cumret"][-1] for g in groups_result]
    monotonic = all(
        final_cumrets[i] <= final_cumrets[i + 1]
        for i in range(n_groups - 1)
    )

    summary = {
        "q1_cumret": round(float(q1_final), 4),
        "q5_cumret": round(float(q5_final), 4),
        "long_short_cumret": round(float(ls_final), 4),
        "monotonic": bool(monotonic),
        "long_short_sharpe": round(
            float(np.mean(ls_daily) / np.std(ls_daily) * np.sqrt(252))
            if np.std(ls_daily) > 1e-9 else 0.0,
            3,
        ),
    }

    return {
        "factor": factor_name,
        "period": {"start": start_date, "end": end_date},
        "pool": stock_pool,
        "n_groups": n_groups,
        "dates": daily_dates,
        "groups": groups_result,
        "long_short": long_short,
        "summary": summary,
    }


def compute_correlation_matrix(factor_names: list[str], stock_pool: str = "all",
                                start_date: Optional[str] = None,
                                end_date: Optional[str] = None) -> dict:
    """计算因子相关性矩阵 (Pearson, 基于每日因子值)

    Returns:
        {
            'factors': ['ret_5d', 'ret_10d', ...],
            'matrix': [[1.0, 0.45, ...], ...],  # N×N
            'pool': stock_pool,
            'stock_count': N,
        }
    """
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    stock_codes = get_stock_pool(stock_pool)
    panels = load_kline_panel(stock_codes, start_date, end_date)
    if not panels:
        return {"factors": factor_names, "matrix": [], "pool": stock_pool, "stock_count": 0}

    # 对每个因子算每日因子值, 然后 stack 成 (date, stock) -> factor_value
    factor_panels = {}
    for fname in factor_names:
        if fname not in FACTOR_REGISTRY:
            continue
        factor_panels[fname] = _build_factor_panel(panels, fname)

    if not factor_panels:
        return {"factors": factor_names, "matrix": [], "pool": stock_pool, "stock_count": len(panels)}

    # 取所有因子的最近一日因子值, 算横截面相关性
    # 或者: 把所有 (date, stock) flatten 后算时序相关性
    # 选后者: 更稳定, 用所有日期-股票对

    # 各因子 stack 成 Series
    stacked = {}
    common_index = None
    for fname, fp in factor_panels.items():
        if fp.empty:
            continue
        s = fp.stack().dropna()
        if common_index is None:
            common_index = s.index
        else:
            common_index = common_index.intersection(s.index)
        stacked[fname] = s.reindex(common_index)

    if not stacked or len(common_index) < 100:
        return {"factors": list(stacked.keys()), "matrix": [], "pool": stock_pool, "stock_count": len(panels)}

    df = pd.DataFrame(stacked)
    corr = df.corr()

    return {
        "factors": list(corr.columns),
        "matrix": [[round(float(corr.iloc[i, j]), 4) for j in range(len(corr.columns))] for i in range(len(corr))],
        "pool": stock_pool,
        "stock_count": len(panels),
        "start_date": start_date,
        "end_date": end_date,
    }


# ═══════════════════════════════════════════════════════════════
#  层次聚类 (P1-1) — 把 N 个因子按相关性自动聚成树状图
#
#  算法 (scipy 标准):
#    1. 算因子相关性矩阵
#    2. 转距离矩阵: d = 1 - |corr| (避免 -1~1 映射到 0~2 不直观)
#    3. linkage(method='average') — 平均连接(对噪声稳健)
#    4. fcluster 切簇(或保留完整树给前端)
#
#  返回:
#    - tree: 嵌套 dict 树状结构,前端可直接渲染 SVG
#    - groups: 按 distance 阈值切出的扁平簇列表
# ═══════════════════════════════════════════════════════════════


def compute_factor_clustering(
    factors: list[str],
    stock_pool: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    distance_threshold: float = 0.3,
) -> dict:
    """层次聚类树 — 把相似因子归组,解决"55 因子一团乱麻"问题

    Args:
        factors: 因子列表
        distance_threshold: 切簇阈值(0~1)
          - 0.2: 严格聚类(只把强相关因子合一起,适合去重)
          - 0.3: 默认(经验值)
          - 0.5: 宽松聚类(把中等相关的也合一起,适合分类)

    Returns:
        {
            'factors': [...],
            'tree': {id, children: [{name, distance, cluster_id}, ...]},
            'groups': [{id, factors: [...], avg_corr, distance}, ...],
            'summary': {n_factors, n_clusters, method, threshold},
            'period': {start, end},
            'pool': ...,
        }
    """
    if len(factors) < 2:
        return {
            "error": "至少需要 2 个因子才能聚类",
            "factors": factors, "tree": {}, "groups": [],
        }

    # 1. 复用相关性计算
    corr_result = compute_correlation_matrix(
        factors, stock_pool, start_date, end_date,
    )
    factor_names: list[str] = corr_result.get("factors", [])
    matrix: list[list[float]] = corr_result.get("matrix", [])

    if len(factor_names) < 2 or not matrix:
        return {
            "error": "相关性矩阵为空(数据不足)",
            "factors": factor_names, "tree": {}, "groups": [],
        }

    # 2. 转距离矩阵 (1 - |corr|): corr=1 → dist=0, corr=0 → dist=1, corr=-1 → dist=2
    n = len(factor_names)
    import numpy as np
    corr_arr = np.array(matrix, dtype=float)
    dist = 1.0 - np.abs(corr_arr)
    np.fill_diagonal(dist, 0.0)

    # 3. linkage + fcluster
    try:
        from scipy.cluster.hierarchy import linkage, fcluster
        from scipy.spatial.distance import squareform
    except ImportError:
        return {
            "error": "scipy 未安装,请 pip install scipy",
            "factors": factor_names, "tree": {}, "groups": [],
        }

    # squareform 要求严格的下三角(对角为 0)
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method="average")
    cluster_labels = fcluster(Z, t=distance_threshold, criterion="distance")

    # 4. 按簇号分组
    groups_dict: dict[int, list[int]] = {}
    for i, label in enumerate(cluster_labels):
        groups_dict.setdefault(int(label), []).append(i)

    # 5. 扁平簇列表(用于卡片展示)
    groups_list = []
    for cid, idxs in sorted(groups_dict.items(), key=lambda x: min(x[1])):
        # 计算簇内平均相关性
        if len(idxs) >= 2:
            sub_corr = corr_arr[np.ix_(idxs, idxs)]
            # 上三角均值(排除对角)
            triu = sub_corr[np.triu_indices(len(idxs), k=1)]
            avg_corr = float(np.mean(np.abs(triu)))
        else:
            avg_corr = 1.0  # 单因子簇

        groups_list.append({
            "id": int(cid),
            "factors": [factor_names[i] for i in idxs],
            "size": len(idxs),
            "avg_corr": round(avg_corr, 4),
            "distance": round(1.0 - avg_corr, 4),
        })

    # 6. 构建嵌套树结构(供前端 SVG 渲染)
    # linkage 矩阵的 row i 合并 cluster i+n,连接 (Z[i,0], Z[i,1]) at Z[i,2]
    # 我们用 cluster_id = i + n 表示非叶节点
    tree = _build_cluster_tree(factor_names, Z)

    return {
        "factors": factor_names,
        "tree": tree,
        "groups": groups_list,
        "summary": {
            "n_factors": n,
            "n_clusters": len(groups_list),
            "method": "average",
            "threshold": distance_threshold,
        },
        "period": corr_result.get("start_date") or start_date,
        "end_date": corr_result.get("end_date"),
        "pool": stock_pool,
        "stock_count": corr_result.get("stock_count", 0),
    }


def _build_cluster_tree(factor_names: list[str], Z) -> dict:
    """从 scipy linkage 矩阵构建嵌套 dict 树

    叶子节点: {"name": factor_name, "cluster_id": -i-1}
    内部节点: {"cluster_id": i, "distance": float, "children": [...]}
    根节点: {"cluster_id": "root", "children": [...]}
    """
    n = len(factor_names)
    # 创建所有节点
    nodes: dict[int, dict] = {}
    for i, name in enumerate(factor_names):
        nodes[i] = {
            "name": name,
            "cluster_id": -(i + 1),  # 负数表示叶
            "distance": 0.0,
            "is_leaf": True,
        }

    # 自底向上合并
    for i, (left, right, dist, size) in enumerate(Z):
        left = int(left)
        right = int(right)
        new_id = n + i
        nodes[new_id] = {
            "cluster_id": new_id,
            "distance": round(float(dist), 4),
            "size": int(size),
            "is_leaf": False,
            "children": [nodes[left], nodes[right]],
        }

    root_id = n + len(Z) - 1
    root = nodes[root_id]
    root["cluster_id"] = "root"
    return root


# ═══════════════════════════════════════════════════════════════
#  因子瀑布图 (P1-2) — 某只股票的 alpha 因子归因
#
#  算法 (教科书 factor contribution decomposition):
#    1. 选定截面日(默认最新交易日)
#    2. 对每只股票算每个因子的截面 z-score(标准化)
#    3. weight = 该因子的 IC mean(过去 N 日)
#    4. contribution = z_score × weight
#    5. 总 alpha = sum(contributions)  →  预测次日收益
#
#  这是"为什么 AI 选了这只股票"的可解释归因
# ═══════════════════════════════════════════════════════════════


def compute_factor_contribution(
    stock_code: str,
    factors: list[str],
    stock_pool: str = "hs300",
    as_of_date: Optional[str] = None,
    lookback_days: int = 120,
) -> dict:
    """因子瀑布图 — 单只股票的 alpha 因子归因

    Args:
        stock_code: 股票代码 (e.g. "600519")
        factors: 因子名列表
        stock_pool: 对比股票池(用于截面 z-score 标准化)
        as_of_date: 截面日(默认最新交易日)
        lookback_days: IC mean 估算回看窗口(默认 120 日)

    Returns:
        {
            'stock': '600519',
            'as_of_date': '2026-07-30',
            'total_alpha': 0.025,         # 预测次日收益 (sum of contributions)
            'contributions': [            # 按 |contribution| 降序
                {
                    'factor': 'ret_5d',
                    'z_score': 1.85,        # 标准化后的因子值
                    'raw_value': 0.12,      # 原始因子值
                    'ic_weight': 0.0085,    # 该因子的 IC mean
                    'contribution': 0.0157, # = z_score × ic_weight
                    'direction': 'long',    # 正 = 看多,负 = 看空
                },
                ...
            ],
            'summary': {
                'n_long': 5,
                'n_short': 3,
                'top_contributor': 'ret_5d',
                'bottom_contributor': 'volatility_20',
            }
        }
    """
    if not factors:
        factors = list(FACTOR_REGISTRY.keys())[:10]  # 默认 10 因子

    # 默认截面日 = 最新可用交易日
    if not as_of_date:
        from database import query_one
        r = query_one("SELECT MAX(trade_date) as d FROM historical_kline WHERE stock_code = ?", (stock_code,))
        if not r or not r["d"]:
            return {"error": f"股票 {stock_code} 无 K 线数据"}
        as_of_date = r["d"]

    # 计算 lookback 日期范围
    end_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=int(lookback_days * 1.5))  # 多取一些以防数据缺口
    start_date = start_dt.strftime("%Y-%m-%d")

    # 1. 加载股票池 + 目标股票 K 线
    pool_codes = get_stock_pool(stock_pool)
    if not pool_codes:
        return {"error": f"股票池 {stock_pool} 为空"}

    # 目标股票必须在池里(否则截面标准化不公平)
    if stock_code not in pool_codes:
        return {"error": f"股票 {stock_code} 不在 {stock_pool} 池内"}

    panels = load_kline_panel(pool_codes, start_date, as_of_date)
    if not panels or stock_code not in panels:
        return {"error": f"加载 K 线失败: {stock_code}"}

    # 2. 截面日:每只股票每因子取当日因子值
    factor_panels: dict[str, pd.DataFrame] = {}
    for fname in factors:
        if fname not in FACTOR_REGISTRY:
            continue
        try:
            fp = _build_factor_panel(panels, fname)
            factor_panels[fname] = fp
        except Exception:
            continue

    if not factor_panels:
        return {"error": "无有效因子"}

    # 检查截面日是否在因子 panel 里
    target_date = pd.Timestamp(as_of_date)
    for fname, fp in factor_panels.items():
        if target_date not in fp.index:
            return {"error": f"截面日 {as_of_date} 无 {fname} 因子值"}

    # 3. 算截面 z-score
    cross_section = pd.DataFrame({
        fname: fp.loc[target_date] for fname, fp in factor_panels.items()
    })

    # 标准化: z = (x - mean) / std
    z_scores = (cross_section - cross_section.mean()) / cross_section.std().replace(0, 1)

    # 4. 算每个因子的 IC mean (lookback_days)
    # 用 shift(-1) 让 return_t 对应 t+1 日的收益(避免 look-ahead)
    return_panel = pd.DataFrame({
        code: df["close"].pct_change() for code, df in panels.items()
    })
    forward_return_panel = return_panel.shift(-1)

    contributions = []
    for fname in factors:
        if fname not in factor_panels:
            continue
        fp = factor_panels[fname]
        # IC mean over lookback_days
        recent_dates = fp.index[fp.index <= target_date][-lookback_days:]
        ic_values = []
        for d in recent_dates:
            f_vals = fp.loc[d].dropna()
            r_vals = forward_return_panel.loc[d].dropna() if d in forward_return_panel.index else pd.Series()
            common = f_vals.index.intersection(r_vals.index)
            if len(common) < 20:
                continue
            f_a = f_vals[common].values.astype(float)
            r_a = r_vals[common].values.astype(float)
            if np.std(f_a) < 1e-9 or np.std(r_a) < 1e-9:
                continue
            try:
                c = np.corrcoef(f_a, r_a)[0, 1]
                if not np.isnan(c):
                    ic_values.append(c)
            except Exception:
                continue

        if len(ic_values) < 10:
            continue

        ic_weight = float(np.mean(ic_values))

        # 该股票在截面日的因子值
        if stock_code not in cross_section.index or pd.isna(z_scores.loc[stock_code, fname]):
            continue
        z = float(z_scores.loc[stock_code, fname])
        raw = float(cross_section.loc[stock_code, fname])

        contrib = z * ic_weight
        contributions.append({
            "factor": fname,
            "z_score": round(z, 4),
            "raw_value": round(raw, 6),
            "ic_weight": round(ic_weight, 6),
            "contribution": round(contrib, 6),
            "direction": "long" if contrib > 0 else "short",
        })

    if not contributions:
        return {"error": "无有效贡献(可能因子 IC 数据不足)"}

    # 按 |contribution| 降序
    contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)

    total_alpha = sum(c["contribution"] for c in contributions)
    n_long = sum(1 for c in contributions if c["contribution"] > 0)
    n_short = sum(1 for c in contributions if c["contribution"] < 0)

    summary = {
        "n_long": n_long,
        "n_short": n_short,
        "top_contributor": contributions[0]["factor"] if contributions else None,
        "bottom_contributor": contributions[-1]["factor"] if contributions else None,
        "factor_count": len(contributions),
    }

    return {
        "stock": stock_code,
        "as_of_date": as_of_date,
        "total_alpha": round(total_alpha, 6),
        "contributions": contributions,
        "summary": summary,
        "lookback_days": lookback_days,
        "pool": stock_pool,
    }


# ═══════════════════════════════════════════════════════════════
#  平行坐标 (P2) — 多因子选股可视化
#
#  用法: 给定截面日 + N 个因子 + 股票池,返回每只股票在各因子上的得分
#  前端自渲染 SVG 平行坐标(每只股票一条折线,跨 N 个轴)
#  颜色: 综合等权得分高=绿,低=红
# ═══════════════════════════════════════════════════════════════


def compute_parallel_coordinates(
    factors: list[str],
    stock_pool: str = "hs300",
    as_of_date: Optional[str] = None,
    lookback_days: int = 120,
    top_n: int | None = None,
) -> dict:
    """平行坐标数据 — 给定截面日,每只股票的各因子 z-score

    Args:
        factors: 因子列表(2-8 个,太多会乱)
        stock_pool: 股票池
        as_of_date: 截面日(默认最新)
        lookback_days: IC mean 回看窗口
        top_n: 只返回综合得分 top N(默认全部)

    Returns:
        {
            'as_of_date': '2026-07-31',
            'factors': ['ret_5d', 'rsi_14', ...],
            'ic_weights': {factor: ic_mean},  # 用于前端显示轴标题权重
            'stocks': [
                {
                    'code': '000001',
                    'values': {factor1: z1, factor2: z2, ...},
                    'composite': 0.85,   # 等权 z-score 平均
                },
                ...
            ],
            'summary': {
                'n_stocks': 300,
                'n_factors': 4,
                'factor_ranges': {factor: (min, max)},
            }
        }
    """
    if len(factors) < 2:
        return {"error": "至少需要 2 个因子"}

    # 默认截面日
    if not as_of_date:
        from database import query_one
        r = query_one("SELECT MAX(trade_date) as d FROM historical_kline")
        if not r or not r["d"]:
            return {"error": "无 K 线数据"}
        as_of_date = r["d"]

    # 加载股票池 + K 线
    pool_codes = get_stock_pool(stock_pool)
    if not pool_codes:
        return {"error": f"股票池 {stock_pool} 为空"}

    end_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=int(lookback_days * 1.5))
    start_date = start_dt.strftime("%Y-%m-%d")

    panels = load_kline_panel(pool_codes, start_date, as_of_date)
    if not panels:
        return {"error": "K 线加载失败"}

    # 计算各因子 panel
    factor_panels: dict[str, pd.DataFrame] = {}
    for fname in factors:
        if fname not in FACTOR_REGISTRY:
            continue
        try:
            fp = _build_factor_panel(panels, fname)
            if not fp.empty:
                factor_panels[fname] = fp
        except Exception:
            continue

    if len(factor_panels) < 2:
        return {"error": f"有效因子不足 2 个(只剩 {len(factor_panels)})"}

    # 截面日提取
    target_date = pd.Timestamp(as_of_date)
    cross_section = pd.DataFrame({
        fname: fp.loc[target_date] for fname, fp in factor_panels.items()
        if target_date in fp.index
    })
    if cross_section.empty:
        return {"error": f"截面日 {as_of_date} 无有效因子值"}

    # 算 IC weights (lookback_days)
    return_panel = pd.DataFrame({
        code: df["close"].pct_change() for code, df in panels.items()
    })
    forward_return = return_panel.shift(-1)

    ic_weights: dict[str, float] = {}
    for fname, fp in factor_panels.items():
        recent_dates = fp.index[fp.index <= target_date][-lookback_days:]
        ic_vals = []
        for d in recent_dates:
            f_vals = fp.loc[d].dropna()
            r_vals = forward_return.loc[d].dropna() if d in forward_return.index else pd.Series()
            common = f_vals.index.intersection(r_vals.index)
            if len(common) < 20:
                continue
            f_a = f_vals[common].values.astype(float)
            r_a = r_vals[common].values.astype(float)
            if np.std(f_a) < 1e-9 or np.std(r_a) < 1e-9:
                continue
            try:
                c = np.corrcoef(f_a, r_a)[0, 1]
                if not np.isnan(c):
                    ic_vals.append(c)
            except Exception:
                continue
        if len(ic_vals) >= 10:
            ic_weights[fname] = round(float(np.mean(ic_vals)), 6)

    # 截面 z-score 标准化(对每个因子)
    z_scores = (cross_section - cross_section.mean()) / cross_section.std().replace(0, 1)

    # 综合得分: 等权平均(后续可加 IC 加权)
    composite = z_scores.mean(axis=1)

    # 构建 stocks 列表
    stocks = []
    for code in z_scores.index:
        row = z_scores.loc[code]
        if row.isna().all():
            continue
        vals = {fname: (round(float(row[fname]), 4) if not pd.isna(row[fname]) else 0.0)
                for fname in factor_panels.keys()}
        c = float(composite[code]) if not pd.isna(composite[code]) else 0.0
        stocks.append({
            "code": code,
            "values": vals,
            "composite": round(c, 4),
        })

    # 按 composite 降序
    stocks.sort(key=lambda s: s["composite"], reverse=True)
    if top_n:
        stocks = stocks[:top_n]

    # 因子值范围(前端定标用)
    factor_ranges = {}
    for fname in factor_panels.keys():
        col = z_scores[fname].dropna()
        if len(col) > 0:
            factor_ranges[fname] = {
                "min": round(float(col.min()), 2),
                "max": round(float(col.max()), 2),
                "mean": round(float(col.mean()), 4),
                "std": round(float(col.std()), 4),
            }

    return {
        "as_of_date": as_of_date,
        "factors": list(factor_panels.keys()),
        "ic_weights": ic_weights,
        "stocks": stocks,
        "summary": {
            "n_stocks": len(stocks),
            "n_factors": len(factor_panels),
            "factor_ranges": factor_ranges,
        },
        "pool": stock_pool,
    }


# ═══════════════════════════════════════════════════════════
#  散点数据
# ═══════════════════════════════════════════════════════════

def compute_scatter_data(factor_a: str, factor_b: str, stock_pool: str = "all",
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None,
                         sample: int = 500) -> dict:
    """计算两个因子的散点数据

    Returns:
        {
            'factor_a': ...,
            'factor_b': ...,
            'correlation': 0.45,
            'points': [
                {'code': '600519', 'date': '2026-07-15', 'x': 0.05, 'y': 0.02},
                ...
            ],
            'pool': stock_pool,
        }
    """
    empty = {
        "factor_a": factor_a,
        "factor_b": factor_b,
        "y_label": "次日 5 日累计收益",
        "correlation": 0,
        "points": [],
        "pool": stock_pool,
        "stock_count": 0,
        "date": None,
    }
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    stock_codes = get_stock_pool(stock_pool)
    panels = load_kline_panel(stock_codes, start_date, end_date)
    if not panels:
        return empty

    return_panel = pd.DataFrame({
        code: df["close"].pct_change() for code, df in panels.items()
    })
    # 5 日 forward return: close[t+5] / close[t] - 1 (未来 5 日收益)
    fwd_ret_5d = (return_panel.shift(-5).add(1, fill_value=1) ** 5 - 1) if False else \
        pd.DataFrame(
            {code: df["close"].shift(-5) / df["close"] - 1 for code, df in panels.items()}
        )

    fp_a = _build_factor_panel(panels, factor_a) if factor_a in FACTOR_REGISTRY else pd.DataFrame()
    fp_b = _build_factor_panel(panels, factor_b) if factor_b in FACTOR_REGISTRY else pd.DataFrame()

    if fp_a.empty or fp_b.empty:
        return empty

    # 取最近一个"足够完整"的横截面 (至少 80% 股票有数据, 且往前推 5 日还能取到 forward return)
    threshold = max(int(fp_a.shape[1] * 0.8), 30)
    complete_days = fp_a.notna().sum(axis=1)
    valid_days = complete_days[complete_days >= threshold]
    if valid_days.empty:
        return empty
    # forward return 跨 5 天, 所以 last_date 必须往前推 5 天
    # valid_days 与 fwd_ret_5d 取交集 (都用 index 顺序匹配)
    fwd_complete = fwd_ret_5d.notna().sum(axis=1)
    fwd_valid = fwd_complete[fwd_complete >= threshold]
    common_valid_days = valid_days.index.intersection(fwd_valid.index)
    if common_valid_days.empty:
        return empty
    last_date = common_valid_days.max()
    if last_date not in fwd_ret_5d.index:
        return empty

    a_vals = fp_a.loc[last_date].dropna()
    b_vals = fp_b.loc[last_date].dropna()
    r_vals = fwd_ret_5d.loc[last_date].dropna()

    common = a_vals.index.intersection(b_vals.index).intersection(r_vals.index)
    if len(common) < 30:
        return empty

    points = []
    for code in common:
        x = float(a_vals[code])
        next_ret = float(r_vals[code]) if code in r_vals.index else 0
        points.append({"code": code, "x": round(x, 4), "y": round(next_ret, 4)})

    # 抽样
    if len(points) > sample:
        step = len(points) // sample
        points = points[::step][:sample]

    corr_val = float(np.corrcoef(
        [p["x"] for p in points],
        [p["y"] for p in points]
    )[0, 1]) if len(points) > 2 else 0.0

    return {
        "factor_a": factor_a,
        "factor_b": factor_b,
        "y_label": "次日 5 日累计收益",
        "correlation": round(corr_val, 4),
        "pool": stock_pool,
        "date": last_date.strftime("%Y-%m-%d"),
        "stock_count": len(common),
        "points": points,
    }


# ═══════════════════════════════════════════════════════════
#  工具
# ═══════════════════════════════════════════════════════════

def list_available_factors() -> list[dict]:
    """列出可用的纯价格/技术因子"""
    return [
        {"name": name, "needs_volume": needs_vol}
        for name, (_, needs_vol) in FACTOR_REGISTRY.items()
    ]


def get_supported_pools() -> dict:
    """返回支持的股票池预设"""
    return STOCK_POOLS


# ═══════════════════════════════════════════════════════════
#  v4.0 Phase 2 — 因子 IC 重新校准
#  一次性跑全量注册表因子的 IC 分析,按 |IC| 排序输出
# ═══════════════════════════════════════════════════════════

# v4.0 B1 新增的 11 个因子(K线形态 4 个需 OHLC,本表不接)
B1_FACTORS_FOR_IC = [
    "roc5", "roc10", "roc20", "roc60",
    "deviation10", "deviation20",
    "std5", "std20",
    "beta20",
    "vroc10", "corr20",
]


def recalibrate_all_factors_ic(
    stock_pool: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_n: int = 15,
) -> dict:
    """v4.0 Phase 2: 重新校准所有因子的 IC,输出 |IC| 排序的 Top-N 排名

    覆盖范围:
      - 经典 15 个 (FACTOR_REGISTRY 中的 ret_*/ma*/rsi/macd 等)
      - v4.0 B1 新增 11 个 (roc*/deviation*/std*/beta20/vroc10/corr20)

    跳过: KLEN/KUP/KLOW/KSFT(需 OHLC 数据,本表不接)

    Args:
        stock_pool: 股票池
        start_date/end_date: 时间范围,默认最近 1 年
        top_n: 返回 Top-N 排名(按 |ic_mean| 降序)

    Returns:
        {
            'period': {'start', 'end'},
            'pool': stock_pool,
            'factor_count': int,
            'top_factors': [{name, ic_mean, ic_std, ir, win_rate, abs_ic}, ...],
            'b1_factors': [{name, ic_mean, ir, ...}, ...]  # 仅 B1
        }
    """
    # 1. 收集所有要计算的因子
    all_factor_names = list(FACTOR_REGISTRY.keys())
    b1_names = [n for n in B1_FACTORS_FOR_IC if n in FACTOR_REGISTRY]

    # 2. 复用现有 compute_factor_metrics(已实现 IC / IR / win_rate / decay)
    metrics_result = compute_factor_metrics(
        all_factor_names,
        stock_pool=stock_pool,
        start_date=start_date,
        end_date=end_date,
    )

    # 3. 构建排名
    factor_metrics = metrics_result.get("factors", {})
    ranked = []
    for name, m in factor_metrics.items():
        if "error" in m or m.get("valid_days", 0) < 30:
            continue  # 数据不足的因子跳过
        ic_mean = m.get("ic_mean", 0)
        ranked.append({
            "name": name,
            "ic_mean": round(ic_mean, 4),
            "ic_std": round(m.get("ic_std", 0), 4),
            "ir": round(m.get("ir", 0), 4),
            "win_rate": round(m.get("win_rate", 0), 4),
            "abs_ic": round(abs(ic_mean), 4),
            "valid_days": m.get("valid_days", 0),
            "is_b1": name in b1_names,
        })

    # 按 |ic_mean| 降序
    ranked.sort(key=lambda x: x["abs_ic"], reverse=True)

    # 4. 分别输出全榜 Top-N + 仅 B1 的结果
    b1_ranked = [r for r in ranked if r["is_b1"]]
    return {
        "period": metrics_result.get("period", {}),
        "pool": stock_pool,
        "factor_count": len(ranked),
        "top_factors": ranked[:top_n],
        "b1_factors": b1_ranked,
    }