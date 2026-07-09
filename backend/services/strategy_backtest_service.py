"""策略回测引擎 — 用 YAML 策略在历史数据上模拟选股 + 交易 + 绩效评估

核心工作流:
  对每个调仓日（从 start_date 到 end_date）:
    1. 从 historical_kline 为每只候选股构建"当日截面"K 线数据（只看 as_of_date 之前）
    2. 用 backtest_field_builder 计算技术字段
    3. 用 condition_engine.evaluate() 跑策略筛选
    4. 模拟买入（次日开盘价）/ 卖出（持仓满 hold_days）
    5. 记录每日净值曲线

依赖: historical_kline 表必须有足够的历史数据
"""

import logging
from datetime import datetime, timedelta

from database import query_all

logger = logging.getLogger(__name__)

# 默认股票池（沪深300中的代表性标的，覆盖多个行业）
_DEFAULT_POOL = [
    "000001", "000002", "000651", "000858", "002415",
    "600000", "600009", "600016", "600028", "600030",
    "600036", "600048", "600104", "600276", "600309",
    "600519", "600585", "600809", "600887", "601012",
    "601088", "601166", "601288", "601318", "601398",
    "601668", "601857", "601888", "601939", "603259",
]


# A股交易成本
_COMMISSION_RATE = 0.0003    # 佣金 万分之三
_COMMISSION_MIN = 5.0         # 最低佣金 5元
_STAMP_TAX_RATE = 0.001       # 印花税 千分之一（仅卖出）
_TRANSFER_FEE_RATE = 0.00001  # 过户费 十万分之一


