"""股市数据路由"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute, execute_many
from services.news_service import get_matched_news, fetch_news_jsonp, _industry_keyword
from services.ai_service import ai_chat
from services.technical import get_indicators as calc_indicators
from services.utils import run_curl, get_market, detect_asset_type, get_fund_nav, calc_xirr

router = APIRouter()


# ==================== 持仓 ====================

@router.get("/holdings")
def get_holdings(portfolio_id: int | None = None):
    if portfolio_id:
        return query_all("SELECT * FROM holdings WHERE user_id = 1 AND portfolio_id = ? ORDER BY id DESC", (portfolio_id,))
    return query_all("SELECT * FROM holdings WHERE user_id = 1 ORDER BY id DESC")


class HoldingBody(BaseModel):
    stock_code: str
    stock_name: str
    market: str = "SH"
    asset_type: str = ""      # stock / etf / fund，空则自动识别
    quantity: int = 0         # 股数(股票/ETF) 或 份数(基金)
    cost_price: float = 0.0   # 成本价(股票/ETF) 或 成本净值(基金)
    shares: float | None = None  # 基金份额，数量=份数时等同 quantity
    portfolio_id: int | None = None


@router.post("/holdings")
def add_holding(body: HoldingBody):
    at = body.asset_type or detect_asset_type(body.stock_code)
    qty = body.quantity
    cost = body.cost_price
    if body.shares is not None:
        qty = int(body.shares) if at != "fund" else body.shares
    result = execute(
        """INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price, shares, portfolio_id)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (body.stock_code, body.stock_name, body.market, at, qty, cost, body.shares, body.portfolio_id),
    )
    holding_id = result["lastrowid"]
    # 同步创建初始买入交易记录；失败则删除持仓回滚
    amount = round(qty * cost, 2)
    try:
        execute(
            """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, traded_at, note)
               VALUES (1, ?, ?, ?, 'buy', ?, ?, ?, date('now','localtime'), '初始建仓')""",
            (body.stock_code, body.stock_name, at, cost, qty, amount),
        )
    except Exception:
        execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        raise HTTPException(500, "持仓创建失败，请重试")

    return {"id": holding_id, "message": "添加成功", "asset_type": at}


@router.put("/holdings/{holding_id}")
def update_holding(holding_id: int, body: HoldingBody):
    at = body.asset_type or detect_asset_type(body.stock_code)
    execute(
        """UPDATE holdings SET stock_code=?, stock_name=?, market=?, asset_type=?, quantity=?, cost_price=?, shares=?, portfolio_id=?
           WHERE id=? AND user_id=1""",
        (body.stock_code, body.stock_name, body.market, at, body.quantity, body.cost_price, body.shares, body.portfolio_id, holding_id),
    )
    return {"message": "已更新"}


@router.delete("/holdings/{holding_id}")
def delete_holding(holding_id: int):
    execute("DELETE FROM holdings WHERE id = ? AND user_id = 1", (holding_id,))
    return {"message": "已删除"}


class JournalBody(BaseModel):
    journal: str = ""


