"""持仓 vs 影子组合差异服务 (v4.1 1B.4)

公开 API:
  - get_holdings_vs_shadow(user_id, window_days=30) -> dict

返回:
  {
    "window_days": int,
    "shadow_portfolio_id": int | None,
    "shadow_portfolio_name": str | None,
    "snapshot_date": str | None,            # 最新 snapshot 的 observation_date
    "accumulating": bool,                   # snapshot_count < window_days 或无 active shadow
    "snapshot_count": int,
    "snapshot_target": int,
    "actual": { market_value, cost_basis, pnl, pnl_pct, today_pnl },
    "shadow": { nav, cash, market_value, delta_nav, delta_nav_pct },
    "diff_summary": {
      value_gap, value_gap_pct,
      position_overlap_count, actual_only_count, shadow_only_count
    },
    "rows": [
      { stock_code, stock_name,
        actual: { quantity, cost_price, last_price, market_value, pnl, pnl_pct, today_pnl, weight_pct },
        shadow: { quantity, cost_price, last_price, market_value, pnl, pnl_pct, today_pnl, weight_pct },
        delta_qty, delta_market_value, diff_side }, ...
    ]
  }

策略永远渲染 (DoD): 无 active shadow 时 shadow_portfolio_id=null,
shadow_portfolio_name=None, snapshot_count=0, accumulating=true.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from database import query_all
from services.holdings_service import get_holdings_with_pnl_snapshot

logger = logging.getLogger(__name__)


def _empty_response(window_days: int, *, message: str = "") -> dict:
    """无 active shadow 或积累严重不足时的兜底响应."""
    return {
        "window_days": window_days,
        "shadow_portfolio_id": None,
        "shadow_portfolio_name": None,
        "snapshot_date": None,
        "accumulating": True,
        "snapshot_count": 0,
        "snapshot_target": window_days,
        "actual": {
            "market_value": 0.0,
            "cost_basis": 0.0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "today_pnl": 0.0,
        },
        "shadow": {
            "nav": 0.0,
            "cash": 0.0,
            "market_value": 0.0,
            "delta_nav": 0.0,
            "delta_nav_pct": 0.0,
        },
        "diff_summary": {
            "value_gap": 0.0,
            "value_gap_pct": 0.0,
            "position_overlap_count": 0,
            "actual_only_count": 0,
            "shadow_only_count": 0,
        },
        "rows": [],
        "message": message,
    }


def _latest_active_shadow(user_id: int) -> dict | None:
    """取最近一个 status='active' 的 shadow portfolio."""
    try:
        from services.shadow_portfolio_service import list_portfolios
        rows = list_portfolios(owner_user_id=user_id)
    except Exception as e:
        logger.warning("list_portfolios failed: %s", e)
        return None
    active = [r for r in rows if r.get("status") == "active"]
    if not active:
        return None
    # list_portfolios ORDER BY portfolio_id DESC — 已是最新的
    return active[0]


def _load_snapshots(portfolio_id: int, limit: int) -> list[dict]:
    """拉取最近 N 个 snapshot (按 observation_date DESC)."""
    try:
        from services.shadow_portfolio_service import get_snapshots
        # get_snapshots 不支持 limit 倒序 — 改成直接 query
        rows = query_all(
            "SELECT * FROM shadow_portfolio_snapshots "
            "WHERE portfolio_id = ? "
            "ORDER BY observation_date DESC, snapshot_id DESC LIMIT ?",
            (portfolio_id, limit),
        )
        return rows or []
    except Exception as e:
        logger.warning("load_snapshots failed: %s", e)
        return []


def _empty_side() -> dict:
    return {
        "quantity": None,
        "cost_price": None,
        "last_price": None,
        "market_value": None,
        "pnl": None,
        "pnl_pct": None,
        "today_pnl": None,
        "weight_pct": None,
    }


def get_holdings_vs_shadow(
    user_id: int,
    window_days: int = 30,
) -> dict:
    """持仓 vs 影子组合差异 — 当前快照.

    Args:
        user_id: 当前用户
        window_days: 回看窗口天数 (7/30/90/180) — 仅决定 snapshot_target + accumulating 判断

    Returns:
        dict (见模块 docstring)
    """
    window_days = int(window_days)
    if window_days <= 0:
        window_days = 30

    # ── Step 1: 取最近 active shadow portfolio ──
    portfolio = _latest_active_shadow(user_id)
    if not portfolio:
        # 无 active → 仍然返回 actual 侧 PnL (让用户看到自己持仓)
        snap = get_holdings_with_pnl_snapshot(user_id)
        actual_summary = snap["summary"]
        return {
            **_empty_response(window_days, message="no_active_shadow"),
            "actual": {
                "market_value": actual_summary["total_value"],
                "cost_basis": actual_summary["total_cost"],
                "pnl": actual_summary["total_pnl"],
                "pnl_pct": actual_summary["total_pnl_pct"],
                "today_pnl": actual_summary["today_pnl"],
            },
        }

    portfolio_id = int(portfolio["portfolio_id"])
    portfolio_name = portfolio.get("name") or f"portfolio_{portfolio_id}"

    # ── Step 2: 拉取 snapshots ──
    snapshots = _load_snapshots(portfolio_id, window_days)
    snapshot_count = len(snapshots)
    accumulating = snapshot_count < window_days

    if not snapshots:
        snap = get_holdings_with_pnl_snapshot(user_id)
        actual_summary = snap["summary"]
        return {
            **_empty_response(window_days, message="no_snapshots_yet"),
            "shadow_portfolio_id": portfolio_id,
            "shadow_portfolio_name": portfolio_name,
            "actual": {
                "market_value": actual_summary["total_value"],
                "cost_basis": actual_summary["total_cost"],
                "pnl": actual_summary["total_pnl"],
                "pnl_pct": actual_summary["total_pnl_pct"],
                "today_pnl": actual_summary["today_pnl"],
            },
        }

    # snapshots 已按 DESC, [0] 是最新
    latest = snapshots[0]
    earliest_in_window = snapshots[-1]   # 窗口最旧

    latest_nav = float(latest.get("nav") or 0)
    latest_cash = float(latest.get("cash") or 0)
    latest_mv = latest_nav - latest_cash
    earliest_nav = float(earliest_in_window.get("nav") or latest_nav)
    delta_nav = latest_nav - earliest_nav
    delta_nav_pct = (delta_nav / earliest_nav * 100) if earliest_nav > 0 else 0.0

    # ── Step 3: 解析 holdings_json + actual_weights_json ──
    try:
        latest_holdings = json.loads(latest.get("holdings_json") or "{}")
        latest_weights = json.loads(latest.get("actual_weights_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        latest_holdings = {}
        latest_weights = {}

    # ── Step 4: actual 侧 ──
    snap = get_holdings_with_pnl_snapshot(user_id)
    actual_rows = snap["rows"]
    actual_summary = snap["summary"]
    actual_mv = actual_summary["total_value"]

    # ── Step 5: union 行集合 ──
    actual_codes = {h["stock_code"] for h in actual_rows}
    shadow_codes = set(latest_holdings.keys())
    all_codes = actual_codes | shadow_codes

    # 批量报价 (复用现有 vendor_router)
    quote_map: dict = {}
    if all_codes:
        try:
            from services.vendor_router import route
            quote_map = route("get_batch_quotes", codes=list(all_codes))
            if not isinstance(quote_map, dict):
                quote_map = {}
        except Exception:
            pass

    # ── Step 6: 行组装 ──
    rows: list[dict] = []
    position_overlap = 0
    actual_only = 0
    shadow_only = 0

    actual_by_code = {h["stock_code"]: h for h in actual_rows}

    for code in sorted(all_codes):
        a = actual_by_code.get(code)
        last_price = (quote_map.get(code, {}) or {}).get("price")

        actual_side = _empty_side()
        if a:
            qty = int(a.get("quantity") or 0)
            cost = float(a.get("cost_price") or 0)
            actual_side = {
                "quantity": qty,
                "cost_price": cost,
                "last_price": last_price,
                "market_value": round((last_price or 0) * qty, 2),
                "pnl": a.get("pnl"),
                "pnl_pct": a.get("pnl_pct"),
                "today_pnl": a.get("today_pnl"),
                "weight_pct": round((last_price or 0) * qty / actual_mv * 100, 2)
                              if (last_price and actual_mv > 0 and qty > 0) else None,
            }

        shadow_side = _empty_side()
        if code in latest_holdings:
            s_qty = int(latest_holdings.get(code) or 0)
            s_weight = float(latest_weights.get(code) or 0) * 100  # 0~1 → 0~100
            # implied market value 用 weight × nav (与影子口径一致)
            s_mv = round(s_weight / 100 * latest_nav, 2) if s_weight > 0 else 0.0
            shadow_side = {
                "quantity": s_qty,
                "cost_price": None,
                "last_price": last_price,
                "market_value": s_mv,
                "pnl": None,
                "pnl_pct": None,
                "today_pnl": None,
                "weight_pct": round(s_weight, 2) if s_weight > 0 else None,
            }

        # diff_side
        in_actual = a is not None
        in_shadow = code in latest_holdings
        if in_actual and in_shadow:
            diff_side = "both"
            position_overlap += 1
        elif in_actual:
            diff_side = "actual_only"
            actual_only += 1
        else:
            diff_side = "shadow_only"
            shadow_only += 1

        delta_qty = None
        delta_mv = None
        if in_actual and in_shadow:
            aq = actual_side["quantity"] or 0
            sq = shadow_side["quantity"] or 0
            delta_qty = aq - sq
            delta_mv = round((actual_side["market_value"] or 0) - (shadow_side["market_value"] or 0), 2)

        rows.append({
            "stock_code": code,
            "stock_name": (a or {}).get("stock_name") or code,
            "actual": actual_side,
            "shadow": shadow_side,
            "delta_qty": delta_qty,
            "delta_market_value": delta_mv,
            "diff_side": diff_side,
        })

    # 按 |delta_market_value| 降序 (None 排最后)
    def _delta_key(r: dict) -> tuple:
        dmv = r.get("delta_market_value")
        if dmv is None:
            return (1, 0.0)
        return (0, -abs(dmv))
    rows.sort(key=_delta_key)

    # ── Step 7: diff_summary ──
    value_gap = round(actual_mv - latest_mv, 2)
    value_gap_pct = round(value_gap / actual_mv * 100, 2) if actual_mv > 0 else 0.0

    return {
        "window_days": window_days,
        "shadow_portfolio_id": portfolio_id,
        "shadow_portfolio_name": portfolio_name,
        "snapshot_date": latest.get("observation_date"),
        "accumulating": accumulating,
        "snapshot_count": snapshot_count,
        "snapshot_target": window_days,
        "actual": {
            "market_value": actual_mv,
            "cost_basis": actual_summary["total_cost"],
            "pnl": actual_summary["total_pnl"],
            "pnl_pct": actual_summary["total_pnl_pct"],
            "today_pnl": actual_summary["today_pnl"],
        },
        "shadow": {
            "nav": round(latest_nav, 2),
            "cash": round(latest_cash, 2),
            "market_value": round(latest_mv, 2),
            "delta_nav": round(delta_nav, 2),
            "delta_nav_pct": round(delta_nav_pct, 2),
        },
        "diff_summary": {
            "value_gap": value_gap,
            "value_gap_pct": value_gap_pct,
            "position_overlap_count": position_overlap,
            "actual_only_count": actual_only,
            "shadow_only_count": shadow_only,
        },
        "rows": rows,
    }