def run_strategy_backtest(
    strategy_ids: list[str] | None = None,
    stock_codes: list[str] | None = None,
    start_date: str = "2024-01-01",
    end_date: str = "2025-01-01",
    initial_cash: float = 100000,
    hold_days: int = 5,
    rebalance_freq: str = "daily",
    max_positions: int = 10,
    position_size_pct: float = 0.1,
    benchmark: str = "000300",
    param_overrides: dict[str, dict[str, any]] | None = None,
    include_fees: bool = True,
) -> dict:
    """策略回测主函数

    Args:
        strategy_ids: YAML 策略 id 列表，默认 ["turtle_s1"]
        stock_codes: 股票池，为空则用默认池
        start_date: 回测起始日
        end_date: 回测结束日
        initial_cash: 初始资金
        hold_days: 持仓天数（买入后 N 天卖出）
        rebalance_freq: 调仓频率 (daily / weekly / monthly)
        max_positions: 最大同时持仓数
        position_size_pct: 单票仓位（初始资金的百分比）
        benchmark: 基准指数代码（默认 000300 沪深300）

    Returns:
        {
            "config": {...},
            "metrics": {...},
            "equity_curve": [{date, value, benchmark_value}],
            "trades": [{date, code, name, direction, price, shares, pnl, reason}],
            "monthly_returns": [{month, strategy_return, benchmark_return}],
            "final_positions": [{code, name, entry_date, entry_price, current_price, days_held, unrealized_pnl}],
        }
    """
    # ── 参数整理 ──
    if strategy_ids is None:
        strategy_ids = ["turtle_s1"]
    if stock_codes is None or len(stock_codes) == 0:
        stock_codes = list(_DEFAULT_POOL)

    # 加载策略条件树（支持参数覆盖）
    condition_tree = _load_strategy_conditions(strategy_ids, param_overrides)
    if condition_tree is None:
        return {"error": f"无法加载策略: {strategy_ids}",
                "available": _list_available_strategies()}

    # 获取回测日列表
    all_trading_dates = _get_trading_dates(start_date, end_date)
    if len(all_trading_dates) < 2:
        # 查询实际可用日期范围
        dr = query_all(
            "SELECT MIN(trade_date) as mn, MAX(trade_date) as mx FROM historical_kline"
        )
        range_msg = f"{dr[0]['mn']} ~ {dr[0]['mx']}" if dr and dr[0]['mn'] else "无数据"
        return {"error": f"回测日期范围内无交易数据 ({start_date} ~ {end_date})，数据库可用范围: {range_msg}"}

    rebalance_dates = _filter_rebalance_dates(all_trading_dates, rebalance_freq)

    # 获取基准曲线
    benchmark_curve = _get_benchmark_curve(benchmark, start_date, end_date)

    # ── 回测主循环 ──
    cash = initial_cash
    positions = []  # [{code, name, entry_date, entry_price, shares, next_day_open}]
    trades = []     # [{date, code, name, direction, price, shares, pnl, reason}]
    equity_curve = []

    trade_id_counter = 0

    for i, rebal_date in enumerate(rebalance_dates):
        # 找到 rebal_date 在 all_trading_dates 中的位置
        date_idx = _index_of(all_trading_dates, rebal_date)
        if date_idx < 0:
            continue

        # ── 更新持仓市值（每日净值记录在卖出/买入操作后）──
        # 这里简化：在每个调仓日统一处理

        # ── Step A: 卖出到期的持仓 ──
        # 找出下一个交易日的开盘价（用于卖出价）
        next_date = all_trading_dates[date_idx + 1] if date_idx + 1 < len(all_trading_dates) else None
        if next_date is None:
            break

        positions_to_close = [
            p for p in positions
            if _trading_days_between(all_trading_dates, p["entry_date"], rebal_date) >= hold_days
        ]

        for p in positions_to_close:
            sell_price = _get_price_on_date(p["code"], next_date, "open")
            if sell_price is None:
                sell_price = _get_price_on_date(p["code"], rebal_date, "close")
            if sell_price is None:
                continue  # 停牌等，跳过

            proceeds = sell_price * p["shares"]
            cost = p["entry_price"] * p["shares"]
            # 卖出手续费（佣金+印花税）
            sell_fee = _calc_fee(proceeds, is_buy=False) if include_fees else 0
            pnl = round(proceeds - cost - sell_fee, 2)
            pnl_pct = round((sell_price - p["entry_price"]) / p["entry_price"] * 100, 2)

            cash += (proceeds - sell_fee)
            trade_id_counter += 1
            trades.append({
                "id": trade_id_counter,
                "date": next_date,
                "code": p["code"],
                "name": p["name"],
                "direction": "sell",
                "price": round(sell_price, 2),
                "shares": p["shares"],
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": f"持仓满{hold_days}天",
            })

        positions = [p for p in positions if p not in positions_to_close]

        # ── Step B: 选股 ──
        slots = max_positions - len(positions)
        if slots <= 0:
            continue

        candidates = _screen_stocks(
            stock_codes, rebal_date, condition_tree, all_trading_dates,
            top_n=slots,
        )

        # ── Step C: 买入 ──
        per_position_cash = initial_cash * position_size_pct
        for c in candidates:
            if cash < per_position_cash:
                break

            buy_price = _get_price_on_date(c["code"], next_date, "open")
            if buy_price is None:
                continue
            if buy_price <= 0:
                continue

            shares = int(per_position_cash / buy_price)
            if shares < 100:
                # A 股最小交易单位 100 股（ETF 除外）
                is_etf = c["code"].startswith(("51", "159", "588", "56"))
                if not is_etf and shares < 100:
                    continue
                if shares == 0:
                    continue

            cost = buy_price * shares
            # 买入手续费（佣金）
            if include_fees:
                buy_fee = _calc_fee(cost, is_buy=True)
                cost += buy_fee

            if cost > cash:
                shares = int(cash / buy_price)
                if shares == 0:
                    continue
                cost = buy_price * shares

            cash -= cost
            positions.append({
                "code": c["code"],
                "name": c.get("name", ""),
                "entry_date": next_date,
                "entry_price": buy_price,
                "shares": shares,
            })

            trade_id_counter += 1
            trades.append({
                "id": trade_id_counter,
                "date": next_date,
                "code": c["code"],
                "name": c.get("name", ""),
                "direction": "buy",
                "price": round(buy_price, 2),
                "shares": shares,
                "pnl": None,
                "pnl_pct": None,
                "reason": _build_trade_reason(c["code"], strategy_ids),
            })

        # ── Step D: 记录当日净值 ──
        positions_value = 0
        for p in positions:
            cur_price = _get_price_on_date(p["code"], rebal_date, "close")
            if cur_price is None:
                cur_price = p["entry_price"]  # fallback
            positions_value += cur_price * p["shares"]

        total_value = cash + positions_value
        bm_val = _interpolate_benchmark(benchmark_curve, rebal_date)

        equity_curve.append({
            "date": rebal_date,
            "value": round(total_value, 2),
            "cash": round(cash, 2),
            "positions_value": round(positions_value, 2),
            "benchmark_value": round(bm_val, 2) if bm_val is not None else None,
            "positions_count": len(positions),
        })

    # ── 期末清仓 ──
    final_date = all_trading_dates[-1]
    for p in positions:
        close_price = _get_price_on_date(p["code"], final_date, "close")
        if close_price is None:
            close_price = p["entry_price"]
        proceeds = close_price * p["shares"]
        cost = p["entry_price"] * p["shares"]
        pnl = round(proceeds - cost, 2)
        cash += proceeds
        trade_id_counter += 1
        trades.append({
            "id": trade_id_counter,
            "date": final_date,
            "code": p["code"],
            "name": p["name"],
            "direction": "sell",
            "price": round(close_price, 2),
            "shares": p["shares"],
            "pnl": pnl,
            "pnl_pct": round((close_price - p["entry_price"]) / p["entry_price"] * 100, 2) if p["entry_price"] > 0 else None,
            "reason": "期末清仓",
        })

    final_positions = []  # All closed by end
    positions = []

    # 最后一天的净值
    total_value = cash
    bm_val = _interpolate_benchmark(benchmark_curve, final_date)
    equity_curve.append({
        "date": final_date,
        "value": round(total_value, 2),
        "cash": round(cash, 2),
        "positions_value": 0,
        "benchmark_value": round(bm_val, 2) if bm_val is not None else None,
        "positions_count": 0,
    })

    # ── 绩效指标计算 ──
    metrics = _calculate_metrics(equity_curve, initial_cash, trades, start_date, end_date)

    # ── 月度收益 ──
    monthly_returns = _calculate_monthly_returns(equity_curve, benchmark_curve)

    return {
        "config": {
            "strategy_ids": strategy_ids,
            "stock_codes": stock_codes,
            "stock_count": len(stock_codes),
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_cash,
            "hold_days": hold_days,
            "rebalance_freq": rebalance_freq,
            "max_positions": max_positions,
            "position_size_pct": position_size_pct,
            "benchmark": benchmark,
            "param_overrides": param_overrides,
        },
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "monthly_returns": monthly_returns,
        "final_positions": final_positions,
        "final_value": round(total_value, 2),
    }


