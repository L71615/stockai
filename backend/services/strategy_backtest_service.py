"""策略回测引擎 — 用 YAML 策略在历史数据上模拟选股 + 交易 + 绩效评估

核心工作流:
  对每个调仓日（从 start_date 到 end_date）:
    1. 从 historical_kline 为每只候选股构建"当日截面"K 线数据（只看 as_of_date 之前）
    2. 用 backtest_field_builder 计算技术字段
    3. 用 condition_engine.evaluate() 跑策略筛选
    4. 模拟买入（次日开盘价）/ 卖出（持仓满 hold_days）
    5. 记录每日净值曲线

依赖: historical_kline 表必须有足够的历史数据

v3.11 (T2): _evaluate_overfit_from_snapshot() — 用冻结快照做 OOS 判定,
  任何 trade/curve 日期 > as_of_date 都视为泄漏, 直接抛 SnapshotLeakageError.
"""
import logging
from datetime import datetime, timedelta

from database import query_all
from services.snapshot_service import SnapshotLeakageError

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
    commission_rate: float = 0.0003,
    slippage_bps: float = 10.0,
    impact_bps: float = 0.0,
    adv_window: int = 20,
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
        include_fees: 是否计入手续费
        commission_rate: 佣金率(默认 0.0003 = 万分之三)
        slippage_bps: 固定滑点(basis points,1bp = 0.01%);默认 10bps = 0.1%。
                     买入价 × (1 + slippage),卖出价 × (1 - slippage)
        impact_bps: 冲击成本系数(v4.0 B5)。基于 ADV (Average Daily Volume) 比例
                    的平方根模型: impact = impact_bps × sqrt(buy_amount / ADV_value)
                    买入/卖出价各叠加一次(在 slippage 之外)。
                    默认 0 = 关闭冲击成本。
        adv_window: ADV 计算窗口(默认 20 日)。

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

    # 滑点系数(卖出减、买入加)
    _slip_factor = slippage_bps / 10000.0

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

            # v4.0 B4: 滑点 — 卖出价变差(× (1 - slippage))
            if _slip_factor > 0:
                sell_price = sell_price * (1 - _slip_factor)

            # v4.0 B5: 冲击成本 — 基于 ADV 比例的平方根模型
            if impact_bps > 0:
                _imp = _calc_impact_cost_bps(
                    p["code"], p["shares"], sell_price, impact_bps, adv_window,
                    as_of_date=next_date,
                )
                if _imp > 0:
                    sell_price = sell_price * (1 - _imp / 10000.0)

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

            # v4.0 B4: 滑点 — 买入价变差(× (1 + slippage))
            if _slip_factor > 0:
                buy_price = buy_price * (1 + _slip_factor)

            # v4.0 B5: 冲击成本 — 基于 ADV 比例的平方根模型
            if impact_bps > 0:
                _imp = _calc_impact_cost_bps(
                    c["code"], per_position_cash / buy_price, buy_price, impact_bps, adv_window,
                    as_of_date=next_date,
                )
                if _imp > 0:
                    buy_price = buy_price * (1 + _imp / 10000.0)

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
        # v4.0 B4: 滑点 — 期末清仓也按 (1 - slippage) 处理
        if _slip_factor > 0:
            close_price = close_price * (1 - _slip_factor)
        # v4.0 B5: 期末清仓也加冲击成本
        if impact_bps > 0:
            _imp = _calc_impact_cost_bps(
                p["code"], p["shares"], close_price, impact_bps, adv_window,
                as_of_date=final_date,
            )
            if _imp > 0:
                close_price = close_price * (1 - _imp / 10000.0)
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

    # ── 回测内置保护评估（不修改主回测逻辑，只附加风险信号）──
    protection = _evaluate_protection(
        metrics=metrics,
        trades=trades,
        stock_count=len(stock_codes) if stock_codes else 0,
        start_date=start_date,
        end_date=end_date,
        include_fees=include_fees,
    )

    # ── 过拟合检测：train/test split (默认 70/30) ──
    overfit_check = _evaluate_overfit(
        equity_curve=equity_curve,
        initial_cash=initial_cash,
        trades=trades,
        start_date=start_date,
        end_date=end_date,
    )

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
            "include_fees": include_fees,
            "commission_rate": commission_rate,
            "slippage_bps": slippage_bps,  # v4.0 B4
            "impact_bps": impact_bps,      # v4.0 B5
            "adv_window": adv_window,      # v4.0 B5
        },
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "monthly_returns": monthly_returns,
        "final_positions": final_positions,
        "final_value": round(total_value, 2),
        "_protection": protection,
        "_overfit_check": overfit_check,
    }


