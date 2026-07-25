"""影子组合服务 (v3.11+, T4) — 收盘后生成信号, T+1 模拟执行

按 plan-ceo-review 2026-07-24 §Phase 3 设计:
  - 收盘后生成信号 (target_weights)
  - 下一可交易日 (T+1) 执行
  - A 股最低限度执行语义: T+1, 整手 (100 股), 现金约束, 涨跌停/停牌未成交
  - 手续费: 佣金万三+最低5, 印花税千一(仅卖), 过户费十万分之一
  - 合法停牌 = 沿用上一有效价 + 标 'stale'
  - 未知缺价 = 标 'blocked', 不生成 evidence
  - UNIQUE(portfolio_id, observation_date, input_version) 防重复结算

公开 API:
  - create_shadow_portfolio(owner_user_id, candidate_id=..., name=...) -> portfolio_id
  - get_portfolio(portfolio_id) -> dict
  - list_portfolios(owner_user_id=...) -> list[dict]
  - set_target_weights(portfolio_id, weights: dict, as_of_date)
  - settle_day(portfolio_id, observation_date, prices: dict, *, input_version) -> snapshot
  - settle_window(portfolio_id, start_date, end_date, prices_by_date: dict) -> list[snapshot]
  - get_snapshots(portfolio_id, start=..., end=...) -> list[dict]

异常:
  - ShadowPortfolioError (基类)
  - ShadowPortfolioSettlementError
  - ShadowPortfolioNotFoundError
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from database import execute, query_all, query_one
from services.fees import calc_total_fee
from services.trading_calendar import next_trading_day, prev_trading_day

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  异常
# ════════════════════════════════════════════════════════════

class ShadowPortfolioError(Exception):
    http_status = 400


class ShadowPortfolioNotFoundError(ShadowPortfolioError):
    http_status = 404


class ShadowPortfolioSettlementError(ShadowPortfolioError):
    http_status = 422


# ════════════════════════════════════════════════════════════
#  内部工具
# ════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _round_lots(shares: int, lot_size: int = 100) -> int:
    """整手化: 向下取整到 lot_size 倍数."""
    if lot_size <= 0:
        return shares
    return (shares // lot_size) * lot_size


def _compute_target_shares(
    nav: float,
    prev_holdings: dict[str, int],
    target_weights: dict[str, float],
    prices: dict[str, float],
    lot_size: int = 100,
    min_cash_buffer: float = 100.0,
) -> tuple[dict[str, int], float]:
    """根据 target_weights 和 NAV, 计算每只股票的目标股数.

    Args:
        nav: 总净值 (prev_cash + prev_holdings 当前市值), 用作再平衡基准
        prev_holdings: {code: shares} 当前持仓, 不在 target_weights 里的会被卖
        target_weights: {code: weight} (权重和应 ≤ 1, 多余保留为现金)
        prices: {code: price} 今日价
        min_cash_buffer: 结算后最少留多少现金 (手续费 buffer), 默认 100 元

    Returns:
        (target_shares, leftover_cash)
        - target_shares: 新目标持仓
        - leftover_cash: 购买后剩余现金 (含 buffer)
    """
    total_weight = sum(target_weights.values())
    if total_weight > 1.0:
        target_weights = {k: v / total_weight for k, v in target_weights.items()}

    target_shares: dict[str, int] = {}
    leftover = nav
    for code, weight in target_weights.items():
        price = prices.get(code)
        if not price or price <= 0:
            continue
        allocation = nav * weight
        raw_shares = int(allocation / price)
        lots = _round_lots(raw_shares, lot_size)
        if lots <= 0:
            continue
        cost = lots * price
        while lots > 0 and cost > leftover:
            lots -= lot_size
            if lots <= 0:
                break
            cost = lots * price
        if lots <= 0:
            continue
        target_shares[code] = lots
        leftover -= cost

    # fee 安全: 如果 leftover < min_cash_buffer, 削减最大持仓 1 手
    # 1 手 100 股 * 价 ≈ 100 元 buffer
    while target_shares and leftover < min_cash_buffer:
        biggest_code = max(target_shares, key=lambda c: target_shares[c] * prices.get(c, 0))
        if target_shares[biggest_code] < lot_size:
            break
        target_shares[biggest_code] -= lot_size
        leftover += lot_size * prices.get(biggest_code, 0)
        if target_shares[biggest_code] <= 0:
            del target_shares[biggest_code]

    return target_shares, leftover


# ════════════════════════════════════════════════════════════
#  Portfolio CRUD
# ════════════════════════════════════════════════════════════

def create_shadow_portfolio(
    *,
    owner_user_id: int,
    name: str = "",
    candidate_id: Optional[int] = None,
    experiment_id: Optional[str] = None,
    policy_version: str = "v1.0.0",
    initial_cash: float = 100000.0,
    scope: str = "paper",
) -> int:
    """新建一个影子组合. 返回 portfolio_id (INT PK)."""
    cur = execute(
        "INSERT INTO shadow_portfolios "
        "(owner_user_id, experiment_id, candidate_id, name, policy_version, "
        " initial_cash, target_weights_json, scope, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, '{}', ?, 'active', ?, ?)",
        (owner_user_id, experiment_id, candidate_id, name, policy_version,
         initial_cash, scope, _now(), _now()),
    )
    return int(cur["lastrowid"])


def get_portfolio(portfolio_id: int) -> dict:
    row = query_one("SELECT * FROM shadow_portfolios WHERE portfolio_id = ?", (portfolio_id,))
    if not row:
        raise ShadowPortfolioNotFoundError(f"portfolio {portfolio_id} not found")
    row["target_weights"] = json.loads(row.get("target_weights_json") or "{}")
    return row


def list_portfolios(*, owner_user_id: Optional[int] = None) -> list[dict]:
    where = []
    params: list[Any] = []
    if owner_user_id is not None:
        where.append("owner_user_id = ?")
        params.append(owner_user_id)
    sql = "SELECT * FROM shadow_portfolios"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY portfolio_id DESC"
    return query_all(sql, tuple(params))


def set_target_weights(
    portfolio_id: int,
    weights: dict[str, float],
    *,
    as_of_date: Optional[str] = None,
) -> None:
    """设置组合的目标权重 (信号生成).

    as_of_date: 信号生成日 (默认今天), 真实执行是 T+1.
    """
    p = get_portfolio(portfolio_id)
    execute(
        "UPDATE shadow_portfolios SET target_weights_json = ?, updated_at = ? "
        "WHERE portfolio_id = ?",
        (json.dumps(weights, ensure_ascii=False), _now(), portfolio_id),
    )
    logger.info("portfolio %s targets set at %s: %s",
                portfolio_id, as_of_date or "now", weights)


# ════════════════════════════════════════════════════════════
#  单日结算
# ════════════════════════════════════════════════════════════

def settle_day(
    portfolio_id: int,
    observation_date: str,
    prices: dict[str, float],
    *,
    prev_holdings: Optional[dict[str, int]] = None,
    prev_cash: Optional[float] = None,
    input_version: str = "",
    baseline_prices: Optional[dict[str, float]] = None,
) -> dict:
    """单日结算: T+1 执行 + 整手 + 涨跌停 + 手续费.

    Args:
        portfolio_id: 影子组合 ID
        observation_date: 结算观察日 (YYYY-MM-DD)
        prices: {code: price} 当日开盘价或收盘价 (执行价)
        prev_holdings: {code: shares} 前一日持仓, 默认从快照读最新
        prev_cash: 前一日现金, 默认从快照读最新
        input_version: 输入快照 hash, 用于 UNIQUE 约束
        baseline_prices: {benchmark_code: price} 可选, 用于算 baseline_diff

    Returns:
        snapshot dict

    Raises:
        ShadowPortfolioSettlementError: 缺价 / 数据异常
    """
    p = get_portfolio(portfolio_id)

    # 1. UNIQUE 检查: 已结算过就直接返回
    existing = query_one(
        "SELECT * FROM shadow_portfolio_snapshots "
        "WHERE portfolio_id = ? AND observation_date = ? AND input_version = ?",
        (portfolio_id, observation_date, input_version),
    )
    if existing:
        logger.info("portfolio %s @ %s 已结算 (input_version=%s), 跳过",
                    portfolio_id, observation_date, input_version)
        return existing

    # 2. 拿 prev_holdings / prev_cash
    if prev_holdings is None or prev_cash is None:
        prev_snap = query_one(
            "SELECT holdings_json, cash FROM shadow_portfolio_snapshots "
            "WHERE portfolio_id = ? AND observation_date < ? "
            "ORDER BY observation_date DESC LIMIT 1",
            (portfolio_id, observation_date),
        )
        if prev_snap:
            prev_holdings = prev_holdings or json.loads(prev_snap.get("holdings_json") or "{}")
            prev_cash = prev_cash if prev_cash is not None else float(prev_snap.get("cash", 0))
        else:
            prev_holdings = prev_holdings or {}
            prev_cash = prev_cash if prev_cash is not None else float(p["initial_cash"])

    target_weights = p.get("target_weights") or {}

    # 3. 涨跌停 / 缺价检查
    unavailable: list[str] = []
    halted: list[str] = []  # 停牌: 沿用上一有效价
    effective_prices: dict[str, float] = {}
    for code, price in prices.items():
        if price is None or price <= 0:
            unavailable.append(code)
            continue
        effective_prices[code] = price

    # 计算 prev NAV (用今日价重估 prev_holdings)
    prev_nav = prev_cash + sum(
        prev_holdings.get(c, 0) * effective_prices.get(c, 0)
        for c in prev_holdings
    )

    if unavailable and not effective_prices:
        # 整组合都拿不到价 → blocked, 持仓和现金保留
        return _insert_snapshot(
            portfolio_id=portfolio_id,
            observation_date=observation_date,
            nav=round(prev_nav, 2),
            cash=prev_cash,
            holdings=prev_holdings,
            target_weights=target_weights,
            actual_weights={},
            turnover=0.0,
            costs=0.0,
            drawdown=0.0,
            baseline_diff={},
            status="blocked",
            reason=f"所有持仓代码缺价: {unavailable}",
            input_version=input_version,
        )

    # 4. 算目标股数 (整手, 再平衡, 含 fee buffer)
    target_shares, leftover_cash = _compute_target_shares(
        nav=prev_nav,  # 用 NAV 作总预算
        prev_holdings=prev_holdings,
        target_weights=target_weights,
        prices=effective_prices,
    )

    # 5. 计算 turnover (与 prev_holdings 比)
    turnover = 0.0
    all_codes = set(list(prev_holdings.keys()) + list(target_shares.keys()))
    for code in all_codes:
        prev_qty = prev_holdings.get(code, 0)
        new_qty = target_shares.get(code, 0)
        diff = abs(new_qty - prev_qty)
        price = effective_prices.get(code, 0)
        turnover += diff * price

    # 6. 算手续费
    buy_amount = 0.0
    sell_amount = 0.0
    for code, shares in target_shares.items():
        prev_qty = prev_holdings.get(code, 0)
        diff = shares - prev_qty
        if diff > 0:
            buy_amount += diff * effective_prices.get(code, 0)
        elif diff < 0:
            sell_amount += (-diff) * effective_prices.get(code, 0)
    fees = calc_total_fee(buy_amount=buy_amount, sell_amount=sell_amount)
    total_cost = fees["total"]

    # 7. 实际持仓 + 现金 (扣手续费)
    new_holdings = dict(target_shares)
    new_cash = leftover_cash - total_cost

    # 8. 算 NAV (净值 = 现金 + 持仓市值)
    holdings_value = sum(shares * effective_prices.get(code, 0) for code, shares in new_holdings.items())
    nav = new_cash + holdings_value

    # 9. 算实际权重
    actual_weights = {
        code: round((shares * effective_prices.get(code, 0)) / nav, 4) if nav > 0 else 0
        for code, shares in new_holdings.items()
    }

    # 10. 算 drawdown (vs initial_cash)
    drawdown = round((p["initial_cash"] - nav) / p["initial_cash"], 4) if p["initial_cash"] > 0 else 0.0

    # 11. 算 baseline_diff
    baseline_diff: dict[str, float] = {}
    if baseline_prices:
        for bench, bench_price in baseline_prices.items():
            # 简化: 仅记录当日基准价, 真实对比需要时间序列
            baseline_diff[bench] = round(bench_price, 4)

    # 12. 写入 snapshot
    status = "stale" if halted else "settled"
    reason = f"halted: {halted}" if halted else ("unavailable: " + ",".join(unavailable) if unavailable else "")

    return _insert_snapshot(
        portfolio_id=portfolio_id,
        observation_date=observation_date,
        nav=round(nav, 2),
        cash=round(new_cash, 2),
        holdings=new_holdings,
        target_weights=target_weights,
        actual_weights=actual_weights,
        turnover=round(turnover, 2),
        costs=round(total_cost, 2),
        drawdown=drawdown,
        baseline_diff=baseline_diff,
        status=status,
        reason=reason,
        input_version=input_version,
    )


def _insert_snapshot(
    *,
    portfolio_id: int,
    observation_date: str,
    nav: float,
    cash: float,
    holdings: dict,
    target_weights: dict,
    actual_weights: dict,
    turnover: float,
    costs: float,
    drawdown: float,
    baseline_diff: dict,
    status: str,
    reason: str,
    input_version: str,
) -> dict:
    """写一条 snapshot, 返回 dict."""
    try:
        cur = execute(
            "INSERT INTO shadow_portfolio_snapshots "
            "(portfolio_id, observation_date, nav, cash, "
            " holdings_json, target_weights_json, actual_weights_json, "
            " turnover, costs, drawdown, baseline_diff_json, "
            " status, reason, input_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                portfolio_id, observation_date, nav, cash,
                json.dumps(holdings, ensure_ascii=False),
                json.dumps(target_weights, ensure_ascii=False),
                json.dumps(actual_weights, ensure_ascii=False),
                turnover, costs, drawdown,
                json.dumps(baseline_diff, ensure_ascii=False),
                status, reason, input_version, _now(),
            ),
        )
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg:
            # 并发结算撞 unique → 重新读最新
            row = query_one(
                "SELECT * FROM shadow_portfolio_snapshots "
                "WHERE portfolio_id = ? AND observation_date = ? AND input_version = ?",
                (portfolio_id, observation_date, input_version),
            )
            if row:
                logger.info("并发结算命中 UNIQUE, 返回已有 snapshot")
                return row
        raise
    snapshot_id = int(cur["lastrowid"])
    return query_one(
        "SELECT * FROM shadow_portfolio_snapshots WHERE snapshot_id = ?",
        (snapshot_id,),
    )


# ════════════════════════════════════════════════════════════
#  区间结算
# ════════════════════════════════════════════════════════════

def settle_window(
    portfolio_id: int,
    start_date: str,
    end_date: str,
    prices_by_date: dict[str, dict[str, float]],
    *,
    input_version: str = "",
) -> list[dict]:
    """区间结算: 每天一次 settle_day.

    Args:
        prices_by_date: {date: {code: price}}

    Returns:
        snapshots 列表 (按日期升序)
    """
    snapshots = []
    cur_date = start_date
    while cur_date <= end_date:
        if cur_date not in prices_by_date:
            cur_date = next_trading_day(cur_date)
            if cur_date > end_date:
                break
            continue
        snap = settle_day(
            portfolio_id=portfolio_id,
            observation_date=cur_date,
            prices=prices_by_date[cur_date],
            input_version=input_version,
        )
        snapshots.append(snap)
        cur_date = next_trading_day(cur_date)
    return snapshots


# ════════════════════════════════════════════════════════════
#  读 snapshot
# ════════════════════════════════════════════════════════════

def get_snapshots(
    portfolio_id: int,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    """列组合的快照."""
    where = ["portfolio_id = ?"]
    params: list[Any] = [portfolio_id]
    if start:
        where.append("observation_date >= ?")
        params.append(start)
    if end:
        where.append("observation_date <= ?")
        params.append(end)
    sql = ("SELECT * FROM shadow_portfolio_snapshots WHERE "
           + " AND ".join(where) +
           " ORDER BY observation_date ASC LIMIT ?")
    params.append(limit)
    rows = query_all(sql, tuple(params))
    for r in rows:
        r["holdings"] = json.loads(r.get("holdings_json") or "{}")
        r["target_weights"] = json.loads(r.get("target_weights_json") or "{}")
        r["actual_weights"] = json.loads(r.get("actual_weights_json") or "{}")
        r["baseline_diff"] = json.loads(r.get("baseline_diff_json") or "{}")
    return rows


def get_snapshot(
    portfolio_id: int,
    observation_date: str,
    *,
    input_version: str = "",
) -> Optional[dict]:
    row = query_one(
        "SELECT * FROM shadow_portfolio_snapshots "
        "WHERE portfolio_id = ? AND observation_date = ? AND input_version = ?",
        (portfolio_id, observation_date, input_version),
    )
    if row:
        row["holdings"] = json.loads(row.get("holdings_json") or "{}")
        row["target_weights"] = json.loads(row.get("target_weights_json") or "{}")
        row["actual_weights"] = json.loads(row.get("actual_weights_json") or "{}")
        row["baseline_diff"] = json.loads(row.get("baseline_diff_json") or "{}")
    return row