# ═══════════════════════════════════════════════════════════════
#  策略加载
# ═══════════════════════════════════════════════════════════════

def _load_strategy_conditions(strategy_ids: list[str], param_overrides: dict | None = None) -> dict | None:
    """加载 YAML 策略并合并条件树（OR 逻辑：任一策略满足即买入）

    Args:
        strategy_ids: 策略 ID 列表
        param_overrides: 参数覆盖，格式 {strategy_id: {field_name: new_value}}
                         例如 {"turtle_s1": {"avg_amount_20d": 30000000, "atr_pct": [1.5, 4]}}
    """
    import os
    import yaml

    strategies_dir = os.path.join(os.path.dirname(__file__), "..", "strategies")
    all_conditions = []
    overrides = param_overrides or {}

    for sid in strategy_ids:
        yaml_path = os.path.join(strategies_dir, f"{sid}.yaml")
        if not os.path.exists(yaml_path):
            logger.warning("strategy_backtest: strategy file not found: %s", yaml_path)
            continue
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            conds = data.get("conditions", [])

            # 应用参数覆盖
            sid_overrides = overrides.get(sid, {})
            if sid_overrides and conds:
                conds = _apply_param_overrides(conds, sid_overrides)

            if conds:
                all_conditions.append({"logic": "AND", "conditions": conds})
        except Exception:
            logger.warning("strategy_backtest: failed to load %s", yaml_path, exc_info=True)

    if not all_conditions:
        return None

    if len(all_conditions) == 1:
        return all_conditions[0]
    else:
        return {"logic": "OR", "conditions": all_conditions}


def _apply_param_overrides(conditions: list[dict], overrides: dict[str, any]) -> list[dict]:
    """将参数覆盖应用到条件列表，返回新的条件列表（不修改原始数据）"""
    import copy
    result = copy.deepcopy(conditions)
    for cond in result:
        field = cond.get("field", "")
        if field in overrides:
            new_val = overrides[field]
            if "value" in cond:
                cond["value"] = new_val
            # 对于 compare_field 类型的条件，如果覆盖的是 compare_field 的值，需要特殊处理
            # 目前主要用于覆盖 value 类型的条件
    return result