def _evaluate_overfit(
    equity_curve: list[dict],
    initial_cash: float,
    trades: list[dict],
    start_date: str,
    end_date: str,
    split_ratio: float = 0.7,
) -> dict:
    """过拟合检测：把数据切 train/test 两段，单独算 metrics

    原理: 前 70% 训练后 30% 测试。
    - 如果 train_metrics.sharpe 远高于 test_metrics.sharpe → 可能过拟合
    - 如果两者接近 → 策略相对稳健

    Returns:
        {
            "split_ratio": 0.7,
            "train_period": [start, mid],
            "test_period": [mid+1, end],
            "train_metrics": {sharpe, total_return, max_drawdown, num_trades, ...},
            "test_metrics": {sharpe, total_return, max_drawdown, num_trades, ...},
            "sharpe_decay_pct": float,  # (train_sharpe - test_sharpe) / train_sharpe
            "verdict": "stable" | "watch" | "overfit",
            "message": "人类可读说明"
        }
    """
    if not equity_curve or len(equity_curve) < 10:
        return {
            "split_ratio": split_ratio,
            "error": "数据太少 (<10 个交易日)，无法做 train/test split",
        }

    n = len(equity_curve)
    split_idx = int(n * split_ratio)
    if split_idx < 5 or (n - split_idx) < 5:
        return {
            "split_ratio": split_ratio,
            "error": f"数据点太少 (n={n}), split 后训练/测试样本不足",
        }

    train_curve = equity_curve[:split_idx]
    test_curve = equity_curve[split_idx:]

    train_metrics = _calculate_metrics(
        train_curve, initial_cash,
        [t for t in trades if t.get("date", "") <= train_curve[-1]["date"]],
        start_date, train_curve[-1]["date"],
    )
    test_metrics = _calculate_metrics(
        test_curve, initial_cash,
        [t for t in trades if t.get("date", "") > train_curve[-1]["date"]],
        train_curve[-1]["date"], end_date,
    )

    # 过拟合判定: 训练 Sharpe vs 测试 Sharpe
    train_sharpe = train_metrics.get("sharpe", 0) or 0
    test_sharpe = test_metrics.get("sharpe", 0) or 0

    # 关键: 只在"训练看起来好"时才判过拟合。
    # 训练/测试都负 (都亏钱) 是"策略整体差",不是过拟合。
    if abs(train_sharpe) < 0.01:
        sharpe_decay_pct = 0.0
    else:
        sharpe_decay_pct = (train_sharpe - test_sharpe) / abs(train_sharpe)

    # 判定: 训练 Sharpe 必须 > 0.5 (策略看起来"有点用") 才做对比
    # 否则 verdict = "weak" (策略本身无效, 不是过拟合问题)
    if train_sharpe < 0.5:
        verdict = "weak"
        msg = (f"⚡ 训练 Sharpe {train_sharpe:.2f} 太低, 策略整体无效 — "
               f"先验证策略逻辑, 再谈过拟合")
    elif sharpe_decay_pct > 0.5:
        verdict = "overfit"
        msg = (f"⚠️ 训练 Sharpe {train_sharpe:.2f} 远高于测试 Sharpe {test_sharpe:.2f} "
               f"(下降 {sharpe_decay_pct*100:.0f}%) — 可能过拟合, 建议调参或减少参数")
    elif sharpe_decay_pct > 0.3:
        verdict = "watch"
        msg = (f"⚡ 训练 Sharpe {train_sharpe:.2f} 与测试 Sharpe {test_sharpe:.2f} 有差距 "
               f"(下降 {sharpe_decay_pct*100:.0f}%) — 需谨慎, 留意实盘表现")
    else:
        verdict = "stable"
        msg = (f"✓ 训练 Sharpe {train_sharpe:.2f} 与测试 Sharpe {test_sharpe:.2f} 接近 "
               f"(下降 {sharpe_decay_pct*100:.0f}%) — 策略相对稳健")

    return {
        "split_ratio": split_ratio,
        "train_period": [train_curve[0]["date"], train_curve[-1]["date"]],
        "test_period": [test_curve[0]["date"], test_curve[-1]["date"]],
        "train_days": len(train_curve),
        "test_days": len(test_curve),
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "sharpe_decay_pct": round(sharpe_decay_pct, 4),
        "verdict": verdict,
        "message": msg,
    }


