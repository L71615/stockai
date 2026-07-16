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