@router.put("/holdings/{holding_id}/journal")
def update_journal(holding_id: int, body: JournalBody):
    h = query_one("SELECT id FROM holdings WHERE id = ? AND user_id = 1", (holding_id,))
    if not h:
        raise HTTPException(404, "持仓不存在")
    execute("UPDATE holdings SET journal = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (body.journal, holding_id))
    return {"message": "已保存", "journal": body.journal}


@router.get("/holdings/with-pnl")
def get_holdings_with_pnl(portfolio_id: int | None = None):
    """持仓列表 + 实时盈亏（按资产类型分别计算）"""
    if portfolio_id:
        rows = query_all("SELECT * FROM holdings WHERE user_id = 1 AND portfolio_id = ? ORDER BY id DESC", (portfolio_id,))
    else:
        rows = query_all("SELECT * FROM holdings WHERE user_id = 1 ORDER BY id DESC")

    results = []
    total_cost = 0.0
    total_value = 0.0
    today_pnl = 0.0

    for h in rows:
        item = dict(h)
        asset_type = item.get("asset_type", "") or detect_asset_type(item["stock_code"])
        qty = item["quantity"] or 0
        cost = item["cost_price"] or 0

        # 默认值
        item["current_price"] = None
        item["change_pct"] = None
        item["market_value"] = 0.0
        item["pnl"] = 0.0
        item["pnl_pct"] = 0.0
        item["today_pnl"] = 0.0
        item["est_label"] = ""  # "估算" 标签（基金用）

        if asset_type == "fund":
            # 普通基金：用官方净值（非估算）
            nav_data = get_fund_nav(item["stock_code"])
            if nav_data:
                item["stock_name"] = item["stock_name"] or nav_data["name"]
                item["current_price"] = nav_data["nav"]
                item["est_nav"] = nav_data["est_nav"]
                item["change_pct"] = nav_data["est_change_pct"]
                item["est_label"] = nav_data["nav_date"]
                shares = item.get("shares") or qty
                item["market_value"] = nav_data["nav"] * shares
                item["pnl"] = (nav_data["nav"] - cost) * shares
                item["pnl_pct"] = (nav_data["nav"] / cost - 1) * 100 if cost > 0 else 0
                item["today_pnl"] = nav_data["nav"] * shares * nav_data["est_change_pct"] / 100
                item["cost_amount"] = cost * shares
        else:
            # 股票 / ETF：查东方财富实时行情
            mkt = get_market(item["stock_code"])
            q = _cached_quote(item["stock_code"], mkt)
            if q and "error" not in q:
                item["stock_name"] = item["stock_name"] or q.get("name", "")
                item["current_price"] = q.get("price")
                item["change_pct"] = q.get("change_pct")
                item["market_value"] = (q.get("price") or cost) * qty
                item["pnl"] = ((q.get("price") or cost) - cost) * qty
                item["pnl_pct"] = (q.get("price") / cost - 1) * 100 if cost > 0 else 0
                change = q.get("change") or 0
                item["today_pnl"] = change * qty if change else 0
                item["cost_amount"] = cost * qty
            else:
                item["cost_amount"] = cost * qty

        total_cost += item.get("cost_amount", 0)
        total_value += item["market_value"]
        today_pnl += item.get("today_pnl", 0)

        results.append(item)

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

    return {
        "holdings": results,
        "summary": {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "today_pnl": round(today_pnl, 2),
        },
    }


@router.get("/fund-nav/{code}")
def get_fund_nav_endpoint(code: str):
    """获取基金净值（天天基金）"""
    nav = get_fund_nav(code)
    if not nav:
        raise HTTPException(500, "无法获取基金净值")
    return nav


@router.get("/holdings/xirr")
def get_xirr():
    """按持仓计算 XIRR 年化收益率（基于所有买入交易+当前市值）"""
    buys = query_all(
        """SELECT stock_code, stock_name, amount, traded_at FROM transactions
           WHERE user_id = 1 AND direction = 'buy' ORDER BY traded_at ASC"""
    )
    if not buys:
        return {"total_xirr": None, "by_holding": []}

    # 获取当前市值（复用 get_holdings_with_pnl 的计算逻辑）
    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1")
    market_values = {}
    for h in holdings:
        at = h.get("asset_type") or detect_asset_type(h["stock_code"])
        if at == "fund":
            nav_data = get_fund_nav(h["stock_code"])
            shares = h.get("shares") or h["quantity"] or 0
            if nav_data and nav_data.get("est_nav", 0) > 0:
                market_values[h["stock_code"]] = round(nav_data["est_nav"] * shares, 2)
            else:
                market_values[h["stock_code"]] = round(h["cost_price"] * shares, 2)
        else:
            qty = h["quantity"] or 0
            cost = h["cost_price"] or 0
            mkt = get_market(h["stock_code"])
            q = _cached_quote(h["stock_code"], mkt)
            if q and "error" not in q and q.get("price"):
                market_values[h["stock_code"]] = round(q["price"] * qty, 2)
            else:
                market_values[h["stock_code"]] = round(cost * qty, 2)

    # 按 stock_code 分组计算（只算有持仓的）
    by_holding = []
    held_codes = set(market_values.keys())
    stock_codes = sorted(set(b["stock_code"] for b in buys) & held_codes)

    for code in stock_codes:
        code_buys = [b for b in buys if b["stock_code"] == code]
        name = code_buys[-1]["stock_name"] or code
        flows = [(b["traded_at"], -b["amount"]) for b in code_buys]
        flows.append((datetime.now().strftime("%Y-%m-%d"), market_values[code]))
        xirr = calc_xirr(flows)
        by_holding.append({
            "stock_code": code,
            "stock_name": name,
            "xirr": xirr,
            "cash_flows_count": len(code_buys),
        })

    # 总体 XIRR：只算有持仓的买入 + 总市值
    total_mv = sum(market_values.values())
    total_flows = [(b["traded_at"], -b["amount"]) for b in buys if b["stock_code"] in held_codes]
    if total_mv > 0:
        total_flows.append((datetime.now().strftime("%Y-%m-%d"), total_mv))
        total_xirr = calc_xirr(total_flows)
    else:
        total_xirr = None

    return {"total_xirr": total_xirr, "by_holding": by_holding}


# ==================== 追加买入（批次管理） ====================

class AddLotBody(BaseModel):
    traded_at: str         # ISO date "2026-05-23"
    amount: float = 0      # 投入金额(元)，基金用
    nav: float | None = None  # 净值，基金用；不传则自动获取
    quantity: float = 0    # 买入数量(股/份)，股票用
    price: float = 0       # 买入单价，股票用
    note: str = ""


@router.get("/holdings/{holding_id}/lots")
def get_holding_lots(holding_id: int):
    """获取某持仓的所有买入批次（从 transactions 表读取）"""
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = 1", (holding_id,))
    if not h:
        raise HTTPException(404, "持仓不存在")

    at = h.get("asset_type") or detect_asset_type(h["stock_code"])
    is_fund = (at == "fund")
    lots = []

    txs = query_all(
        """SELECT * FROM transactions
           WHERE user_id = 1 AND stock_code = ? AND direction = 'buy'
           ORDER BY traded_at ASC""",
        (h["stock_code"],),
    )
    # 如果没有交易记录（旧数据），把当前持仓作为首条
    if not txs:
        init_qty = h.get("shares") or h["quantity"]
        init_cost = h["cost_price"]
        lots.append({
            "id": None,
            "traded_at": (h.get("created_at") or "")[:10],
            "amount": round(init_qty * init_cost, 2),
            "price": init_cost,
            "quantity": round(init_qty, 4) if is_fund else init_qty,
            "note": "初始持仓（待同步）",
        })
    else:
        for t in txs:
            lots.append({
                "id": t["id"],
                "traded_at": (t.get("traded_at") or "")[:10],
                "amount": t["amount"],
                "price": t["price"],
                "quantity": round(t["quantity"], 4) if is_fund else t["quantity"],
                "note": t.get("note", ""),
            })
        # 兜底：如果所有 tx quantity 总和与持仓差异大，展示当前持仓聚合行
        tx_total_qty = sum(t["quantity"] for t in txs)
        holdings_qty = h.get("shares") or h["quantity"]
        if abs(tx_total_qty - holdings_qty) > 0.1:
            lots.append({
                "id": None,
                "traded_at": "汇总",
                "amount": round(holdings_qty * h["cost_price"], 2),
                "price": h["cost_price"],
                "quantity": round(holdings_qty, 4) if is_fund else holdings_qty,
                "note": "当前持仓汇总",
            })

    return {
        "holding_id": holding_id,
        "stock_name": h["stock_name"],
        "asset_type": at,
        "current_cost": h["cost_price"],
        "current_quantity": h.get("shares") or h["quantity"],
        "lots": lots,
    }


@router.post("/holdings/{holding_id}/add-lot")
def add_lot(holding_id: int, body: AddLotBody):
    """追加一笔买入，更新持仓加权成本"""
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = 1", (holding_id,))
    if not h:
        raise HTTPException(404, "持仓不存在")

    at = h.get("asset_type") or detect_asset_type(h["stock_code"])

    if at == "fund":
        # 基金：金额 ÷ 净值 = 份额
        if body.amount <= 0:
            raise HTTPException(400, "请填写有效的投入金额")
        price = body.nav
        if price is None or price <= 0:
            nav_data = get_fund_nav(h["stock_code"])
            if nav_data and nav_data.get("est_nav", 0) > 0:
                price = nav_data["est_nav"]
        if price is None or price <= 0:
            raise HTTPException(400, "无法获取基金净值，请手动输入")
        qty = round(body.amount / price, 4)
        amount = body.amount
    else:
        # 股票/ETF：数量 × 单价 = 金额
        if body.quantity <= 0 or body.price <= 0:
            raise HTTPException(400, "请填写有效的买入数量和单价")
        qty = body.quantity
        price = body.price
        amount = round(qty * price, 2)

    # 创建买入交易记录
    tx_result = execute(
        """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, traded_at, note)
           VALUES (1, ?, ?, ?, 'buy', ?, ?, ?, ?, ?)""",
        (h["stock_code"], h["stock_name"], at, price, qty, amount, body.traded_at, body.note or "追加买入"),
    )

    # 更新持仓加权成本
    old_shares = h.get("shares") or h["quantity"] or 0
    old_cost = h["cost_price"] or 0
    old_total = old_shares * old_cost
    new_total = old_total + amount
    new_shares = old_shares + qty
    new_cost = round(new_total / new_shares, 4) if new_shares > 0 else 0

    if at == "fund":
        execute(
            "UPDATE holdings SET quantity = ?, cost_price = ?, shares = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (round(new_shares, 4), new_cost, round(new_shares, 4), holding_id),
        )
    else:
        execute(
            "UPDATE holdings SET quantity = ?, cost_price = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (int(new_shares), new_cost, holding_id),
        )

    return {
        "message": "追加成功",
        "tx_id": tx_result["lastrowid"],
        "added_shares": round(qty, 4) if at == "fund" else int(qty),
        "price": price,
        "new_cost_price": new_cost,
        "new_quantity": round(new_shares, 4) if at == "fund" else int(new_shares),
    }


# ==================== 历史数据导入 ====================

class ImportLotItem(BaseModel):
    traded_at: str       # "2024-01-05"
    amount: float         # 投入金额(元)
    nav: float            # 当日净值


class ImportLotsBody(BaseModel):
    lots: list[ImportLotItem]
    note: str = "历史数据导入"


@router.post("/holdings/{holding_id}/import-lots")
def import_lots(holding_id: int, body: ImportLotsBody):
    """批量导入历史买入记录，更新加权成本"""
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = 1", (holding_id,))
    if not h:
        raise HTTPException(404, "持仓不存在")

    if not body.lots:
        raise HTTPException(400, "没有可导入的记录")

    at = h.get("asset_type") or detect_asset_type(h["stock_code"])
    is_fund = (at == "fund")

    # 逐行校验并计算
    parsed = []
    errors = []
    for i, lot in enumerate(body.lots):
        line_no = i + 1
        if not lot.traded_at or not lot.traded_at.strip():
            errors.append(f"第{line_no}行: 日期不能为空")
            continue
        if lot.amount <= 0:
            errors.append(f"第{line_no}行: 金额必须大于0")
            continue
        if lot.nav <= 0:
            errors.append(f"第{line_no}行: 净值必须大于0")
            continue

        if is_fund:
            qty = round(lot.amount / lot.nav, 4)
            amount = lot.amount
            price = lot.nav
        else:
            qty = lot.amount  # 对股票来说 amount 字段是数量
            price = lot.nav   # nav 字段是单价
            amount = round(qty * price, 2)

        parsed.append({
            "traded_at": lot.traded_at.strip(),
            "price": price,
            "quantity": qty,
            "amount": amount,
        })

    if errors:
        raise HTTPException(400, "; ".join(errors))

    if not parsed:
        raise HTTPException(400, "没有有效的记录可导入")

    # 汇总
    total_amount = sum(p["amount"] for p in parsed)
    total_shares = sum(p["quantity"] for p in parsed)

    # 加权成本计算
    old_shares = h.get("shares") or h["quantity"] or 0
    old_cost = h["cost_price"] or 0
    old_total = old_shares * old_cost
    new_total = old_total + total_amount
    new_shares = old_shares + total_shares
    new_cost = round(new_total / new_shares, 4) if new_shares > 0 else 0

    # 原子批量写入
    statements = []
    for p in parsed:
        statements.append((
            """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, traded_at, note)
               VALUES (1, ?, ?, ?, 'buy', ?, ?, ?, ?, ?)""",
            (h["stock_code"], h["stock_name"], at, p["price"], p["quantity"], p["amount"], p["traded_at"], body.note),
        ))

    if is_fund:
        statements.append((
            "UPDATE holdings SET quantity = ?, cost_price = ?, shares = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (round(new_shares, 4), new_cost, round(new_shares, 4), holding_id),
        ))
    else:
        statements.append((
            "UPDATE holdings SET quantity = ?, cost_price = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (int(new_shares), new_cost, holding_id),
        ))

    execute_many(statements)

    return {
        "message": f"成功导入 {len(parsed)} 笔记录",
        "imported_count": len(parsed),
        "total_amount": round(total_amount, 2),
        "total_shares": round(total_shares, 4),
        "new_cost_price": new_cost,
        "new_quantity": round(new_shares, 4) if is_fund else int(new_shares),
    }


# ==================== 组合管理 ====================

class PortfolioBody(BaseModel):
    name: str
    type: str = "long"  # long / short / experiment


@router.get("/portfolios")
def get_portfolios():
    return query_all("SELECT * FROM portfolios WHERE user_id = 1 ORDER BY id")


@router.post("/portfolios")
def add_portfolio(body: PortfolioBody):
    result = execute(
        "INSERT INTO portfolios (user_id, name, type) VALUES (1, ?, ?)",
        (body.name, body.type),
    )
    return {"id": result["lastrowid"], "message": "创建成功"}


@router.delete("/portfolios/{pf_id}")
def delete_portfolio(pf_id: int):
    # 将该组合下的持仓设为未分类
    execute("UPDATE holdings SET portfolio_id = NULL WHERE portfolio_id = ? AND user_id = 1", (pf_id,))
    execute("DELETE FROM portfolios WHERE id = ? AND user_id = 1", (pf_id,))
    return {"message": "已删除"}


# ==================== 自选股 ====================

@router.get("/watchlist")
def get_watchlist():
    return query_all("SELECT * FROM watchlist WHERE user_id = 1 ORDER BY added_at DESC")


class WatchlistBody(BaseModel):
    stock_code: str
    stock_name: str
    market: str = "SH"
    asset_type: str = ""


@router.post("/watchlist")
def add_watchlist(body: WatchlistBody):
    at = body.asset_type or detect_asset_type(body.stock_code)
    result = execute(
        "INSERT OR IGNORE INTO watchlist (user_id, stock_code, stock_name, market, asset_type) VALUES (1, ?, ?, ?, ?)",
        (body.stock_code, body.stock_name, body.market, at),
    )
    return {"id": result["lastrowid"], "message": "添加成功"}


@router.delete("/watchlist/{item_id}")
def delete_watchlist(item_id: int):
    execute("DELETE FROM watchlist WHERE id = ? AND user_id = 1", (item_id,))
    return {"message": "已移除"}


# ==================== 交易记录 ====================

@router.get("/transactions")
def get_transactions():
    return query_all(
        "SELECT * FROM transactions WHERE user_id = 1 ORDER BY traded_at DESC"
    )


class TransactionBody(BaseModel):
    stock_code: str
    stock_name: str
    asset_type: str = ""
    direction: str
    price: float
    quantity: int
    traded_at: str
    note: str = ""


@router.post("/transactions")
def add_transaction(body: TransactionBody):
    amount = body.price * body.quantity
    at = body.asset_type or detect_asset_type(body.stock_code)
    result = execute(
        """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, traded_at, note)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (body.stock_code, body.stock_name, at, body.direction, body.price, body.quantity, amount, body.traded_at, body.note),
    )
    return {"id": result["lastrowid"], "message": "添加成功"}


def _recalc_holding_for_code(stock_code: str):
    """根据某代码的所有买入交易重新计算持仓成本和数量"""
    h = query_one(
        "SELECT * FROM holdings WHERE user_id = 1 AND stock_code = ?", (stock_code,)
    )
    if not h:
        return None

    at = h.get("asset_type") or detect_asset_type(stock_code)
    is_fund = (at == "fund")

    buys = query_all(
        """SELECT * FROM transactions
           WHERE user_id = 1 AND stock_code = ? AND direction = 'buy'
           ORDER BY traded_at ASC""",
        (stock_code,),
    )

    if not buys:
        # 所有买入记录都被删了，保留原成本不变（用户需手动处理）
        return {"holding_id": h["id"], "stock_code": stock_code, "quantity": h["quantity"], "cost_price": h["cost_price"]}

    total_amount = sum(t["amount"] for t in buys)
    total_shares = sum(t["quantity"] for t in buys)
    new_cost = round(total_amount / total_shares, 4) if total_shares > 0 else 0

    if is_fund:
        execute(
            "UPDATE holdings SET quantity = ?, cost_price = ?, shares = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (round(total_shares, 4), new_cost, round(total_shares, 4), h["id"]),
        )
    else:
        execute(
            "UPDATE holdings SET quantity = ?, cost_price = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (int(total_shares), new_cost, h["id"]),
        )

    return {"holding_id": h["id"], "stock_code": stock_code, "quantity": total_shares, "cost_price": new_cost}


@router.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    """删除交易记录，并重新计算对应持仓成本"""
    tx = query_one("SELECT * FROM transactions WHERE id = ? AND user_id = 1", (tx_id,))
    if not tx:
        raise HTTPException(404, "交易记录不存在")

    stock_code = tx["stock_code"]
    direction = tx["direction"]

    execute("DELETE FROM transactions WHERE id = ? AND user_id = 1", (tx_id,))

    holding_result = None
    if direction == "buy":
        holding_result = _recalc_holding_for_code(stock_code)

    return {
        "message": "已删除",
        "deleted_id": tx_id,
        "holding_updated": holding_result is not None,
        "holding": holding_result,
    }


class UpdateTransactionBody(BaseModel):
    traded_at: str | None = None
    price: float | None = None
    quantity: float | None = None
    note: str | None = None


@router.put("/transactions/{tx_id}")
def update_transaction(tx_id: int, body: UpdateTransactionBody):
    """更新交易记录，并重新计算对应持仓成本"""
    tx = query_one("SELECT * FROM transactions WHERE id = ? AND user_id = 1", (tx_id,))
    if not tx:
        raise HTTPException(404, "交易记录不存在")

    # 合并：传了的字段更新，没传的保留原值
    traded_at = body.traded_at if body.traded_at is not None else tx["traded_at"]
    price = body.price if body.price is not None else tx["price"]
    quantity = body.quantity if body.quantity is not None else tx["quantity"]
    note = body.note if body.note is not None else tx["note"]

    amount = round(price * quantity, 2)

    execute(
        """UPDATE transactions SET traded_at = ?, price = ?, quantity = ?, amount = ?, note = ?
           WHERE id = ? AND user_id = 1""",
        (traded_at, price, quantity, amount, note, tx_id),
    )

    holding_result = None
    if tx["direction"] == "buy":
        holding_result = _recalc_holding_for_code(tx["stock_code"])

    return {
        "message": "已更新",
        "updated_id": tx_id,
        "holding_updated": holding_result is not None,
        "holding": holding_result,
    }


# ==================== 实时行情 ====================

_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}  # key -> (expire_time, result)
_CACHE_TTL = 5.0  # 秒


def _cache_key(code: str, market: str | None = None) -> str:
    return f"{code}:{market or ''}"


def _cached_quote(code: str, market: str | None = None) -> dict:
    """带缓存的行情获取"""
    key = _cache_key(code, market)
    entry = _QUOTE_CACHE.get(key)
    if entry and time.time() < entry[0]:
        return entry[1]
    result = _fetch_quote_sync(code, market)
    _QUOTE_CACHE[key] = (time.time() + _CACHE_TTL, result)
    return result


def _fetch_quote_sync(code: str, market: str | None = None) -> dict:
    """获取单只股票实时行情（AKShare 优先，东方财富兜底）"""
    # 优先 AKShare
    try:
        from services.akshare_adapter import get_quote
        q = get_quote(code)
        if q and q.get("price"):
            return {
                "code": q["code"],
                "name": q.get("name", ""),
                "price": q["price"],
                "change": q["change"],
                "change_pct": q["change_pct"],
                "volume": q.get("volume"),
                "high": q.get("high"),
                "low": q.get("low"),
            }
    except Exception:
        pass

    # 兜底：东方财富 API
    try:
        if market is None:
            market = get_market(code)
        secid = f"{market}.{code}"
        url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secid}&fields=f2,f3,f4,f5,f12,f14,f15,f16"
        data = json.loads(run_curl(url))
        diff = (data.get("data") or {}).get("diff") or []
        if diff:
            d = diff[0]
            return {
                "code": d.get("f12", code),
                "name": d.get("f14", ""),
                "price": d.get("f2"),
                "change": d.get("f4"),
                "change_pct": d.get("f3"),
                "volume": d.get("f5"),
                "high": d.get("f15"),
                "low": d.get("f16"),
            }
    except Exception as e:
        print(f"[Quote Error] {code}: {e}")
    return {"code": code, "error": "获取失败"}


@router.get("/quote/{code}")
def get_quote(code: str):
    """单只股票/基金实时行情"""
    at = detect_asset_type(code)
    if at == "fund":
        nav = get_fund_nav(code)
        if nav:
            return {
                "code": code, "name": nav.get("name", ""),
                "price": nav.get("nav"), "est_nav": nav.get("est_nav"),
                "change_pct": nav.get("est_change_pct"),
                "nav_date": nav.get("nav_date"), "asset_type": "fund",
            }
        raise HTTPException(500, "获取基金净值失败")
    result = _cached_quote(code)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


@router.get("/lookup/{code}")
def lookup(code: str):
    """输入代码自动查询：识别类型并返回名称、价格、涨跌幅"""
    at = detect_asset_type(code)

    # Try the most likely data source first, then fall back to the other
    try_quote_first = at in ("stock", "etf")

    q = _cached_quote(code) if try_quote_first else None
    nav = None if try_quote_first else get_fund_nav(code)

    if q and "error" not in q:
        return {"code": code, "name": q.get("name", ""), "type": at,
                "price": q.get("price"), "change_pct": q.get("change_pct")}
    if nav:
        return {"code": code, "name": nav.get("name", ""), "type": "fund",
                "price": nav.get("nav"), "change_pct": nav.get("est_change_pct")}

    # Fallback: try the other source
    if try_quote_first:
        nav = get_fund_nav(code)
        if nav:
            return {"code": code, "name": nav.get("name", ""), "type": "fund",
                    "price": nav.get("nav"), "change_pct": nav.get("est_change_pct")}
    else:
        q = _cached_quote(code)
        if q and "error" not in q:
            return {"code": code, "name": q.get("name", ""),
                    "type": "etf" if code.startswith(("51", "159", "588", "56")) else "stock",
                    "price": q.get("price"), "change_pct": q.get("change_pct")}

    raise HTTPException(404, f"未找到 {code} 的信息")


class BatchQuoteBody(BaseModel):
    codes: list[str]
    markets: list[str | None] | None = None  # 可选，与 codes 一一对应
    asset_types: list[str] | None = None  # 可选，与 codes 一一对应，用于区分基金


@router.post("/quotes")
def get_quotes_batch(body: BatchQuoteBody):
    """批量获取实时行情（股票走东方财富，基金走天天基金估值）"""
    results = []
    for i, code in enumerate(body.codes):
        m = body.markets[i] if body.markets and i < len(body.markets) else None
        at = body.asset_types[i] if body.asset_types and i < len(body.asset_types) else ""
        if not at:
            at = detect_asset_type(code)

        if at == "fund":
            # 基金：走天天基金估值
            key = _cache_key(code, "fund")
            entry = _QUOTE_CACHE.get(key)
            if entry and time.time() < entry[0]:
                results.append(entry[1])
            else:
                nav = get_fund_nav(code)
                if nav:
                    result = {
                        "code": code,
                        "name": nav.get("name", ""),
                        "price": nav.get("nav"),
                        "est_nav": nav.get("est_nav"),
                        "change": round(nav.get("est_nav", 0) - nav.get("nav", 0), 4),
                        "change_pct": nav.get("est_change_pct"),
                        "high": None,
                        "low": None,
                        "volume": None,
                        "asset_type": "fund",
                        "nav_date": nav.get("nav_date"),
                    }
                else:
                    result = {"code": code, "error": "获取基金净值失败"}
                _QUOTE_CACHE[key] = (time.time() + 60, result)  # 基金缓存 60 秒
                results.append(result)
                time.sleep(0.2)  # 基金 API 限速
        else:
            # 股票/ETF：走东方财富行情
            key = _cache_key(code, m)
            entry = _QUOTE_CACHE.get(key)
            if entry and time.time() < entry[0]:
                results.append(entry[1])
            else:
                results.append(_fetch_quote_sync(code, m or None))
                _QUOTE_CACHE[key] = (time.time() + _CACHE_TTL, results[-1])
                time.sleep(0.3)
    return results


# ==================== 全球指数 ====================

_GLOBAL_INDICES = [
    {"code": "1.000001",  "name": "上证指数",       "region": "中国"},
    {"code": "0.399001",  "name": "深证成指",       "region": "中国"},
    {"code": "0.399006",  "name": "创业板指",       "region": "中国"},
    {"code": "100.HSI",   "name": "恒生指数",       "region": "中国香港"},
    {"code": "100.TWII",  "name": "台湾加权",       "region": "中国台湾"},
    {"code": "100.NDX",   "name": "纳斯达克",       "region": "美国"},
    {"code": "100.SPX",   "name": "标普500",        "region": "美国"},
    {"code": "100.DJIA",  "name": "道琼斯",         "region": "美国"},
    {"code": "100.N225",  "name": "日经225",        "region": "日本"},
    {"code": "100.KS11",  "name": "韩国KOSPI",      "region": "韩国"},
    {"code": "100.FTSE",  "name": "英国富时100",    "region": "英国"},
    {"code": "100.GDAXI", "name": "德国DAX30",      "region": "德国"},
    {"code": "100.SENSEX","name": "印度SENSEX",     "region": "印度"},
    {"code": "100.BVSP",  "name": "巴西BOVESPA",    "region": "巴西"},
    {"code": "100.STI",   "name": "新加坡海峡时报", "region": "新加坡"},
]

_INDEX_CACHE_TTL = 5.0
_INDEX_BATCH_EXPIRY = 0.0
_INDEX_CACHED_DATA: list[dict] = []


@router.get("/indices/global")
def get_global_indices():
    """获取全球主要指数行情（AKShare 优先，东方财富 ulist 兜底）"""
    global _INDEX_BATCH_EXPIRY, _INDEX_CACHED_DATA
    now = time.time()
    if _INDEX_CACHED_DATA and now < _INDEX_BATCH_EXPIRY:
        return _INDEX_CACHED_DATA

    results = []

    # 优先 AKShare
    try:
        from services.akshare_adapter import get_global_indices as ak_indices
        results = ak_indices()
        if results:
            _INDEX_CACHED_DATA = results
            _INDEX_BATCH_EXPIRY = now + _INDEX_CACHE_TTL
            return results
    except Exception as e:
        print(f"[AKShare Index Error]: {e}")

    # 兜底：东方财富 ulist API
    try:
        secids = ",".join([idx["code"] for idx in _GLOBAL_INDICES])
        url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f14"
        data = json.loads(run_curl(url))
        diff_list = data.get("data", {}).get("diff", [])
        code_map = {idx["code"].split(".")[-1]: idx for idx in _GLOBAL_INDICES}
        for d in diff_list:
            code = d.get("f12", "")
            info = code_map.get(code)
            if info:
                results.append({
                    "code": code,
                    "name": info["name"],
                    "region": info["region"],
                    "price": d.get("f2"),
                    "change": d.get("f4"),
                    "change_pct": d.get("f3"),
                })
    except Exception as e:
        print(f"[Global Index Error]: {e}")
        return _INDEX_CACHED_DATA or []

    order_map = {idx["code"].split(".")[-1]: i for i, idx in enumerate(_GLOBAL_INDICES)}
    results.sort(key=lambda x: order_map.get(x["code"], 99))
    _INDEX_CACHED_DATA = results
    _INDEX_BATCH_EXPIRY = now + _INDEX_CACHE_TTL
    return results


# ==================== 技术指标 ====================

@router.get("/indicators/{code}")
def get_technical_indicators(code: str):
    """获取技术指标：MA/MACD/KDJ/RSI + 简要信号"""
    result = calc_indicators(code)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


class IndicatorInterpretBody(BaseModel):
    provider: str = ""
    apiKey: str = ""
    model: str = ""


@router.post("/indicators/{code}/interpret")
async def interpret_indicators(code: str, body: IndicatorInterpretBody):
    """AI 解读技术指标"""
    if not body.apiKey:
        raise HTTPException(400, "请先配置 API Key")

    result = calc_indicators(code)
    if "error" in result:
        raise HTTPException(500, result["error"])

    prompt = f"""你是专业股票技术分析师。请根据以下技术指标数据，给出简洁的解读和操作建议。

股票: {result.get('name') or code} ({code})
最新价: {result['price']}
日期: {result['date']}

均线: MA5={result['MA'].get('MA5')}, MA10={result['MA'].get('MA10')}, MA20={result['MA'].get('MA20')}, MA60={result['MA'].get('MA60')}
MACD: DIF={result['MACD'].get('DIF')}, DEA={result['MACD'].get('DEA')}, 柱={result['MACD'].get('MACD')}
KDJ: K={result['KDJ'].get('K')}, D={result['KDJ'].get('D')}, J={result['KDJ'].get('J')}
RSI(14): {result['RSI']}

自动信号: {result['signal']}

要求：
1. 简要概括当前技术面状态（多头/空头/震荡）
2. 指出 1-2 个关键信号
3. 给出短线操作建议（一句话）
4. 不超过 200 字，直接输出不要标题"""

    interpretation = await ai_chat(
        prompt,
        provider=body.provider,
        api_key=body.apiKey,
        model=body.model,
    )
    return {"interpretation": interpretation.strip()}


# ==================== 新闻 ====================

# 全球区域 → 新闻搜索关键词映射
_REGION_KEYWORDS = {
    "us":       "美股 美联储 纳斯达克",
    "ca":       "加拿大 央行 多伦多",
    "br":       "巴西 股市 Bovespa",
    "mx":       "墨西哥 经济",
    "uk":       "英国 央行 富时100",
    "de":       "德国 DAX 欧洲央行",
    "fr":       "法国 CAC40 欧洲",
    "jp":       "日本 日经225 央行",
    "kr":       "韩国 KOSPI",
    "in":       "印度 股市 Sensex",
    "au":       "澳大利亚 澳洲联储",
    "hk":       "港股 恒生指数",
    "cn":       "A股 上证指数",
    "ae":       "中东 沙特 阿联酋",
    "za":       "南非 非洲经济",
    "sg":       "东南亚 东盟 新加坡",
    "ru":       "俄罗斯 MOEX 卢布",
    "sa":       "沙特 石油 OPEC",
    "it":       "意大利 欧洲经济",
    "es":       "西班牙 IBEX 欧洲",
}


@router.get("/news/global/{region}")
def get_global_news(region: str):
    """获取全球区域财经新闻"""
    keyword = _REGION_KEYWORDS.get(region)
    if not keyword:
        raise HTTPException(404, f"未知区域: {region}")
    articles = fetch_news_jsonp(keyword, page=1, page_size=8)
    return {"region": region, "keyword": keyword, "news": articles}


@router.get("/news/holdings")
def get_holdings_news():
    """获取持仓相关新闻（按行业+代码匹配）"""
    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1")
    if not holdings:
        return []
    return get_matched_news(holdings)


@router.get("/news/{code}")
def get_stock_news(code: str):
    """获取单只股票相关新闻"""
    articles = fetch_news_jsonp(code, page=1, page_size=10)
    return {"code": code, "news": articles}


# ==================== AI 复盘 ====================

class ReviewRequest(BaseModel):
    provider: str = ""
    apiKey: str = ""
    model: str = ""
    period: str = "all"  # all / month / quarter / year


_PERIOD_CONFIG = {
    "month":   ("本月",   "AND traded_at >= date('now','localtime','start of month')"),
    "quarter": ("本季度", "AND traded_at >= date('now','localtime','start of year','+' || (cast((strftime('%m','now')-1)/3 as int)*3) || ' months')"),
    "year":    ("本年",   "AND traded_at >= date('now','localtime','start of year')"),
    "all":     ("全部",   ""),
}


@router.post("/review")
async def generate_review(body: ReviewRequest):
    """AI 复盘：读取交易记录，生成盈亏分析报告"""
    if not body.apiKey:
        raise HTTPException(400, "请先在设置页配置 AI 供应商和 API Key")

    period_label, period_filter = _PERIOD_CONFIG.get(body.period, ("全部", ""))

    txs = query_all(f"SELECT * FROM transactions WHERE user_id = 1 {period_filter} ORDER BY traded_at ASC")
    if not txs:
        return {"review": f"暂无{period_label}交易记录，无法生成复盘报告。"}

    # 按股票分组
    stock_txs: dict[str, list[dict]] = {}
    for t in txs:
        code = t["stock_code"]
        if code not in stock_txs:
            stock_txs[code] = []
        stock_txs[code].append(t)

    # 聚合统计
    total_buy_amount = 0.0
    total_sell_amount = 0.0
    buy_count = 0
    sell_count = 0
    stock_summaries = []

    for code, trades in stock_txs.items():
        name = trades[0]["stock_name"] or code
        buys = [t for t in trades if t["direction"] == "buy"]
        sells = [t for t in trades if t["direction"] == "sell"]

        buy_total = sum(t["amount"] for t in buys)
        sell_total = sum(t["amount"] for t in sells)
        buy_shares = sum(t["quantity"] for t in buys)
        sell_shares = sum(t["quantity"] for t in sells)

        # 已卖出部分的盈亏（FIFO 简化）
        realized_pnl = 0.0
        if buys and sells:
            avg_buy_price = buy_total / buy_shares if buy_shares > 0 else 0
            sold_qty = min(sell_shares, buy_shares)
            realized_pnl = sum(t["amount"] for t in sells) - sold_qty * avg_buy_price

        remaining = buy_shares - sell_shares

        stock_summaries.append({
            "name": name,
            "code": code,
            "buy_count": len(buys),
            "sell_count": len(sells),
            "total_buy": f"{buy_total:.2f}",
            "total_sell": f"{sell_total:.2f}",
            "realized_pnl": f"{realized_pnl:+.2f}",
            "remaining_shares": remaining,
            "trades": [f"{t['direction']} {t['quantity']}股@{t['price']:.2f} {t['traded_at'][:10]}" for t in trades],
        })

        total_buy_amount += buy_total
        total_sell_amount += sell_total
        buy_count += len(buys)
        sell_count += len(sells)

    total_pnl = total_sell_amount - total_buy_amount

    # 构造 prompt
    lines = [
        f"## {period_label}交易统计",
        f"- 总买入: {buy_count} 笔，共 {total_buy_amount:.2f} 元",
        f"- 总卖出: {sell_count} 笔，共 {total_sell_amount:.2f} 元",
        f"- 已实现盈亏: {total_pnl:+.2f} 元",
        "",
        "## 各股票明细",
    ]
    for s in stock_summaries:
        lines.append(f"\n### {s['name']}（{s['code']}）")
        lines.append(f"- 买入 {s['buy_count']} 笔共 {s['total_buy']} 元，卖出 {s['sell_count']} 笔共 {s['total_sell']} 元")
        lines.append(f"- 已实现盈亏: {s['realized_pnl']} 元，剩余持仓: {s['remaining_shares']} 股")
        for t in s["trades"]:
            lines.append(f"  - {t}")

    data_text = "\n".join(lines)

    prompt = f"""你是专业股票交易复盘分析师。请根据以下交易数据，生成一份复盘报告。

{data_text}

要求：
1. 先总结总体盈亏情况
2. 逐只股票分析交易表现
3. 指出做得好的和可以改进的地方
4. 给出 2-3 条具体的改进建议
5. 语言简洁专业，不超过 500 字
6. 直接输出报告正文，不要加"复盘报告"等标题"""

    review = await ai_chat(
        prompt,
        provider=body.provider,
        api_key=body.apiKey,
        model=body.model,
    )

    return {"review": review.strip()}


# ==================== 分散度分析 ====================

@router.get("/diversification")
def get_diversification():
    """持仓分散度分析：行业占比、市场占比、集中风险"""
    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1")
    if not holdings:
        return {"by_industry": [], "by_market": [], "risk_level": "无持仓", "max_single_pct": 0}

    # 同时获取行情数据（含估值）
    results = []
    total_value = 0.0
    for h in holdings:
        mkt = get_market(h["stock_code"])
        q = _cached_quote(h["stock_code"], mkt)

        # 当前价格
        if q and "error" not in q:
            price = q.get("price") or h["cost_price"]
            ind_raw = q.get("industry", "")
            region = q.get("region", "")
        else:
            price = h["cost_price"]
            ind_raw = ""
            region = ""

        mv = price * h["quantity"]
        total_value += mv
        results.append({
            "code": h["stock_code"],
            "name": h["stock_name"],
            "industry": _industry_keyword(ind_raw) if ind_raw else "",
            "region": region,
            "market": h.get("market", ""),
            "market_value": mv,
        })

    if total_value == 0:
        return {"by_industry": [], "by_market": [], "risk_level": "无数据", "max_single_pct": 0}

    # 按行业聚合
    industry_map: dict[str, dict] = {}
    for r in results:
        kw = r["industry"] or "未分类"
        if kw not in industry_map:
            industry_map[kw] = {"name": kw, "count": 0, "market_value": 0.0}
        industry_map[kw]["count"] += 1
        industry_map[kw]["market_value"] += r["market_value"]

    by_industry = sorted(industry_map.values(), key=lambda x: x["market_value"], reverse=True)
    for item in by_industry:
        item["pct"] = round(item["market_value"] / total_value * 100, 1)
        item["market_value"] = round(item["market_value"], 2)

    # 按市场聚合
    market_map: dict[str, dict] = {}
    for r in results:
        mkt = r["market"] or "未知"
        mkt_label = {"SH": "上海", "SZ": "深圳", "BJ": "北京"}.get(mkt, mkt)
        if mkt_label not in market_map:
            market_map[mkt_label] = {"name": mkt_label, "count": 0, "market_value": 0.0}
        market_map[mkt_label]["count"] += 1
        market_map[mkt_label]["market_value"] += r["market_value"]

    by_market = sorted(market_map.values(), key=lambda x: x["market_value"], reverse=True)
    for item in by_market:
        item["pct"] = round(item["market_value"] / total_value * 100, 1)
        item["market_value"] = round(item["market_value"], 2)

    # 风险等级
    max_single = max(r["market_value"] for r in results) / total_value * 100
    max_ind_pct = by_industry[0]["pct"] if by_industry else 0
    if max_ind_pct > 60 or len(holdings) <= 1:
        risk = "集中"
    elif max_ind_pct > 40 or len(holdings) <= 2:
        risk = "适中"
    else:
        risk = "分散"

    return {
        "by_industry": by_industry,
        "by_market": by_market,
        "risk_level": risk,
        "max_single_pct": round(max_single, 1),
    }


# ==================== 大盘对比 ====================

@router.get("/peer-comparison")
def get_peer_comparison():
    """持仓 vs 大盘指数对比"""
    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1")
    if not holdings:
        return {"items": [], "indices": {}}

    # 获取三大指数行情
    sh_idx = _cached_quote("000001", "1")
    sz_idx = _cached_quote("399001", "0")
    bj_idx = _cached_quote("899050", "0")

    indices = {}
    for idx, key in [(sh_idx, "sh"), (sz_idx, "sz"), (bj_idx, "bj")]:
        if idx and "error" not in idx:
            indices[key] = f"{idx.get('name', '')} {idx.get('change_pct', 0):+.2f}%"

    items = []
    for h in holdings:
        mkt = get_market(h["stock_code"])
        bench = sh_idx if mkt == "1" else sz_idx
        bench_name = bench.get("name", "上证指数" if mkt == "1" else "深证成指") if bench and "error" not in bench else ("上证指数" if mkt == "1" else "深证成指")
        bench_pct = bench.get("change_pct", 0) if bench and "error" not in bench else 0

        q = _cached_quote(h["stock_code"], mkt)
        if q and "error" not in q:
            my_pct = q.get("change_pct") or 0
            excess = round(my_pct - bench_pct, 2)
            items.append({
                "code": h["stock_code"],
                "name": h["stock_name"],
                "my_pct": my_pct,
                "bench_name": bench_name,
                "bench_pct": bench_pct,
                "excess": excess,
                "tag": "跑赢" if excess > 0 else ("持平" if excess == 0 else "跑输"),
            })
        else:
            items.append({
                "code": h["stock_code"],
                "name": h["stock_name"],
                "my_pct": None,
                "bench_name": bench_name,
                "bench_pct": bench_pct,
                "excess": None,
                "tag": "无数据",
            })

    return {"items": items, "indices": indices}


# ==================== 价格预警 ====================

class AlertBody(BaseModel):
    stock_code: str
    alert_type: str      # above / below / pct_change
    target_value: float


@router.get("/alerts")
def list_alerts():
    return query_all("SELECT * FROM price_alerts WHERE user_id = 1 ORDER BY id DESC")


@router.post("/alerts")
def add_alert(body: AlertBody):
    # 同股同类型去重
    existing = query_one(
        "SELECT id FROM price_alerts WHERE user_id = 1 AND stock_code = ? AND alert_type = ?",
        (body.stock_code, body.alert_type),
    )
    if existing:
        execute("DELETE FROM price_alerts WHERE id = ?", (existing["id"],))
    result = execute(
        "INSERT INTO price_alerts (user_id, stock_code, alert_type, target_value) VALUES (1, ?, ?, ?)",
        (body.stock_code, body.alert_type, body.target_value),
    )
    return {"id": result["lastrowid"], "message": "预警已设置"}


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int):
    execute("DELETE FROM price_alerts WHERE id = ? AND user_id = 1", (alert_id,))
    return {"message": "已删除"}


# ==================== 股息记录 ====================

class DividendBody(BaseModel):
    stock_code: str
    stock_name: str = ""
    amount_per_share: float
    ex_date: str
    total_amount: float
    note: str = ""


@router.get("/dividends")
def list_dividends():
    return query_all("SELECT * FROM dividends WHERE user_id = 1 ORDER BY ex_date DESC")


@router.post("/dividends")
def add_dividend(body: DividendBody):
    result = execute(
        """INSERT INTO dividends (user_id, stock_code, stock_name, amount_per_share, ex_date, total_amount, note)
           VALUES (1, ?, ?, ?, ?, ?, ?)""",
        (body.stock_code, body.stock_name, body.amount_per_share, body.ex_date, body.total_amount, body.note),
    )
    return {"id": result["lastrowid"], "message": "已记录"}


@router.delete("/dividends/{div_id}")
def delete_dividend(div_id: int):
    execute("DELETE FROM dividends WHERE id = ? AND user_id = 1", (div_id,))
    return {"message": "已删除"}


@router.get("/dividends/summary")
def dividends_summary():
    """股息汇总：总股息、按股票汇总"""
    rows = query_all(
        """SELECT stock_code, stock_name, SUM(total_amount) as total_div
           FROM dividends WHERE user_id = 1
           GROUP BY stock_code ORDER BY total_div DESC"""
    )
    total = sum(r["total_div"] for r in rows)
    return {"total_dividends": total, "by_stock": rows}