# ═══════════════════════════════════════════════════════════════
#  v3.11 (T2): snapshot-aware OOS replay
# ═══════════════════════════════════════════════════════════════

def _evaluate_overfit_from_snapshot(
    snapshot: dict,
    equity_curve: list[dict],
    trades: list[dict],
    initial_cash: float,
    split_ratio: float = 0.7,
) -> dict:
    """用冻结快照做 OOS 过拟合判定.

    与 _evaluate_overfit 的关键区别:
      1. 先 assert curve/trades 里的日期 ≤ snapshot.as_of_date (防未来数据泄漏)
      2. 用 snapshot.input_version_hash 标注结果, 调用方可据此比 hash
      3. 把 snapshot 的 as_of_date / policy_version / input_hash 写进返回值

    Args:
        snapshot: 解码后的 snapshot dict (从 snapshot_service.get_snapshot()['snapshot'])
        equity_curve: [{date, value, ...}, ...] 必须 ≤ as_of_date
        trades: [{date, code, ...}, ...] 必须 ≤ as_of_date
        initial_cash: 起始资金
        split_ratio: train/test 切分比

    Returns:
        _evaluate_overfit() 的返回值 + snapshot_meta 字段

    Raises:
        SnapshotLeakageError: 任一日期 > as_of_date
    """
    as_of = snapshot.get("as_of_date")
    if not as_of:
        raise SnapshotLeakageError("snapshot 缺 as_of_date")

    # 1. Leakage check
    leaks = []
    for c in equity_curve:
        d = c.get("date")
        if d and d > as_of:
            leaks.append(("curve", d))
    for t in trades:
        d = t.get("date")
        if d and d > as_of:
            leaks.append(("trade", d))
    if leaks:
        raise SnapshotLeakageError(
            f"检测到 {len(leaks)} 行日期 > as_of_date ({as_of}); "
            f"sample={leaks[:5]}"
        )

    # 2. 跑现有判定 (无泄漏时与原版结果一致)
    start_date = equity_curve[0]["date"] if equity_curve else "1970-01-01"
    end_date = equity_curve[-1]["date"] if equity_curve else as_of

    result = _evaluate_overfit(
        equity_curve=equity_curve,
        initial_cash=initial_cash,
        trades=trades,
        start_date=start_date,
        end_date=end_date,
        split_ratio=split_ratio,
    )

    # 3. 加 snapshot meta
    result["snapshot_meta"] = {
        "as_of_date": as_of,
        "input_version_hash": snapshot.get("__input_hash", ""),
        "policy_version": snapshot.get("config", {}).get("policy_version", ""),
        "stock_pool": snapshot.get("stock_pool", []),
    }
    return result


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

    # v4.1.1: 用 registry 校验 + 共享 yaml_path,typo 不再静默通过
    try:
        from services.strategy_registry import get_registry
        registry = get_registry()
        valid_ids, invalid_ids = registry.validate(strategy_ids)
        if invalid_ids:
            logger.warning(
                "strategy_backtest: %d 个策略 ID 不存在,跳过: %s (可用: %s)",
                len(invalid_ids), invalid_ids,
                [s.id for s in registry.scan()],
            )
            strategy_ids = valid_ids
            if not strategy_ids:
                return None
    except Exception as e:
        # registry 不可用(测试 mock 等)时 fallback 到原行为
        logger.debug("strategy_backtest: registry 不可用,fallback 直接加载: %s", e)
        registry = None

    all_conditions = []
    overrides = param_overrides or {}

    for sid in strategy_ids:
        # v4.1.1: 优先从 registry 拿 yaml_path(共享目录/缓存)
        yaml_path = None
        if registry is not None:
            info = registry.get(sid)
            if info is not None:
                yaml_path = info.yaml_path

        # Fallback: registry 不可用时,本地拼接路径
        if yaml_path is None:
            strategies_dir = os.path.join(os.path.dirname(__file__), "..", "strategies")
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
    """列出所有可用策略（包含来源、标签、可调参数等元信息）

    v4.1.1: 委托给 strategy_registry,行为兼容(返回 dict 列表,字段一致)。
    """
    try:
        from services.strategy_registry import list_strategies as _list
        return _list()
    except Exception as e:
        # registry 不可用时返回空(不静默失败,记 warning 便于排查)
        logger.warning("strategy_backtest: registry 不可用,_list 返回空: %s", e)
        return []


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


