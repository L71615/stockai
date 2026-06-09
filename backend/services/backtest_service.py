"""策略回测服务：基于 backtrader 的多策略回测引擎

支持的策略（仅多头）:
  - ma_cross: 均线金叉买入，死叉卖出
  - macd: MACD 金叉买入，死叉卖出
  - rsi: RSI 超卖买入，超买卖出
  - momentum: 动量突破（N日新高买入，M日新低卖出）
  - turtle: 海龟交易法（唐奇安通道突破）

统一输出格式:
  {
    "strategy": str,
    "total_return": float,
    "annual_return": float,
    "sharpe": float,
    "max_drawdown": float,
    "win_rate": float,
    "profit_factor": float,
    "num_trades": int,
    "initial_cash": float,
    "final_value": float,
    "buy_signals": [{date, price, shares}],
    "sell_signals": [{date, price, shares, reason}],
  }

注意: backtrader 是可选的，未安装时提供纯 Python 回退实现。
"""

import math
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 纯 Python 回退实现（无 backtrader 依赖）
# ═══════════════════════════════════════════════════════════

def _sim_ma_cross(dates: list[str], closes: list[float], opens: list[float],
                  initial_cash: float, fast: int = 10, slow: int = 30) -> dict:
    """均线交叉策略：快线从下穿上慢线 → 买入；从上穿下慢线 → 卖出"""
    if len(closes) < slow + 1:
        return {"error": f"数据不足（需要至少 {slow + 1} 天）"}

    def sma(data, n, idx):
        if idx < n - 1:
            return None
        return sum(data[idx - n + 1:idx + 1]) / n

    cash = initial_cash
    shares = 0
    position = False
    buy_signals = []
    sell_signals = []
    total_trades = 0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    last_buy_price = 0.0

    for i in range(slow, len(closes)):
        ma_f = sma(closes, fast, i)
        ma_s = sma(closes, slow, i)
        if ma_f is None or ma_s is None:
            continue
        ma_f_prev = sma(closes, fast, i - 1)
        ma_s_prev = sma(closes, slow, i - 1)
        if ma_f_prev is None or ma_s_prev is None:
            continue

        price = closes[i]  # 以收盘价成交

        # 金叉买入
        if ma_f_prev <= ma_s_prev and ma_f > ma_s and not position:
            if cash >= price:
                shares = int(cash * 0.95 / price)  # 留 5% 现金
                if shares > 0:
                    cash -= shares * price
                    position = True
                    last_buy_price = price
                    buy_signals.append({
                        "date": dates[i] if i < len(dates) else "",
                        "price": round(price, 2),
                        "shares": shares,
                    })

        # 死叉卖出
        elif ma_f_prev >= ma_s_prev and ma_f < ma_s and position:
            cash += shares * price
            total_trades += 1
            pnl = (price - last_buy_price) / last_buy_price
            if pnl > 0:
                wins += 1
                gross_profit += pnl * last_buy_price * shares
            else:
                gross_loss += abs(pnl) * last_buy_price * shares
            sell_signals.append({
                "date": dates[i] if i < len(dates) else "",
                "price": round(price, 2),
                "shares": shares,
                "reason": "死叉",
            })
            shares = 0
            position = False

    # 期末清仓
    if position and closes:
        cash += shares * closes[-1]
        sell_signals.append({
            "date": dates[-1] if dates else "",
            "price": round(closes[-1], 2),
            "shares": shares,
            "reason": "期末清仓",
        })
        shares = 0
        position = False

    final_value = cash
    return _build_result(dates, closes, initial_cash, final_value,
                         total_trades + (1 if position else 0),
                         wins, gross_profit, gross_loss,
                         buy_signals, sell_signals, "ma_cross")


