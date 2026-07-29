"""持仓服务层 (v4.1 1B.4 新增 — 提取 holdings router 内嵌逻辑为可复用 helper)

公开 API:
  - get_holdings_with_pnl_snapshot(user_id, portfolio_id=None) -> dict
      返回结构 (与 router 端点一致):
        {
          "rows": [
            {stock_code, stock_name, quantity, cost_price, current_price,
             change_pct, market_value, pnl, pnl_pct, today_pnl, est_label,
             cost_amount, asset_type, market, ...},  # 原始 holdings 字段 + PnL 字段
          ],
          "summary": {
            "total_cost": float,
            "total_value": float,
            "total_pnl": float,
            "total_pnl_pct": float,
            "today_pnl": float,
            "count": int
          }
        }

Notes:
  - 调用方负责认证 (ContextVar)
  - 失败静默: 批量报价失败时 last_price/market_value 留 0
"""
from __future__ import annotations

from typing import Optional

from database import query_all


def _detect_asset_type(stock_code: str) -> str:
    """最小兜底 — 真实逻辑在 routers/holdings._detect_asset_type."""
    if not stock_code:
        return ""
    if stock_code.startswith(("5", "1")) and len(stock_code) == 6:
        return "fund"
    return "stock"


def _estimate_sell_fee(market_value: float, asset_type: str, stock_code: str = "") -> float:
    """预估卖出费用 (复用真实费率配置 — 同 routers/holdings._estimate_sell_fee).

    Stock: 佣金 max(费率*金额,最低) + 印花税 0.05% + 过户费 0.002%
    ETF:   佣金 max(费率*金额,最低),无印花税/过户费
    Fund:  0
    """
    if market_value <= 0:
        return 0.0
    at = (asset_type or "").strip().lower()
    if at in ("fund", "hk"):
        return 0.0

    try:
        from services.utils import get_fee_config, FeeConfig
        cfg = get_fee_config()
        if at == "etf":
            return round(max(market_value * cfg.commission_rate, cfg.commission_min), 2)
        commission = max(market_value * cfg.commission_rate, cfg.commission_min)
        stamp_tax = market_value * FeeConfig.stamp_tax_rate
        transfer_fee = market_value * FeeConfig.transfer_fee_rate
        return round(commission + stamp_tax + transfer_fee, 2)
    except Exception:
        # 配置不可用时兜底
        return round(max(market_value * 0.001, 5.0), 2)


def get_holdings_with_pnl_snapshot(
    user_id: int,
    portfolio_id: Optional[int] = None,
) -> dict:
    """持仓列表 + 实时盈亏 — 当前快照.

    Args:
        user_id: 当前用户 (由 router 注入,避免直接调 get_current_user_id)
        portfolio_id: 可选,过滤单组合

    Returns:
        { rows: [...], summary: {...} }
    """
    if portfolio_id:
        rows = query_all(
            "SELECT * FROM holdings WHERE user_id = ? AND portfolio_id = ? ORDER BY id DESC",
            (user_id, portfolio_id),
        )
    else:
        rows = query_all(
            "SELECT * FROM holdings WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )

    # ── 第一遍: 分类 + 收集需要批量报价的代码 ──
    stock_codes: list[str] = []
    fund_items: list[dict] = []
    stock_items: list[dict] = []

    for h in rows:
        item = dict(h)
        at = item.get("asset_type", "") or _detect_asset_type(item["stock_code"])
        if at == "fund":
            fund_items.append(item)
        else:
            stock_items.append(item)
            stock_codes.append(item["stock_code"])

    # ── 批量拉取股票/ETF 行情 ──
    quotes: dict = {}
    if stock_codes:
        try:
            from services.vendor_router import route
            quotes = route("get_batch_quotes", codes=stock_codes)
            if not isinstance(quotes, dict):
                quotes = {}
        except Exception:
            pass

    results: list[dict] = []
    total_cost = 0.0
    total_value = 0.0
    today_pnl_total = 0.0

    # ── 处理基金 (无 PnL, market_value 留 0) ──
    for item in fund_items:
        qty = item.get("quantity") or 0
        cost = item.get("cost_price") or 0
        item["current_price"] = None
        item["change_pct"] = None
        item["market_value"] = 0.0
        item["pnl"] = 0.0
        item["pnl_pct"] = 0.0
        item["today_pnl"] = 0.0
        item["est_label"] = ""
        item["cost_amount"] = cost * qty
        total_cost += item["cost_amount"]
        total_value += item["market_value"]
        today_pnl_total += item.get("today_pnl", 0)
        results.append(item)

    # ── 处理股票/ETF ──
    for item in stock_items:
        qty = item.get("quantity") or 0
        cost = item.get("cost_price") or 0
        code = item["stock_code"]
        item["current_price"] = None
        item["change_pct"] = None
        item["market_value"] = 0.0
        item["pnl"] = 0.0
        item["pnl_pct"] = 0.0
        item["today_pnl"] = 0.0
        item["est_label"] = ""
        q = quotes.get(code, {})
        if q and q.get("price"):
            item["stock_name"] = q.get("name") or item["stock_name"]
            item["current_price"] = q.get("price")
            item["change_pct"] = q.get("change_pct")
            item["market_value"] = round(q["price"] * qty, 2)
            gross_pnl = (q["price"] - cost) * qty
            sell_fee = _estimate_sell_fee(item["market_value"], item.get("asset_type", "stock"), code)
            item["pnl"] = round(gross_pnl - sell_fee, 2)
            item["pnl_pct"] = round(item["pnl"] / (cost * qty) * 100, 2) if cost > 0 and qty > 0 else 0
            change = q.get("change") or 0
            item["today_pnl"] = round(change * qty, 2) if change else 0
            item["cost_amount"] = cost * qty
        else:
            item["cost_amount"] = cost * qty
        total_cost += item.get("cost_amount", 0)
        total_value += item["market_value"]
        today_pnl_total += item.get("today_pnl", 0)
        results.append(item)

    total_pnl = sum(r.get("pnl", 0) for r in results)
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0

    return {
        "rows": results,
        "summary": {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": total_pnl_pct,
            "today_pnl": round(today_pnl_total, 2),
            "count": len(results),
        },
    }