def _calc_impact_cost_bps(
    code: str,
    shares: int,
    price: float,
    impact_bps: float,
    adv_window: int = 20,
    *,
    as_of_date: str,
) -> float:
    """v4.0 B5: 冲击成本计算(平方根模型)

    模型: impact_bps = base × sqrt(buy_amount / ADV_value)
    base 来自 impact_bps 参数,ADV = 过去 N 日均成交额(price × volume)。

    Args:
        code: 股票代码(用于查 ADV)
        shares: 本次交易股数
        price: 当前价格(估算 buy_amount)
        impact_bps: 冲击成本系数(bps)
        adv_window: ADV 计算窗口
        as_of_date: 交易日期(关键 — 必须是历史截面日期,不能用 date('now'),
                    否则在回测 2024 年时会用 2026 年的真实 ADV 数据,造成未来信息泄露)。

    Returns:
        实际冲击成本(bps),= 0 表示无影响
    """
    if impact_bps <= 0 or shares <= 0 or price <= 0:
        return 0.0
    try:
        from database import query_all
        rows = query_all(
            """SELECT close, volume FROM historical_kline
               WHERE stock_code = ? AND trade_date <= ?
               ORDER BY trade_date DESC LIMIT ?""",
            (code, as_of_date, adv_window),
        )
        if not rows or len(rows) < 5:
            return 0.0  # 数据不足,不应用冲击
        adv_value = sum(
            float(r["close"]) * float(r["volume"])
            for r in rows
            if r.get("close") and r.get("volume")
        ) / len(rows)
        if adv_value <= 0:
            return 0.0
        buy_amount = shares * price
        # 平方根模型:impact = base × sqrt(order_size / ADV)
        ratio = buy_amount / adv_value
        actual_impact = impact_bps * (ratio ** 0.5)
        return round(min(actual_impact, impact_bps * 5), 2)  # 上限 5x 基础值
    except Exception:
        return 0.0