def _list_available_strategies() -> list[dict]:
    """列出所有可用策略（包含来源、标签、可调参数等元信息）"""
    import os
    import yaml

    strategies_dir = os.path.join(os.path.dirname(__file__), "..", "strategies")
    result = []
    if not os.path.isdir(strategies_dir):
        return result

    for fname in sorted(os.listdir(strategies_dir)):
        if not fname.endswith(".yaml"):
            continue
        try:
            with open(os.path.join(strategies_dir, fname), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            result.append({
                "id": data.get("id", fname.replace(".yaml", "")),
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "source": data.get("source", ""),
                "source_url": data.get("source_url", ""),
                "tags": data.get("tags", []),
                "params": data.get("params", []),
                "market_state": data.get("market_state", []),
                "recommended_position": data.get("recommended_position", ""),
                "conditions_count": len(data.get("conditions", [])),
            })
        except Exception:
            pass

    # 加上内置策略
    from services.backtest_service import AVAILABLE_STRATEGIES
    for sid, info in AVAILABLE_STRATEGIES.items():
        result.append({
            "id": sid,
            "name": info["name"],
            "description": "内置技术指标策略",
            "source": "",
            "source_url": "",
            "tags": [],
            "params": [],
            "market_state": [],
            "recommended_position": "",
            "conditions_count": 1,
            "builtin": True,
        })

    return result


def _build_trade_reason(code: str, strategy_ids: list[str]) -> str:
    """为交易构建信号解释文本"""
    if not strategy_ids:
        return "策略选股"
    sid = strategy_ids[0]  # 取第一个策略
    try:
        from services.discipline_service import build_signal_reason
        return build_signal_reason(code, sid)
    except Exception:
        return f"策略选股: {sid}"


def _calc_fee(amount: float, is_buy: bool = True) -> float:
    """计算A股单笔交易手续费

    买入: 佣金(万分之三, 最低5元) + 过户费(十万分之一)
    卖出: 佣金(万分之三, 最低5元) + 印花税(千分之一) + 过户费(十万分之一)
    """
    commission = max(amount * _COMMISSION_RATE, _COMMISSION_MIN)
    transfer = amount * _TRANSFER_FEE_RATE
    stamp = 0 if is_buy else amount * _STAMP_TAX_RATE
    return round(commission + stamp + transfer, 2)


def _overfit_warning(num_trades: int, max_dd: float, sharpe: float) -> str | None:
    """检测过拟合风险，返回警告字符串或 None"""
    warnings = []
    if num_trades == 0:
        warnings.append("回测期间无符合条件的交易——策略条件未触发。可检查：①回测日期范围是否够长 ②策略参数是否过于严格 ③股票是否处于策略适用的市场环境")
    elif num_trades < 10:
        warnings.append(f"交易次数仅{num_trades}笔，统计显著性不足，建议用更长时间范围验证")
    elif num_trades < 30:
        warnings.append(f"交易次数{num_trades}笔偏少，建议用更长时间范围验证")
    if num_trades > 0:
        if sharpe > 4:
            warnings.append("夏普比率异常高(>4)，可能存在未来信息泄露或过拟合")
        if abs(max_dd) < 0.02:
            warnings.append("最大回撤极低(<2%)，请确认回测条件是否过于宽松")
    return "；".join(warnings) if warnings else None


# ═══════════════════════════════════════════════════════════════
#  日期 / 交易数据
# ═══════════════════════════════════════════════════════════════

def _get_trading_dates(start: str, end: str) -> list[str]:
    """获取日期范围内的所有交易日（从 historical_kline 表）"""
    rows = query_all(
        """SELECT DISTINCT trade_date FROM historical_kline
           WHERE trade_date >= ? AND trade_date <= ?
           ORDER BY trade_date ASC""",
        (start, end),
    )
    return [r["trade_date"] for r in rows]


def _filter_rebalance_dates(dates: list[str], freq: str) -> list[str]:
    """按频率筛选调仓日"""
    if freq == "daily":
        return dates
    elif freq == "weekly":
        # 取每周第一个交易日
        result = []
        last_week = None
        for d in dates:
            try:
                dt = datetime.fromisoformat(d)
                week = dt.isocalendar()[1]
            except Exception:
                continue
            if week != last_week:
                result.append(d)
                last_week = week
        return result
    elif freq == "monthly":
        # 取每月第一个交易日
        result = []
        last_month = None
        for d in dates:
            month = d[:7]  # "2024-01"
            if month != last_month:
                result.append(d)
                last_month = month
        return result
    return dates


def _index_of(dates: list[str], target: str) -> int:
    """找到 target 在 dates 中的索引，未找到返回 -1"""
    try:
        return dates.index(target)
    except ValueError:
        return -1


def _trading_days_between(all_dates: list[str], start: str, end: str) -> int:
    """计算两个日期之间的交易日数"""
    si = _index_of(all_dates, start)
    ei = _index_of(all_dates, end)
    if si < 0 or ei < 0:
        return 999
    return max(0, ei - si)


# ═══════════════════════════════════════════════════════════════
#  价格查询（仅从 historical_kline，不调 API）
# ═══════════════════════════════════════════════════════════════

def _get_price_on_date(code: str, date: str, price_type: str = "close") -> float | None:
    """从 historical_kline 表获取某日价格"""
    col = price_type  # open / close / high / low
    row = query_all(
        f"""SELECT {col} FROM historical_kline
           WHERE stock_code = ? AND trade_date = ?
           LIMIT 1""",
        (code, date),
    )
    if row and row[0][col] is not None:
        return float(row[0][col])
    return None


# ═══════════════════════════════════════════════════════════════
#  历史截面选股
# ═══════════════════════════════════════════════════════════════

def _screen_stocks(
    codes: list[str],
    as_of_date: str,
    condition_tree: dict,
    trading_dates: list[str],
    top_n: int = 10,
    lookback_days: int = 120,
) -> list[dict]:
    """在指定截面日期运行策略选股

    Args:
        codes: 候选股票列表
        as_of_date: 截面日期（只用 <= 该日期的数据）
        condition_tree: 条件树
        trading_dates: 所有交易日列表
        top_n: 返回前 N 只（按策略 sort_by 排序）
        lookback_days: 回看天数

    Returns:
        [{code, name}, ...] 按策略优先级排序
    """
    from services.condition_engine import evaluate
    from services.backtest_field_builder import build_stock_data

    matched = []
    for code in codes:
        kline = _build_historical_snapshot(code, as_of_date, lookback_days)
        if kline is None or len(kline.get("closes", [])) < 20:
            continue

        sd = build_stock_data(kline)
        if sd.get("error"):
            continue

        try:
            if evaluate(sd, condition_tree):
                name = _get_stock_name(code)
                matched.append({"code": code, "name": name})
        except Exception:
            logger.debug("strategy_backtest: evaluate error for %s on %s", code, as_of_date, exc_info=True)

    # 按策略排序：如有 sort_by 字段，使用它
    # 这里简化处理：先到先得
    return matched[:top_n]


def _build_historical_snapshot(code: str, as_of_date: str, lookback_days: int = 120) -> dict | None:
    """构建历史截面 K 线数据（只用 as_of_date 及之前的数据，无未来信息泄露）"""
    rows = query_all(
        """SELECT trade_date, open, high, low, close, volume
           FROM historical_kline
           WHERE stock_code = ? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT ?""",
        (code, as_of_date, lookback_days),
    )
    if not rows or len(rows) < 20:
        return None

    # 反转为时间升序
    rows_rev = list(reversed(rows))
    return {
        "dates": [r["trade_date"] for r in rows_rev],
        "opens": [r["open"] for r in rows_rev],
        "highs": [r["high"] for r in rows_rev],
        "lows": [r["low"] for r in rows_rev],
        "closes": [r["close"] for r in rows_rev],
        "volumes": [r["volume"] for r in rows_rev],
    }


# ═══════════════════════════════════════════════════════════════
#  股票名称缓存
# ═══════════════════════════════════════════════════════════════

_NAME_CACHE: dict[str, str] = {}
_NAME_CACHE_LOADED = False


def _get_stock_name(code: str) -> str:
    """获取股票名称（带缓存，多源回退）"""
    global _NAME_CACHE, _NAME_CACHE_LOADED

    if code in _NAME_CACHE:
        return _NAME_CACHE[code]

    # 尝试从 all_stock_list 加载
    if not _NAME_CACHE_LOADED:
        try:
            from services.screener_service import get_all_stock_list
            stocks = get_all_stock_list(force_refresh=False)
            for s in stocks:
                if s.get("name"):
                    _NAME_CACHE[s["code"]] = s["name"]
            _NAME_CACHE_LOADED = True
        except Exception:
            pass

    if code in _NAME_CACHE:
        return _NAME_CACHE[code]

    # 从 holdings 表查询
    row = query_all(
        "SELECT stock_name FROM holdings WHERE stock_code = ? LIMIT 1",
        (code,),
    )
    name = row[0]["stock_name"] if row and row[0].get("stock_name") else code
    _NAME_CACHE[code] = name
    return name


# ═══════════════════════════════════════════════════════════════
#  基准指数
# ═══════════════════════════════════════════════════════════════

def _get_benchmark_curve(benchmark: str, start: str, end: str) -> list[dict]:
    """获取基准指数净值曲线——优先用 ETF，否则用全市场等权合成基准"""
    # 尝试 ETF 代理
    proxy_map = {"000300": "510300", "000905": "510500", "399006": "159915"}
    proxy = proxy_map.get(benchmark, benchmark)

    rows = query_all(
        """SELECT trade_date, close FROM historical_kline
           WHERE stock_code = ? AND trade_date >= ? AND trade_date <= ?
           ORDER BY trade_date ASC""",
        (proxy, start, end),
    )
    if rows:
        base = rows[0]["close"]
        if base:
            return [
                {"date": r["trade_date"], "value": round(float(r["close"]) / float(base) * 100000, 2)}
                for r in rows
            ]

    # 回退：用库中所有股票的等权平均构建合成基准
    all_stocks = query_all(
        "SELECT DISTINCT stock_code FROM historical_kline"
    )
    if not all_stocks:
        return []

    codes = [s["stock_code"] for s in all_stocks]
    # 抽样 100 只加速
    if len(codes) > 100:
        import random
        random.seed(42)
        codes = random.sample(codes, 100)

    # 获取每只股票的日收益率，取平均
    daily_returns: dict[str, list[float]] = {}
    for code in codes:
        rows = query_all(
            """SELECT trade_date, close FROM historical_kline
               WHERE stock_code = ? AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date ASC""",
            (code, start, end),
        )
        if len(rows) < 2:
            continue
        for i in range(1, len(rows)):
            date = rows[i]["trade_date"]
            prev = float(rows[i - 1]["close"])
            curr = float(rows[i]["close"])
            if prev > 0:
                if date not in daily_returns:
                    daily_returns[date] = []
                daily_returns[date].append((curr - prev) / prev)

    if not daily_returns:
        return []

    # 每日等权平均收益 → 累计净值
    sorted_dates = sorted(daily_returns.keys())
    value = 100000.0
    result = []
    for date in sorted_dates:
        rets = daily_returns[date]
        if rets:
            avg_ret = sum(rets) / len(rets)
            value *= (1 + avg_ret)
        result.append({"date": date, "value": round(value, 2)})

    return result


def _interpolate_benchmark(curve: list[dict], date: str) -> float | None:
    """从基准曲线中获取某日的值"""
    if not curve:
        return None
    for pt in curve:
        if pt["date"] == date:
            return pt["value"]
    return None


# ═══════════════════════════════════════════════════════════════
#  绩效指标
# ═══════════════════════════════════════════════════════════════

def _calculate_metrics(
    equity_curve: list[dict],
    initial_cash: float,
    trades: list[dict],
    start_date: str,
    end_date: str,
) -> dict:
    """从净值和交易记录计算绩效指标"""
    if not equity_curve or len(equity_curve) < 2:
        return {
            "total_return": 0, "annual_return": 0,
            "sharpe": 0, "max_drawdown": 0,
            "win_rate": 0, "profit_factor": 0,
            "num_trades": 0, "calmar": 0, "final_value": initial_cash,
        }

    # 总收益
    final_value = equity_curve[-1]["value"]
    total_return = (final_value - initial_cash) / initial_cash

    # 年化收益
    try:
        d0 = datetime.fromisoformat(equity_curve[0]["date"])
        d1 = datetime.fromisoformat(equity_curve[-1]["date"])
        days = max((d1 - d0).days, 1)
        annual_return = (1 + total_return) ** (365 / days) - 1
    except Exception:
        annual_return = total_return

    # 日收益率序列
    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["value"]
        curr = equity_curve[i]["value"]
        if prev and prev > 0:
            daily_returns.append((curr - prev) / prev)

    # 夏普比率
    if daily_returns:
        import math
        avg_ret = sum(daily_returns) / len(daily_returns)
        if len(daily_returns) > 1:
            variance = sum((r - avg_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
            std = math.sqrt(variance)
            sharpe = round(avg_ret / std * math.sqrt(252), 4) if std > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0

    # 最大回撤
    peak = equity_curve[0]["value"]
    max_dd = 0.0
    for pt in equity_curve:
        v = pt["value"]
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd

    # 交易统计
    sell_trades = [t for t in trades if t["direction"] == "sell" and t["pnl"] is not None]
    num_trades = len(sell_trades)
    wins = sum(1 for t in sell_trades if t["pnl"] > 0)
    losses = sum(1 for t in sell_trades if t["pnl"] < 0)
    win_rate = wins / num_trades if num_trades > 0 else 0

    gross_profit = sum(t["pnl"] for t in sell_trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in sell_trades if t["pnl"] < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999 if gross_profit > 0 else 0)

    # 卡玛比率
    calmar = round(annual_return / abs(max_dd), 4) if max_dd != 0 else 0

    return {
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "sharpe": sharpe,
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": profit_factor,
        "num_trades": num_trades,
        "win_count": wins,
        "loss_count": losses,
        "calmar": calmar,
        "final_value": round(final_value, 2),
        "initial_cash": initial_cash,
        "total_pnl": round(sum(t["pnl"] for t in sell_trades), 2),
        "avg_win": round(sum(t["pnl"] for t in sell_trades if t["pnl"] > 0) / wins, 2) if wins > 0 else 0,
        "avg_loss": round(sum(t["pnl"] for t in sell_trades if t["pnl"] < 0) / losses, 2) if losses > 0 else 0,
        # 过拟合风险警告
        "overfit_warning": _overfit_warning(num_trades, max_dd, sharpe),
        "fees_included": True,
    }


def _calculate_monthly_returns(equity_curve: list[dict], benchmark_curve: list[dict]) -> list[dict]:
    """计算月度收益对比"""
    if not equity_curve:
        return []

    # 按月分组
    from collections import defaultdict
    months = defaultdict(list)
    for pt in equity_curve:
        month = pt["date"][:7]
        months[month].append(pt)

    result = []
    for month in sorted(months.keys()):
        pts = months[month]
        first_val = pts[0]["value"]
        last_val = pts[-1]["value"]
        strat_ret = round((last_val - first_val) / first_val * 100, 2) if first_val > 0 else 0

        bm_ret = None
        if benchmark_curve:
            bm_pts = [b for b in benchmark_curve if b["date"][:7] == month]
            if len(bm_pts) >= 2:
                bm_first = bm_pts[0]["value"]
                bm_last = bm_pts[-1]["value"]
                bm_ret = round((bm_last - bm_first) / bm_first * 100, 2) if bm_first > 0 else 0

        result.append({
            "month": month,
            "strategy_return": strat_ret,
            "benchmark_return": bm_ret,
        })

    return result


# ═══════════════════════════════════════════════════════════════
#  参数优化器 — 网格搜索最优参数组合
# ═══════════════════════════════════════════════════════════════

def optimize_strategy_params(
    strategy_id: str,
    stock_codes: list[str] | None = None,
    start_date: str = "2025-01-01",
    end_date: str = "2026-06-01",
    initial_cash: float = 100000,
    hold_days: int = 5,
    rebalance_freq: str = "daily",
    max_positions: int = 10,
    position_size_pct: float = 0.1,
    top_n: int = 20,
) -> dict:
    """对策略参数做网格搜索，返回按最大回撤→夏普排序的最优组合

    工作流:
      1. 加载策略 YAML，提取 params 定义
      2. 为每个参数生成候选值列表（按 range/step 生成）
      3. 笛卡尔积 → 所有参数组合（上限 300 组，超出则随机采样）
      4. 对每个组合跑 run_strategy_backtest()（通过 param_overrides 传入）
      5. 按 max_drawdown 升序 → sharpe 降序 排名
      6. 返回 top_n 个结果

    Returns:
        {
            "strategy_id": str,
            "strategy_name": str,
            "params_definition": [...],
            "total_combinations": int,
            "evaluated": int,
            "top_results": [{rank, params, metrics}, ...],
            "default_params": {field: default_value, ...},
            "default_metrics": {...},
        }
    """
    import os
    import yaml
    import itertools
    import random

    # 1. 加载策略
    strategies_dir = os.path.join(os.path.dirname(__file__), "..", "strategies")
    yaml_path = os.path.join(strategies_dir, f"{strategy_id}.yaml")
    if not os.path.exists(yaml_path):
        return {"error": f"策略文件不存在: {strategy_id}.yaml"}

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    params_def = data.get("params", [])
    if not params_def:
        return {"error": f"策略 '{strategy_id}' 没有定义可调参数"}

    strategy_name = data.get("name", strategy_id)

    # 2. 为每个参数生成候选值
    param_candidates: dict[str, list] = {}
    default_params: dict[str, any] = {}

    for p in params_def:
        name = p["name"]
        ptype = p.get("type", "number")
        default = p.get("default")
        prange = p.get("range", [])
        step = p.get("step", 1)

        default_params[name] = default

        if ptype == "range":
            candidates = _generate_range_candidates(default, prange)
        elif ptype == "number" and isinstance(prange, list) and len(prange) == 2:
            candidates = _generate_number_candidates(prange[0], prange[1], step)
        else:
            candidates = [default]

        param_candidates[name] = candidates

    # 3. 笛卡尔积
    param_names = list(param_candidates.keys())
    combinations = list(itertools.product(*[param_candidates[n] for n in param_names]))

    total = len(combinations)
    max_combos = 300

    if total > max_combos:
        random.seed(42)
        combinations = random.sample(combinations, max_combos)

    evaluated = len(combinations)

    # 4. 对每个组合跑回测
    results = []
    for combo in combinations:
        overrides = {strategy_id: dict(zip(param_names, combo))}
        bt = run_strategy_backtest(
            strategy_ids=[strategy_id],
            stock_codes=stock_codes,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            hold_days=hold_days,
            rebalance_freq=rebalance_freq,
            max_positions=max_positions,
            position_size_pct=position_size_pct,
            param_overrides=overrides,
        )

        if "error" in bt:
            continue

        metrics = bt.get("metrics", {})
        results.append({
            "params": overrides[strategy_id],
            "metrics": metrics,
        })

    # 5. 排序: max_drawdown ASC (回撤越小越好) → sharpe DESC → win_rate DESC
    results.sort(key=lambda r: (
        abs(r["metrics"].get("max_drawdown", -1)),
        -(r["metrics"].get("sharpe", -999)),
        -(r["metrics"].get("win_rate", 0)),
    ))

    # 6. 跑默认参数的基准回测
    default_bt = run_strategy_backtest(
        strategy_ids=[strategy_id],
        stock_codes=stock_codes,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        hold_days=hold_days,
        rebalance_freq=rebalance_freq,
        max_positions=max_positions,
        position_size_pct=position_size_pct,
    )

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "params_definition": params_def,
        "total_combinations": total,
        "evaluated": evaluated,
        "top_results": [
            {
                "rank": i + 1,
                "params": r["params"],
                "metrics": r["metrics"],
            }
            for i, r in enumerate(results[:top_n])
        ],
        "default_params": default_params,
        "default_metrics": default_bt.get("metrics", {}),
    }


def compare_strategies(
    strategy_ids: list[str],
    stock_codes: list[str] | None = None,
    start_date: str = "2025-01-01",
    end_date: str = "2026-06-01",
    initial_cash: float = 100000,
    hold_days: int = 5,
    rebalance_freq: str = "daily",
    max_positions: int = 10,
    position_size_pct: float = 0.1,
) -> dict:
    """并行跑多个策略，返回每个策略独立回测结果用于并排对比"""
    import yaml, os

    if not strategy_ids:
        return {"error": "至少选择一个策略", "strategies": []}

    if stock_codes is None or len(stock_codes) == 0:
        stock_codes = list(_DEFAULT_POOL)

    strategies_dir = os.path.join(os.path.dirname(__file__), "..", "strategies")
    results = []

    for sid in strategy_ids:
        strategy_name = sid
        yaml_path = os.path.join(strategies_dir, f"{sid}.yaml")
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    strategy_name = yaml.safe_load(f).get("name", sid)
            except Exception:
                pass

        bt = run_strategy_backtest(
            strategy_ids=[sid],
            stock_codes=list(stock_codes),
            start_date=start_date, end_date=end_date,
            initial_cash=initial_cash, hold_days=hold_days,
            rebalance_freq=rebalance_freq, max_positions=max_positions,
            position_size_pct=position_size_pct, include_fees=True,
        )

        if "error" not in bt:
            results.append({
                "strategy_id": sid, "strategy_name": strategy_name,
                "metrics": bt.get("metrics", {}),
                "equity_curve": bt.get("equity_curve", []),
                "trades": bt.get("trades", []),
            })

    ranking = sorted([
        {"strategy_id": r["strategy_id"], "strategy_name": r["strategy_name"],
         "total_return": r["metrics"].get("total_return", 0),
         "sharpe": r["metrics"].get("sharpe", 0),
         "max_drawdown": r["metrics"].get("max_drawdown", 0),
         "win_rate": r["metrics"].get("win_rate", 0),
         "num_trades": r["metrics"].get("num_trades", 0)}
        for r in results
    ], key=lambda x: (abs(x["max_drawdown"]), -x["sharpe"]))

    return {"strategies": results, "ranking": ranking}


def _generate_number_candidates(low: float, high: float, step: float) -> list:
    """生成 number 类型参数的候选值列表（最多8个均匀采样点）"""
    candidates = []
    val = low
    while val <= high + 0.0001:
        candidates.append(round(val, 4) if isinstance(step, float) else val)
        val += step
    if len(candidates) > 8:
        n = min(8, len(candidates))
        indices = [int(i * (len(candidates) - 1) / (n - 1)) for i in range(n)]
        candidates = [candidates[i] for i in indices]
    return candidates


def _generate_range_candidates(default_val: list, prange: list) -> list:
    """生成 range 类型参数的候选组合（3-5 组典型范围）"""
    candidates = [tuple(default_val)]
    if not prange or not isinstance(prange, list) or len(prange) < 2:
        return candidates

    low_range = prange[0]
    high_range = prange[1]

    mid_low = round((low_range[0] + default_val[0]) / 2, 2)
    mid_high = round((default_val[1] + high_range[1]) / 2, 2)

    for alt in [
        (low_range[0], mid_high),
        (mid_low, high_range[1]),
        (low_range[0], high_range[1]),
    ]:
        if alt != tuple(default_val):
            candidates.append(alt)

    return candidates
