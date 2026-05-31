"""量化分析服务：风控指标 / 相关性 / DCA回测 / 蒙特卡洛模拟 / 策略对比"""

import math
import random
from datetime import datetime, timedelta

from services.utils import get_market


# ==================== 内部消化策略 ====================
# 所有计算函数自己处理异常——NaN → None, ZeroDivision → 0, ValueError → None
# 调用方收到 None 时跳过该指标，前端显示 "--"


# ==================== 辅助函数 ====================

def _returns_from_prices(prices: list[float]) -> list[float]:
    """价格序列 → 日收益率序列"""
    if len(prices) < 2:
        return []
    return [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]


def _annualize_return(total_return: float, days: int) -> float:
    """累计收益率 → 年化收益率"""
    if days <= 0 or total_return <= -1:
        return 0.0
    return (1 + total_return) ** (365 / days) - 1


def _fetch_benchmark_returns(benchmark: str = "000300", days: int = 252) -> list[float]:
    """获取基准指数的日收益率序列（默认沪深300）"""
    try:
        from services.technical import fetch_kline
        market_map = {"000300": "1", "000905": "1", "399006": "0", "HSI": "100"}
        mkt = market_map.get(benchmark, "1")
        kline = fetch_kline(benchmark, mkt, days)
        if "error" in kline or not kline.get("closes"):
            return []
        return _returns_from_prices(kline["closes"])
    except Exception:
        return []


# ==================== 风控指标 ====================

def calc_sharpe(returns: list[float], risk_free: float = 0.025) -> float | None:
    """年化夏普比率: (年化收益 - 无风险利率) / 年化波动率"""
    if not returns or len(returns) < 2:
        return None

    avg_daily = sum(returns) / len(returns)
    if avg_daily == 0:
        return 0.0

    # 年化
    ann_return = avg_daily * 252
    ann_vol = calc_volatility(returns)
    if ann_vol is None or ann_vol == 0:
        return None

    return round((ann_return - risk_free) / ann_vol, 2)