def _evaluate_protection(
    metrics: dict,
    trades: list[dict],
    stock_count: int,
    start_date: str,
    end_date: str,
    include_fees: bool,
) -> dict:
    """回测内置保护评估 — 不改主回测逻辑，只在结果上附加风险信号

    Returns:
        {
            "include_fees": bool,
            "warnings": [str, ...],       # 人类可读警告
            "sample_size_ok": bool,       # 交易数是否够多
            "overfit_risk": "low"|"medium"|"high",
            "stock_diversity_ok": bool,   # 候选池是否够大
            "period_ok": bool,            # 回测期是否够长
            "suggestions": [str, ...],   # 改进建议
        }
    """
    warnings: list[str] = []
    suggestions: list[str] = []

    num_trades = metrics.get("num_trades", 0) or 0
    sharpe = metrics.get("sharpe", 0) or 0
    max_dd = abs(metrics.get("max_drawdown", 0) or 0)
    win_rate = metrics.get("win_rate", 0) or 0

    # ── 1. 交易样本量 ──
    if num_trades < 20:
        warnings.append(f"交易笔数过少 ({num_trades} < 20)，统计显著性不足，结果不稳定")
        suggestions.append("延长回测期至 1 年以上，或扩大股票池到 100+")
        sample_size_ok = False
    elif num_trades < 50:
        warnings.append(f"交易笔数偏少 ({num_trades} < 50)，建议补充更长回测期")
        sample_size_ok = True
    else:
        sample_size_ok = True

    # ── 2. 过拟合风险 ──
    overfit_risk = "low"
    # 高 Sharpe + 低交易数 + 大回撤 = 典型过拟合
    if sharpe > 2.0 and num_trades < 30:
        overfit_risk = "high"
        warnings.append(f"⚠️ Sharpe={sharpe:.2f} 异常高 + 交易数仅 {num_trades}，疑似过拟合（参数可能针对历史噪声优化）")
        suggestions.append("用样本外数据（前 70% 训练 / 后 30% 测试）验证策略稳健性")
    elif sharpe > 1.5 and max_dd > 0.3:
        overfit_risk = "medium"
        warnings.append(f"Sharpe={sharpe:.2f} 偏高 + 最大回撤 {max_dd*100:.1f}%，收益波动大，注意风险")
    elif sharpe > 1.0 and num_trades < 50:
        overfit_risk = "medium"
        warnings.append(f"Sharpe={sharpe:.2f} 偏高 + 交易数 {num_trades}，可能未充分验证")

    # ── 3. 胜率异常 ──
    if win_rate > 0.85 and num_trades < 30:
        warnings.append(f"胜率 {win_rate*100:.0f}% 异常高，样本不足，结果可能不稳健")
    elif win_rate < 0.3 and num_trades >= 30:
        warnings.append(f"胜率仅 {win_rate*100:.0f}%，策略长期可能不盈利（看盈亏比）")

    # ── 4. 股票池多样性 ──
    if stock_count == 0:
        stock_diversity_ok = True  # 用了默认池，不警告
    elif stock_count < 5:
        warnings.append(f"股票池过小 ({stock_count} 只)，策略可能过拟合于这几只特定股票")
        suggestions.append("扩大股票池至 30+ 只以验证普适性")
        stock_diversity_ok = False
    elif stock_count < 30:
        stock_diversity_ok = True
        suggestions.append(f"股票池 {stock_count} 只偏小，建议扩展到 30+ 验证普适性")
    else:
        stock_diversity_ok = True

    # ── 5. 回测期长度 ──
    try:
        from datetime import datetime
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        days = (d2 - d1).days
        if days < 180:
            warnings.append(f"回测期仅 {days} 天 (< 6 个月)，覆盖市场周期不足")
            suggestions.append("至少覆盖 1 年回测期（含牛/熊/震荡）")
            period_ok = False
        elif days < 365:
            period_ok = True
            suggestions.append(f"回测期 {days} 天偏短，建议至少 1 年")
        else:
            period_ok = True
    except Exception:
        period_ok = True

    # ── 6. 手续费透明度 ──
    if not include_fees:
        warnings.append("回测未计入手续费（A 股单边约 0.05%，双边约 0.1%），实际收益会被高估")
        suggestions.append("确认使用 include_fees=True（默认）")

    # ── 综合风险等级 ──
    high_warnings = sum(1 for w in warnings if "⚠️" in w or "异常" in w or "过少" in w)
    if high_warnings >= 2:
        overfit_risk = "high" if overfit_risk == "low" else overfit_risk

    return {
        "include_fees": include_fees,
        "warnings": warnings,
        "suggestions": suggestions,
        "sample_size_ok": sample_size_ok,
        "overfit_risk": overfit_risk,
        "stock_diversity_ok": stock_diversity_ok,
        "period_ok": period_ok,
        "summary": {
            "warning_count": len(warnings),
            "suggestion_count": len(suggestions),
            "overall": "safe" if not warnings else ("caution" if overfit_risk != "high" else "risky"),
        },
    }


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
    """v4.1 Phase 2A: 基准指数净值曲线 — 三段式回退.

    1) index_kline (真实沪深300等指数)
    2) etf_kline (510300/510500/159915 等 ETF)
    3) historical_kline (旧 ETF proxy, 给 index_sync seed 之前过渡)
    4) 全市场等权合成 (last-resort, 旧行为)
    """
    # 1) index_kline 优先 (000/399 code → ak-share symbol)
    if benchmark[:3] in ("000", "399"):
        sym_map = {
            "000300": "sh000300",
            "000905": "sh000905",
            "399006": "sz399006",
            "000016": "sh000016",
            "000852": "sh000852",
            "000688": "sh000688",
        }
        sym = sym_map.get(benchmark)
        if sym:
            rows = query_all(
                """SELECT trade_date, close FROM index_kline
                   WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?
                   ORDER BY trade_date ASC""",
                (sym, start, end),
            )
            if rows:
                base = rows[0]["close"]
                if base:
                    return [
                        {"date": r["trade_date"],
                         "value": round(float(r["close"]) / float(base) * 100000, 2)}
                        for r in rows
                    ]

    # 2) etf_kline 回退 (510/159 code)
    rows = query_all(
        """SELECT trade_date, close FROM etf_kline
           WHERE code = ? AND trade_date >= ? AND trade_date <= ?
           ORDER BY trade_date ASC""",
        (benchmark, start, end),
    )
    if rows:
        base = rows[0]["close"]
        if base:
            return [
                {"date": r["trade_date"],
                 "value": round(float(r["close"]) / float(base) * 100000, 2)}
                for r in rows
            ]

    # 3) 旧 historical_kline ETF proxy (过渡 fallback)
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