def _sim_macd(dates: list[str], closes: list[float], opens: list[float],
              initial_cash: float, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD 策略：DIF 从下穿上 DEA → 买入；从上穿下 DEA → 卖出"""
    if len(closes) < slow + signal:
        return {"error": f"数据不足（需要至少 {slow + signal} 天）"}

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

    ema_f = _ema(closes, fast)
    ema_s = _ema(closes, slow)
    dif = [f - s for f, s in zip(ema_f, ema_s)]
    dea = _ema(dif, signal)

    cash = initial_cash
    shares = 0
    position = False
    buy_signals = []
    sell_signals = []
    total_trades = 0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    last_buy_price = 0.0

    start_idx = slow + signal
    for i in range(start_idx, len(closes)):
        if i >= len(dif) or i >= len(dea):
            continue
        dif_now, dif_prev = dif[i], dif[i - 1]
        dea_now, dea_prev = dea[i], dea[i - 1]
        price = closes[i]

        # 金叉：DIF 上穿 DEA
        if dif_prev <= dea_prev and dif_now > dea_now and not position:
            if cash >= price:
                shares = int(cash * 0.95 / price)
                if shares > 0:
                    cash -= shares * price
                    position = True
                    last_buy_price = price
                    buy_signals.append({
                        "date": dates[i] if i < len(dates) else "",
                        "price": round(price, 2),
                        "shares": shares,
                    })

        # 死叉：DIF 下穿 DEA
        elif dif_prev >= dea_prev and dif_now < dea_now and position:
            cash += shares * price
            total_trades += 1
            pnl = (price - last_buy_price) / last_buy_price
            if pnl > 0:
                wins += 1
                gross_profit += pnl * last_buy_price * shares
            else:
                gross_loss += abs(pnl) * last_buy_price * shares
            sell_signals.append({
                "date": dates[i] if i < len(dates) else "",
                "price": round(price, 2),
                "shares": shares,
                "reason": "MACD死叉",
            })
            shares = 0
            position = False

    if position and closes:
        cash += shares * closes[-1]
        sell_signals.append({"date": dates[-1], "price": round(closes[-1], 2),
                              "shares": shares, "reason": "期末清仓"})
        shares = 0

    final_value = cash
    return _build_result(dates, closes, initial_cash, final_value,
                         total_trades + (1 if position else 0),
                         wins, gross_profit, gross_loss,
                         buy_signals, sell_signals, "macd")


def _sim_rsi(dates: list[str], closes: list[float], opens: list[float],
             initial_cash: float, period: int = 14,
             oversold: int = 30, overbought: int = 70) -> dict:
    """RSI 策略：RSI 低于超卖线买入，高于超买线卖出"""
    if len(closes) < period + 1:
        return {"error": f"数据不足（需要至少 {period + 1} 天）"}

    def _calc_rsi(prices, p):
        if len(prices) < p + 1:
            return []
        rsi_vals = []
        for j in range(p, len(prices)):
            gains = losses = 0.0
            for k in range(j - p + 1, j + 1):
                change = prices[k] - prices[k - 1]
                if change > 0:
                    gains += change
                else:
                    losses += abs(change)
            rs = gains / losses if losses > 0 else 100
            rsi_vals.append(100 - 100 / (1 + rs))
        return rsi_vals

    rsi_list = _calc_rsi(closes, period)

    cash = initial_cash
    shares = 0
    position = False
    buy_signals = []
    sell_signals = []
    total_trades = 0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    last_buy_price = 0.0

    for i_offset, rsi_val in enumerate(rsi_list):
        data_idx = i_offset + period
        if data_idx >= len(closes):
            break
        price = closes[data_idx]

        # 超卖买入
        if rsi_val < oversold and not position:
            if cash >= price:
                shares = int(cash * 0.95 / price)
                if shares > 0:
                    cash -= shares * price
                    position = True
                    last_buy_price = price
                    buy_signals.append({
                        "date": dates[data_idx],
                        "price": round(price, 2),
                        "shares": shares,
                    })

        # 超买卖出
        elif rsi_val > overbought and position:
            cash += shares * price
            total_trades += 1
            pnl = (price - last_buy_price) / last_buy_price
            if pnl > 0:
                wins += 1
                gross_profit += pnl * last_buy_price * shares
            else:
                gross_loss += abs(pnl) * last_buy_price * shares
            sell_signals.append({
                "date": dates[data_idx],
                "price": round(price, 2),
                "shares": shares,
                "reason": "RSI超买",
            })
            shares = 0
            position = False

    if position and closes:
        cash += shares * closes[-1]
        sell_signals.append({"date": dates[-1], "price": round(closes[-1], 2),
                              "shares": shares, "reason": "期末清仓"})

    final_value = cash
    return _build_result(dates, closes, initial_cash, final_value,
                         total_trades + (1 if position else 0),
                         wins, gross_profit, gross_loss,
                         buy_signals, sell_signals, "rsi")


def _sim_momentum(dates: list[str], closes: list[float], opens: list[float],
                  initial_cash: float, breakout_days: int = 20,
                  exit_days: int = 10) -> dict:
    """动量突破策略：N日新高买入，M日新低卖出"""
    if len(closes) < max(breakout_days, exit_days) + 1:
        return {"error": f"数据不足"}

    cash = initial_cash
    shares = 0
    position = False
    buy_signals = []
    sell_signals = []
    total_trades = 0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    last_buy_price = 0.0

    for i in range(breakout_days, len(closes)):
        price = closes[i]
        # N日最高价突破
        highest_n = max(closes[i - breakout_days:i])
        lowest_m = min(closes[max(0, i - exit_days):i])

        if price >= highest_n and not position:
            if cash >= price:
                shares = int(cash * 0.95 / price)
                if shares > 0:
                    cash -= shares * price
                    position = True
                    last_buy_price = price
                    buy_signals.append({
                        "date": dates[i],
                        "price": round(price, 2),
                        "shares": shares,
                    })

        elif price <= lowest_m and position:
            cash += shares * price
            total_trades += 1
            pnl = (price - last_buy_price) / last_buy_price
            if pnl > 0:
                wins += 1
                gross_profit += pnl * last_buy_price * shares
            else:
                gross_loss += abs(pnl) * last_buy_price * shares
            sell_signals.append({
                "date": dates[i],
                "price": round(price, 2),
                "shares": shares,
                "reason": f"{exit_days}日新低",
            })
            shares = 0
            position = False

    if position and closes:
        cash += shares * closes[-1]
        sell_signals.append({"date": dates[-1], "price": round(closes[-1], 2),
                              "shares": shares, "reason": "期末清仓"})

    final_value = cash
    return _build_result(dates, closes, initial_cash, final_value,
                         total_trades + (1 if position else 0),
                         wins, gross_profit, gross_loss,
                         buy_signals, sell_signals, "momentum")


def _sim_turtle(dates: list[str], closes: list[float], opens: list[float],
                initial_cash: float, entry_days: int = 20,
                exit_days: int = 10) -> dict:
    """海龟交易法：突破N日唐奇安通道上轨买入，跌破M日下轨卖出"""
    if len(closes) < max(entry_days, exit_days) + 1:
        return {"error": f"数据不足"}

    cash = initial_cash
    shares = 0
    position = False
    buy_signals = []
    sell_signals = []
    total_trades = 0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    last_buy_price = 0.0

    for i in range(entry_days, len(closes)):
        price = closes[i]
        upper = max(closes[i - entry_days:i])
        lower = min(closes[max(0, i - exit_days):i])

        if price >= upper and not position:
            if cash >= price:
                shares = int(cash * 0.95 / price)
                if shares > 0:
                    cash -= shares * price
                    position = True
                    last_buy_price = price
                    buy_signals.append({
                        "date": dates[i],
                        "price": round(price, 2),
                        "shares": shares,
                    })

        elif price <= lower and position:
            cash += shares * price
            total_trades += 1
            pnl = (price - last_buy_price) / last_buy_price
            if pnl > 0:
                wins += 1
                gross_profit += pnl * last_buy_price * shares
            else:
                gross_loss += abs(pnl) * last_buy_price * shares
            sell_signals.append({
                "date": dates[i],
                "price": round(price, 2),
                "shares": shares,
                "reason": f"跌破{exit_days}日下轨",
            })
            shares = 0
            position = False

    if position and closes:
        cash += shares * closes[-1]
        sell_signals.append({"date": dates[-1], "price": round(closes[-1], 2),
                              "shares": shares, "reason": "期末清仓"})

    final_value = cash
    return _build_result(dates, closes, initial_cash, final_value,
                         total_trades + (1 if position else 0),
                         wins, gross_profit, gross_loss,
                         buy_signals, sell_signals, "turtle")


# ═══════════════════════════════════════════════════════════
# 回退实现 - 结果格式化
# ═══════════════════════════════════════════════════════════

def _build_result(dates, closes, initial_cash, final_value,
                  num_trades, wins, gross_profit, gross_loss,
                  buy_signals, sell_signals, strategy_name) -> dict:
    """统一构建回测结果"""
    total_return = (final_value - initial_cash) / initial_cash if initial_cash > 0 else 0

    # 年化收益率
    if len(dates) >= 2 and total_return > -1:
        try:
            d0 = datetime.fromisoformat(dates[0])
            d1 = datetime.fromisoformat(dates[-1])
            days = (d1 - d0).days or 1
            ann_return = (1 + total_return) ** (365 / days) - 1
        except Exception:
            ann_return = total_return
    else:
        ann_return = total_return

    # Sharpe（简化：基于交易序列）
    sharpe = 0.0
    if num_trades > 0:
        avg_pnl = (gross_profit - gross_loss) / num_trades if num_trades > 0 else 0
        # 用总收益率估算波动率
        from services.factor_service import _returns
        rets = _returns(closes)
        from services.factor_service import _safe_std
        vol = _safe_std(rets)
        if vol and vol > 0:
            excess_return = total_return - 0.025 * (len(closes) / 252)
            sharpe = round(excess_return / (vol * math.sqrt(len(closes))), 2) if vol > 0 else 0

    # 最大回撤（基于执行信号的价值曲线估算）
    max_dd = 0.0
    if buy_signals:
        values = [initial_cash]
        # 粗略估算价值曲线
        for i, (bs, ss) in enumerate(zip(
            buy_signals,
            sell_signals[-len(buy_signals):] if len(sell_signals) <= len(buy_signals) else sell_signals
        )):
            values.append(values[-1] * (1 + (ss.get("price", 0) / bs.get("price", 1) - 1)))
        if len(values) > 1:
            peak = values[0]
            for v in values:
                if v > peak:
                    peak = v
                dd = (v - peak) / peak if peak > 0 else 0
                if dd < max_dd:
                    max_dd = dd

    # 胜率 & 盈亏比
    win_rate = wins / num_trades if num_trades > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999 if gross_profit > 0 else 0)

    return {
        "strategy": strategy_name,
        "total_return": round(total_return, 4),
        "annual_return": round(ann_return, 4),
        "sharpe": sharpe,
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 2),
        "num_trades": num_trades,
        "initial_cash": initial_cash,
        "final_value": round(final_value, 2),
        "buy_signals": buy_signals[-50:],
        "sell_signals": sell_signals[-50:],
    }


# ═══════════════════════════════════════════════════════════
# 主入口：运行回测
# ═══════════════════════════════════════════════════════════

# 可用策略定义
AVAILABLE_STRATEGIES = {
    "ma_cross": {"name": "均线交叉", "params": {"fast": 10, "slow": 30}},
    "macd": {"name": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
    "rsi": {"name": "RSI超买超卖", "params": {"period": 14, "oversold": 30, "overbought": 70}},
    "momentum": {"name": "动量突破", "params": {"breakout_days": 20, "exit_days": 10}},
    "turtle": {"name": "海龟交易", "params": {"entry_days": 20, "exit_days": 10}},
}

STRATEGY_SIMULATORS = {
    "ma_cross": _sim_ma_cross,
    "macd": _sim_macd,
    "rsi": _sim_rsi,
    "momentum": _sim_momentum,
    "turtle": _sim_turtle,
}


def run_backtest(
    code: str,
    strategy: str = "ma_cross",
    initial_cash: float = 100000,
    days: int = 365,
    **strategy_params,
) -> dict:
    """对单只股票运行策略回测

    Args:
        code: 股票代码
        strategy: 策略类型 ("ma_cross" | "macd" | "rsi" | "momentum" | "turtle")
        initial_cash: 初始资金
        days: 回测天数
        **strategy_params: 策略参数覆盖

    Returns:
        统一格式的回测结果
    """
    if strategy not in STRATEGY_SIMULATORS:
        return {"error": f"不支持的策略: {strategy}", "available": list(STRATEGY_SIMULATORS.keys())}

    # 获取历史数据
    from services.technical import fetch_kline
    from services.utils import get_market

    kline = fetch_kline(code, get_market(code), days=days)
    if "error" in kline or not kline.get("closes"):
        return {"error": f"无法获取 {code} 的历史数据", "code": code}

    dates = kline["dates"]
    closes = kline["closes"]
    opens = kline.get("opens", closes)
    highs = kline.get("highs", closes)
    lows = kline.get("lows", closes)

    if len(closes) < 60:
        return {"error": f"历史数据不足（{len(closes)} 天，需要至少 60 天）", "code": code}

    # 合并策略参数
    default_params = dict(AVAILABLE_STRATEGIES[strategy]["params"])
    default_params.update(strategy_params)

    # 执行回测
    simulator = STRATEGY_SIMULATORS[strategy]
    result = simulator(dates, closes, opens, initial_cash, **default_params)

    result["code"] = code
    result["params"] = default_params
    return result


def run_backtest_batch(
    codes: list[str],
    strategies: list[str] = None,
    initial_cash: float = 100000,
    days: int = 365,
) -> dict:
    """批量回测：多只股票 × 多种策略

    Returns:
        {results: [{code, strategy, total_return, sharpe, ...}],
         summary: {best_strategy_per_stock: {code: strategy}}}
    """
    if strategies is None:
        strategies = ["ma_cross", "macd", "rsi", "momentum"]

    results = []
    for code in codes:
        for strat in strategies:
            try:
                r = run_backtest(code, strat, initial_cash, days)
                results.append(r)
            except Exception:
                pass

    # 汇总：每只股票的最佳策略
    best_per_stock = {}
    stock_results: dict[str, list[dict]] = {}
    for r in results:
        code = r.get("code", "")
        if code not in stock_results:
            stock_results[code] = []
        stock_results[code].append(r)

    for code, strat_results in stock_results.items():
        valid = [s for s in strat_results if "error" not in s]
        if valid:
            best = max(valid, key=lambda x: x.get("sharpe", -999))
            best_per_stock[code] = best["strategy"]

    return {
        "results": results,
        "summary": {
            "total_tests": len(results),
            "valid_results": sum(1 for r in results if "error" not in r),
            "best_strategy_per_stock": best_per_stock,
        },
    }