def calc_max_drawdown(prices: list[float]) -> float | None:
    """最大回撤: 从峰顶到谷底的最大跌幅（返回负百分比，如 -0.185 = -18.5%）"""
    if not prices or len(prices) < 2:
        return None

    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        dd = (p - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return round(max_dd, 4) if max_dd < 0 else 0.0


def calc_volatility(returns: list[float]) -> float | None:
    """年化波动率"""
    if not returns or len(returns) < 2:
        return None

    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    daily_vol = math.sqrt(variance)

    # 年化
    return round(daily_vol * math.sqrt(252), 4)


def calc_beta(stock_returns: list[float], benchmark_returns: list[float]) -> float | None:
    """Beta 系数: 个股相对基准的波动敏感度"""
    if not stock_returns or not benchmark_returns:
        return None
    if len(stock_returns) != len(benchmark_returns):
        # 截断到较短的长度
        n = min(len(stock_returns), len(benchmark_returns))
        stock_returns = stock_returns[:n]
        benchmark_returns = benchmark_returns[:n]
    if len(stock_returns) < 2:
        return None

    n = len(stock_returns)
    stock_mean = sum(stock_returns) / n
    bench_mean = sum(benchmark_returns) / n

    # 协方差 / 基准方差
    cov = sum((stock_returns[i] - stock_mean) * (benchmark_returns[i] - bench_mean)
              for i in range(n)) / (n - 1)
    bench_var = sum((r - bench_mean) ** 2 for r in benchmark_returns) / (n - 1)

    if bench_var == 0:
        return None

    return round(cov / bench_var, 2)


# ==================== 相关性矩阵 ====================

def calc_correlation_matrix(price_data: dict[str, list[float]]) -> dict:
    """计算持仓间价格相关性矩阵

    Args:
        price_data: {stock_code: [closes], ...}

    Returns:
        {"stocks": [codes...], "matrix": [[1.0, 0.6, ...], ...]}
    """
    codes = list(price_data.keys())
    if len(codes) < 2:
        return {"stocks": codes, "matrix": [[1.0]] if codes else [], "error": None}

    # 所有股票 → 日收益率
    returns_map: dict[str, list[float]] = {}
    for code, prices in price_data.items():
        r = _returns_from_prices(prices)
        if r:
            returns_map[code] = r

    valid_codes = list(returns_map.keys())
    if len(valid_codes) < 2:
        return {"stocks": valid_codes, "matrix": [[1.0]] * len(valid_codes), "error": "需要 ≥2 只有效数据的持仓"}

    n = len(valid_codes)
    matrix = [[1.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            r_i = returns_map[valid_codes[i]]
            r_j = returns_map[valid_codes[j]]
            corr = _pearson_correlation(r_i, r_j)
            matrix[i][j] = corr
            matrix[j][i] = corr

    return {"stocks": valid_codes, "matrix": matrix, "error": None}


def _pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """皮尔逊相关系数"""
    length = min(len(x), len(y))
    if length < 2:
        return None
    x = x[:length]
    y = y[:length]

    mean_x = sum(x) / length
    mean_y = sum(y) / length

    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(length))
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

    if std_x == 0 or std_y == 0:
        return None

    return round(cov / (std_x * std_y), 2)


# ==================== DCA 回测 ====================

def backtest_dca(
    code: str,
    amount: float,
    freq: str = "monthly",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """DCA（定期定额）历史回测

    Args:
        code: 股票/ETF代码
        amount: 每期投入金额
        freq: "weekly" | "monthly"
        start_date: 起始日期 ISO (YYYY-MM-DD)
        end_date: 结束日期 ISO (默认今天)

    Returns:
        {
            "strategy": "dca",
            "total_invested": float,
            "total_shares": float,
            "final_value": float,
            "total_return": float,
            "annual_return": float,
            "lump_sum_final": float,     # 一次性买入对比
            "lump_sum_return": float,
            "buy_points": [{date, price, shares, invested}, ...],
        }
    """
    # 获取历史K线
    from services.technical import fetch_kline
    kline = fetch_kline(code, get_market(code), days=1825)  # 最多5年
    if "error" in kline or not kline.get("closes"):
        return {"error": f"无法获取 {code} 的历史数据", "code": code}

    dates = kline["dates"]
    closes = kline["closes"]

    # 确定起止范围
    if not start_date:
        start_date = dates[0]
    if not end_date:
        end_date = dates[-1]

    # 模拟定投
    total_invested = 0.0
    total_shares = 0.0
    buy_points: list[dict] = []

    invest_month = ""
    invest_week = ""
    last_invest_date = ""

    for i, date_str in enumerate(dates):
        if date_str < start_date or date_str > end_date:
            continue

        price = closes[i]
        if price <= 0:
            continue

        should_buy = False
        if freq == "monthly":
            month_key = date_str[:7]  # "2026-05"
            if month_key != invest_month:
                should_buy = True
                invest_month = month_key
        elif freq == "weekly":
            # ISO 周
            dt = datetime.fromisoformat(date_str)
            week_key = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
            if week_key != invest_week:
                should_buy = True
                invest_week = week_key

        if should_buy:
            shares = amount / price
            total_invested += amount
            total_shares += shares
            buy_points.append({
                "date": date_str,
                "price": price,
                "shares": round(shares, 4),
                "invested": amount,
            })
            last_invest_date = date_str

    if not buy_points:
        return {"error": "选定的时间段内无有效定投记录", "code": code}

    # 最终市值
    final_price = closes[-1]
    final_value = total_shares * final_price
    total_return = (final_value - total_invested) / total_invested if total_invested > 0 else 0

    # 年化收益
    dt_start = datetime.fromisoformat(start_date)
    dt_end = datetime.fromisoformat(end_date)
    period_days = (dt_end - dt_start).days or 1
    ann_return = _annualize_return(total_return, period_days)

    # 一次性买入对比
    start_idx = 0
    for idx, d in enumerate(dates):
        if d >= start_date:
            start_idx = idx
            break
    lump_sum_shares = total_invested / closes[start_idx]
    lump_sum_final = lump_sum_shares * final_price
    lump_sum_return = (lump_sum_final - total_invested) / total_invested if total_invested > 0 else 0

    return {
        "strategy": "dca",
        "code": code,
        "freq": freq,
        "start_date": start_date,
        "end_date": end_date,
        "total_invested": round(total_invested, 2),
        "total_shares": round(total_shares, 4),
        "final_price": final_price,
        "final_value": round(final_value, 2),
        "total_return": round(total_return, 4),
        "annual_return": round(ann_return, 4),
        "lump_sum_final": round(lump_sum_final, 2),
        "lump_sum_return": round(lump_sum_return, 4),
        "num_purchases": len(buy_points),
        "buy_points": buy_points[:50],  # 最多返回最近50条定投点
    }


# ==================== 策略对比 ====================

def compare_strategies(code: str, amount: float, start_date: str, end_date: str = "") -> dict:
    """对比 4 种策略的历史表现

    策略:
        dca: 定期定额 (每月买入固定金额)
        value_avg: 价值平均 (市值达标多退少补)
        fixed_shares: 固定股数 (每月买入固定股数)
        dip_buy: 下跌加仓 (跌超5%加码50%，涨超10%减半)
    """
    from services.technical import fetch_kline
    kline = fetch_kline(code, get_market(code), days=1825)
    if "error" in kline or not kline.get("closes"):
        return {"error": f"无法获取 {code} 的历史数据", "code": code}

    dates = kline["dates"]
    closes = kline["closes"]
    if not end_date:
        end_date = dates[-1]

    results = {}
    strategies = {
        "dca": lambda: _sim_dca(dates, closes, start_date, end_date, amount),
        "value_avg": lambda: _sim_value_avg(dates, closes, start_date, end_date, amount),
        "fixed_shares": lambda: _sim_fixed_shares(dates, closes, start_date, end_date, amount),
        "dip_buy": lambda: _sim_dip_buy(dates, closes, start_date, end_date, amount),
    }

    for name, sim_fn in strategies.items():
        try:
            results[name] = sim_fn()
        except Exception:
            results[name] = {"error": f"策略 {name} 计算失败"}

    return {"code": code, "start_date": start_date, "end_date": end_date, "monthly_amount": amount, "strategies": results}


def _sim_dca(dates, closes, start, end, amount):
    """定期定额"""
    total_invested = 0.0
    total_shares = 0.0
    month_seen = ""
    for i, d in enumerate(dates):
        if d < start or d > end:
            continue
        month = d[:7]
        if month != month_seen and closes[i] > 0:
            shares = amount / closes[i]
            total_invested += amount
            total_shares += shares
            month_seen = month

    final_val = total_shares * closes[-1]
    ret = (final_val - total_invested) / total_invested if total_invested > 0 else 0
    return {"total_invested": round(total_invested, 2), "final_value": round(final_val, 2),
            "return": round(ret, 4), "trades": sum(1 for d in dates if start <= d <= end and d[:7] != (dates[max(0, dates.index(d)-1)][:7] if dates.index(d) > 0 else ""))}


def _sim_value_avg(dates, closes, start, end, amount):
    """价值平均法: 每月目标市值增长 amount，少则补多则赎"""
    total_invested = 0.0
    total_shares = 0.0
    target_value = 0.0
    month_seen = ""
    for i, d in enumerate(dates):
        if d < start or d > end:
            continue
        month = d[:7]
        if month != month_seen and closes[i] > 0:
            target_value += amount
            current_value = total_shares * closes[i]
            gap = target_value - current_value
            if gap > 0:
                shares = gap / closes[i]
                total_invested += gap
                total_shares += shares
            elif gap < 0:
                # 超出目标，赎回超额部分
                redeem = abs(gap) / closes[i]
                total_shares -= redeem
                total_invested -= abs(gap)
            month_seen = month

    final_val = total_shares * closes[-1]
    ret = (final_val - total_invested) / total_invested if total_invested > 0 else 0
    return {"total_invested": round(total_invested, 2), "final_value": round(final_val, 2), "return": round(ret, 4)}


def _sim_fixed_shares(dates, closes, start, end, amount):
    """固定股数: 每月买入 (amount / 首月股价) 股"""
    total_invested = 0.0
    total_shares = 0.0
    shares_per_month = 0.0
    month_seen = ""
    first = True
    for i, d in enumerate(dates):
        if d < start or d > end:
            continue
        month = d[:7]
        if month != month_seen and closes[i] > 0:
            if first:
                shares_per_month = amount / closes[i]
                first = False
            invested = shares_per_month * closes[i]
            total_invested += invested
            total_shares += shares_per_month
            month_seen = month

    final_val = total_shares * closes[-1]
    ret = (final_val - total_invested) / total_invested if total_invested > 0 else 0
    return {"total_invested": round(total_invested, 2), "final_value": round(final_val, 2), "return": round(ret, 4)}


def _sim_dip_buy(dates, closes, start, end, amount):
    """下跌加仓: 跌超5%加码50%，涨超10%减半"""
    total_invested = 0.0
    total_shares = 0.0
    prev_price = 0.0
    month_seen = ""
    for i, d in enumerate(dates):
        if d < start or d > end:
            continue
        month = d[:7]
        if month != month_seen and closes[i] > 0:
            adj_amount = amount
            if prev_price > 0:
                change = (closes[i] - prev_price) / prev_price
                if change < -0.05:
                    adj_amount = amount * 1.5  # 跌超5%, 加码50%
                elif change > 0.10:
                    adj_amount = amount * 0.5  # 涨超10%, 减半
            shares = adj_amount / closes[i]
            total_invested += adj_amount
            total_shares += shares
            prev_price = closes[i]
            month_seen = month

    final_val = total_shares * closes[-1]
    ret = (final_val - total_invested) / total_invested if total_invested > 0 else 0
    return {"total_invested": round(total_invested, 2), "final_value": round(final_val, 2), "return": round(ret, 4)}


# ==================== 蒙特卡洛模拟 ====================

def monte_carlo_sim(prices: list[float], days: int = 252, sims: int = 1000, confidence: list[float] = None) -> dict:
    """蒙特卡洛仓位模拟

    基于历史波动率和收益率，模拟未来 N 天的价格路径。

    Args:
        prices: 历史价格序列
        days: 模拟未来天数 (默认252 = 1年)
        sims: 模拟路径数 (默认1000)
        confidence: 置信区间百分位 (默认 [5, 25, 50, 75, 95])

    Returns:
        {
            "current_price": float,
            "simulations": [[path1...], [path2...], ...],  # 全部路径数据
            "percentiles": {5: float, 25: float, 50: float, ...},
            "prob_loss": float,    # 亏损概率
            "prob_loss_15pct": float,  # 亏损超15%概率
            "mean_final": float,
            "min_final": float,
            "max_final": float,
        }
    """
    if not prices or len(prices) < 20:
        return {"error": "历史数据不足（至少需要 20 天）", "current_price": prices[-1] if prices else None}

    if confidence is None:
        confidence = [5, 25, 50, 75, 95]

    returns = _returns_from_prices(prices)
    if not returns:
        return {"error": "无法计算收益率序列", "current_price": prices[-1]}

    mu = sum(returns) / len(returns)  # 日均收益率
    sigma = math.sqrt(sum((r - mu) ** 2 for r in returns) / (len(returns) - 1))  # 日波动率

    if sigma == 0:
        sigma = 0.0001  # 避免零波动

    current_price = prices[-1]
    random.seed(42)  # 可重现

    all_paths = []
    finals = []
    for _ in range(sims):
        path = [current_price]
        price = current_price
        for _ in range(days):
            daily_return = random.gauss(mu, sigma)
            price = price * (1 + daily_return)
            if price <= 0:
                price = 0.01  # 截断到正数
            path.append(round(price, 2))
        all_paths.append(path)
        finals.append(path[-1])

    finals.sort()
    percentiles = {}
    for p in confidence:
        idx = int(len(finals) * p / 100)
        percentiles[p] = round(finals[min(idx, len(finals) - 1)], 2)

    prob_loss = sum(1 for f in finals if f < current_price) / sims
    prob_loss_15 = sum(1 for f in finals if f < current_price * 0.85) / sims

    return {
        "current_price": current_price,
        "days": days,
        "simulations": sims,
        "daily_mu": round(mu, 6),
        "daily_sigma": round(sigma, 6),
        "ann_return": round(mu * 252, 4),
        "ann_volatility": round(sigma * math.sqrt(252), 4),
        "simulations_data": all_paths[:100],  # 前100条路径给前端画图
        "percentiles": percentiles,
        "mean_final": round(sum(finals) / len(finals), 2),
        "min_final": round(finals[0], 2),
        "max_final": round(finals[-1], 2),
        "prob_loss": round(prob_loss, 3),
        "prob_loss_15pct": round(prob_loss_15, 3),
    }


# ==================== 组合级别聚合 ====================

def get_benchmark_comparison(user_id: int = 1) -> dict:
    """对比投资组合 vs 多个基准指数的表现

    Returns:
        { "benchmarks": { "000300": {...}, "000905": {...}, ... },
          "portfolio": { "total_return": ..., "annual_return": ... } }
    """
    from database import query_all
    from services.technical import fetch_kline

    holdings = query_all("SELECT * FROM holdings WHERE user_id = ?", (user_id,))
    if not holdings:
        return {"error": "无持仓数据"}

    benchmarks = {
        "000300": "沪深300",
        "000905": "中证500",
        "399006": "创业板指",
    }

    # 计算组合市值序列
    prices_map: dict[str, list[float]] = {}
    for h in holdings:
        code = h["stock_code"]
        kline = fetch_kline(code, get_market(code), days=252)
        if "error" not in kline and kline.get("closes"):
            prices_map[code] = kline["closes"]

    port_prices = _portfolio_prices(holdings, prices_map)
    if not port_prices or len(port_prices) < 2:
        return {"error": "无法计算组合市值序列"}

    port_start = port_prices[0]
    port_end = port_prices[-1]
    port_total_ret = (port_end - port_start) / port_start
    port_ann = _annualize_return(port_total_ret, len(port_prices))

    bench_results = {}
    for bcode, bname in benchmarks.items():
        market_map = {"000300": "1", "000905": "1", "399006": "0"}
        bk = fetch_kline(bcode, market_map[bcode], days=252)
        if "error" in bk or not bk.get("closes"):
            bench_results[bcode] = {"name": bname, "error": "数据获取失败"}
            continue
        bcloses = bk["closes"]
        b_start = bcloses[0]
        b_end = bcloses[-1]
        bench_results[bcode] = {
            "name": bname,
            "start_price": b_start,
            "end_price": b_end,
            "total_return": round((b_end - b_start) / b_start, 4),
            "annual_return": round(_annualize_return((b_end - b_start) / b_start, len(bcloses)), 4),
        }

    return {
        "portfolio": {
            "total_return": round(port_total_ret, 4),
            "annual_return": round(port_ann, 4),
            "start_value": round(port_start, 2),
            "end_value": round(port_end, 2),
        },
        "benchmarks": bench_results,
    }


def get_portfolio_risk(user_id: int = 1) -> dict:
    """获取整个投资组合的风控指标摘要

    Returns:
        {
            "sharpe": float | None,
            "max_drawdown": float | None,
            "volatility": float | None,
            "beta": float | None,
            "beta_benchmark": str,
            "holdings_risk": [{code, name, sharpe, max_dd, vol, beta}, ...],
            "correlation": {stocks: [], matrix: []},
        }
    """
    from database import query_all
    from services.technical import fetch_kline

    holdings = query_all("SELECT * FROM holdings WHERE user_id = ? ORDER BY id DESC", (user_id,))
    if not holdings:
        return {"error": "无持仓数据", "holdings_count": 0}

    # 获取每只持仓的价格历史
    prices_map: dict[str, list[float]] = {}
    returns_map: dict[str, list[float]] = {}
    holdings_risk: list[dict] = []

    for h in holdings:
        code = h["stock_code"]
        kline = fetch_kline(code, get_market(code), days=252)
        if "error" in kline:
            holdings_risk.append({
                "code": code,
                "name": h.get("stock_name", ""),
                "error": kline["error"],
            })
            continue

        closes = kline["closes"]
        returns = _returns_from_prices(closes)
        prices_map[code] = closes
        returns_map[code] = returns

        holdings_risk.append({
            "code": code,
            "name": h.get("stock_name", ""),
            "sharpe": calc_sharpe(returns),
            "max_dd": calc_max_drawdown(closes),
            "vol": calc_volatility(returns),
            "price": closes[-1] if closes else None,
            "cost": h.get("cost_price"),
            "quantity": h.get("quantity"),
        })

    # 组合级别指标
    bench_returns = _fetch_benchmark_returns("000300", 252)
    if bench_returns and returns_map:
        # 组合日收益 = 各持仓收益的市值加权平均
        port_returns = _portfolio_returns(holdings, prices_map, returns_map)
        port_sharpe = calc_sharpe(port_returns)
        port_vol = calc_volatility(port_returns)
        port_beta = calc_beta(port_returns, bench_returns) if port_returns and bench_returns else None

        # 组合最大回撤
        port_prices = _portfolio_prices(holdings, prices_map)
        port_max_dd = calc_max_drawdown(port_prices)
    else:
        port_sharpe = None
        port_vol = None
        port_beta = None
        port_max_dd = None

    # 相关性矩阵
    correlation = calc_correlation_matrix(prices_map)

    return {
        "holdings_count": len(holdings),
        "sharpe": port_sharpe,
        "max_drawdown": port_max_dd,
        "volatility": port_vol,
        "beta": port_beta,
        "beta_benchmark": "沪深300",
        "holdings_risk": holdings_risk,
        "correlation": correlation,
    }


def _portfolio_returns(holdings, prices_map, returns_map) -> list[float]:
    """计算组合加权日收益率序列"""
    weights: dict[str, float] = {}
    total_value = 0.0
    for h in holdings:
        code = h["stock_code"]
        if code in prices_map and prices_map[code]:
            val = prices_map[code][-1] * (h.get("quantity") or 0)
            weights[code] = val
            total_value += val

    if total_value == 0 or not returns_map:
        return []

    # 找到最短的收益率序列长度
    min_len = min(len(r) for r in returns_map.values())
    result = []
    for i in range(min_len):
        daily = 0.0
        for code, r in returns_map.items():
            if code in weights and i < len(r):
                daily += r[i] * (weights.get(code, 0) / total_value)
        result.append(daily)
    return result


def _portfolio_prices(holdings, prices_map) -> list[float]:
    """计算组合总市值序列"""
    if not prices_map:
        return []

    min_len = min(len(p) for p in prices_map.values())
    result = []
    for i in range(min_len):
        val = 0.0
        for h in holdings:
            code = h["stock_code"]
            if code in prices_map and i < len(prices_map[code]):
                val += prices_map[code][i] * (h.get("quantity") or 0)
        result.append(val)
    return result