# ═══════════════════════════════════════════════════════════
#  v4.0 B6 — 多策略组合回测
#  在 compare_strategies 基础上加信号合并:union/intersect/majority
# ═══════════════════════════════════════════════════════════

def run_combined_backtest(
    strategy_ids: list[str],
    stock_codes: list[str] | None = None,
    start_date: str = "2025-01-01",
    end_date: str = "2026-06-01",
    initial_cash: float = 100000,
    hold_days: int = 5,
    rebalance_freq: str = "daily",
    max_positions: int = 10,
    position_size_pct: float = 0.1,
    combination_mode: str = "majority",
    slippage_bps: float = 10.0,
    impact_bps: float = 0.0,
) -> dict:
    """v4.0 B6: 多策略组合回测 — 跑 N 个策略 + 合并交易信号

    Args:
        strategy_ids: 要组合的策略列表
        combination_mode: 信号合并模式
            - "union": 任一策略触发即买入(OR)
            - "intersect": 所有策略同时触发才买入(AND)
            - "majority": >50% 策略触发才买入(投票)
        其他参数同 run_strategy_backtest

    Returns:
        {
            "combination_mode": str,
            "strategy_count": N,
            "combined": {
                "metrics": {total_return, sharpe, max_drawdown, win_rate, num_trades},
                "trades": [{date, code, direction, price, shares, triggering_strategies}],
                "trade_attribution": {strategy_id: count, ...}
            },
            "per_strategy": [
                {strategy_id, strategy_name, total_return, sharpe, max_drawdown, win_rate, num_trades}
            ]
        }
    """
    if not strategy_ids:
        return {"error": "至少选择一个策略", "strategy_count": 0}

    if combination_mode not in ("union", "intersect", "majority"):
        return {"error": f"不支持的合并模式: {combination_mode}",
                "available": ["union", "intersect", "majority"]}

    # 1. 复用 compare_strategies 拿 N 个策略的独立结果
    comparison = compare_strategies(
        strategy_ids=strategy_ids,
        stock_codes=stock_codes,
        start_date=start_date, end_date=end_date,
        initial_cash=initial_cash, hold_days=hold_days,
        rebalance_freq=rebalance_freq, max_positions=max_positions,
        position_size_pct=position_size_pct,
    )
    if "error" in comparison:
        return comparison

    per_strategy = comparison.get("strategies", [])
    n_strategies = len(per_strategy)
    if n_strategies == 0:
        return {"error": "无可用策略结果", "strategy_count": 0}

    # 2. 收集每个策略的 (date, code) buy 信号集合
    # 同一 (date, code) 出现在 K 个策略 → 触发合并逻辑
    from collections import defaultdict
    signal_votes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for s in per_strategy:
        sid = s["strategy_id"]
        for t in s.get("trades", []):
            if t.get("direction") == "buy":
                signal_votes[(t["date"], t["code"])].append(sid)

    # 3. 按 combination_mode 过滤
    threshold_map = {"union": 1, "intersect": n_strategies, "majority": n_strategies // 2 + 1}
    threshold = threshold_map[combination_mode]
    selected_buys: dict[tuple[str, str], list[str]] = {
        sig: voters for sig, voters in signal_votes.items() if len(voters) >= threshold
    }

    # 4. 构造 combined trades 列表(每个 (date, code) 只加一次,触发策略列表记录所有)
    selected_buy_set = set(selected_buys.keys())
    combined_trades: list[dict] = []
    trade_attribution: dict[str, int] = {sid: 0 for sid in strategy_ids}

    # 选一个 canonical trade info(从第一个触发该信号的策略)
    trade_info_by_signal: dict[tuple[str, str], dict] = {}
    for s in per_strategy:
        for t in s.get("trades", []):
            if t.get("direction") != "buy":
                continue
            sig = (t["date"], t["code"])
            if sig not in selected_buy_set:
                continue
            if sig not in trade_info_by_signal:
                trade_info_by_signal[sig] = t

    for sig in selected_buy_set:
        base_trade = trade_info_by_signal[sig]
        combined_buy = dict(base_trade)
        combined_buy["triggering_strategies"] = selected_buys[sig]
        combined_trades.append(combined_buy)
        # attribution:每个触发策略 +1
        for sid in selected_buys[sig]:
            trade_attribution[sid] += 1

    # 5. 找对应的 sell(同一策略的 sell,后 hold_days 天)
    all_sells_by_strategy: dict[str, list[dict]] = {s["strategy_id"]: s.get("trades", []) for s in per_strategy}
    buy_codes_by_date: dict[str, set[str]] = defaultdict(set)
    for t in combined_trades:
        buy_codes_by_date[t["date"]].add(t["code"])

    for s in per_strategy:
        sid = s["strategy_id"]
        for t in s.get("trades", []):
            if t.get("direction") != "sell":
                continue
            # 只在原始策略的 buy 入选时,这个 sell 才进入 combined
            # 简化:只要 code 在 combined_trades 中出现,对应的 sell 都收
            # (取第一个匹配的策略 sell 作为对应 sell)
            pass  # 复杂匹配留作下一版

    # 6. 简化聚合 metrics(基于 combined trades 的 buy 数 + 简化 PnL 计算)
    n_buys = len(combined_trades)
    combined_metrics = {
        "total_return": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "num_trades": n_buys,
        "num_strategies": n_strategies,
        "combination_mode": combination_mode,
    }

    # 用各策略的加权平均作为 combined 的代理指标
    if per_strategy:
        for key in ("total_return", "sharpe", "max_drawdown", "win_rate"):
            values = [s["metrics"].get(key, 0) for s in per_strategy if "metrics" in s]
            if values:
                combined_metrics[key] = round(sum(values) / len(values), 4)

    return {
        "combination_mode": combination_mode,
        "strategy_count": n_strategies,
        "combined": {
            "metrics": combined_metrics,
            "trades": combined_trades[:20],  # 限前 20 条
            "trade_attribution": trade_attribution,
        },
        "per_strategy": [
            {
                "strategy_id": s["strategy_id"],
                "strategy_name": s["strategy_name"],
                "total_return": s["metrics"].get("total_return", 0),
                "sharpe": s["metrics"].get("sharpe", 0),
                "max_drawdown": s["metrics"].get("max_drawdown", 0),
                "win_rate": s["metrics"].get("win_rate", 0),
                "num_trades": s["metrics"].get("num_trades", 0),
            }
            for s in per_strategy
        ],
    }


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
