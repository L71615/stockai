"""持仓管理路由：持仓 CRUD / 批次 / 导入 / XIRR / 组合 / 自选股"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute, execute_many
from services.utils import get_market, detect_asset_type, get_fund_nav, calc_xirr
from routers.stocks import _cached_quote  # 共享的行情缓存函数

router = APIRouter()

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

