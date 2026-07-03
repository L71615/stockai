"""持仓管理路由：持仓 CRUD / 批次 / 导入 / XIRR / 组合 / 自选股"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute, execute_many
from services.utils import get_market, detect_asset_type, get_fund_nav, calc_xirr, get_fee_config, FeeConfig
from routers.stocks import _cached_quote  # 共享的行情缓存函数
from dependencies import get_current_user_id


def _estimate_sell_fee(market_value: float, asset_type: str, stock_code: str = "") -> float:
    """预估卖出费用（同花顺口径：佣金+印花税+过户费）

    Stock: 佣金 max(费率*金额,最低) + 印花税0.05% + 过户费0.002%
    ETF:   佣金 max(费率*金额,最低)，无印花税/过户费
    Fund:  0
    """
    at = (asset_type or "").strip().lower()
    if at in ("fund", "hk") or market_value <= 0:
        return 0.0

    cfg = get_fee_config()

    if at == "etf":
        return round(max(market_value * cfg.commission_rate, cfg.commission_min), 2)

    # Stock: 佣金 + 印花税 + 过户费
    commission = max(market_value * cfg.commission_rate, cfg.commission_min)
    stamp_tax = market_value * FeeConfig.stamp_tax_rate
    transfer_fee = market_value * FeeConfig.transfer_fee_rate
    return round(commission + stamp_tax + transfer_fee, 2)

router = APIRouter()

@router.get("/holdings")
def get_holdings(portfolio_id: int | None = None):
    if portfolio_id:
        return query_all("SELECT * FROM holdings WHERE user_id = ? AND portfolio_id = ? ORDER BY id DESC", (get_current_user_id(), portfolio_id))
    return query_all("SELECT * FROM holdings WHERE user_id = ? ORDER BY id DESC", (get_current_user_id(),))


class HoldingBody(BaseModel):
    stock_code: str
    stock_name: str
    market: str = "SH"
    asset_type: str = ""      # stock / etf / fund，空则自动识别
    quantity: int = 0         # 股数(股票/ETF) 或 份数(基金)
    cost_price: float = 0.0   # 成本价(股票/ETF) 或 成本净值(基金)
    shares: float | None = None  # 基金份额，数量=份数时等同 quantity
    portfolio_id: int | None = None
    fee: float | None = None  # None = 自动计算


@router.post("/holdings")
def add_holding(body: HoldingBody):
    from services.utils import calc_fee

    at = body.asset_type or detect_asset_type(body.stock_code)
    qty = body.quantity
    cost = body.cost_price
    if body.shares is not None:
        qty = int(body.shares) if at != "fund" else body.shares

    # 手续费
    if body.fee is not None:
        fee = round(body.fee, 2)
    else:
        calculated = calc_fee(cost, qty, "buy", at)
        fee = round(calculated, 2) if calculated is not None else 0.0

    amount = round(qty * cost + fee, 2)
    # 持仓成本价 = 含手续费均价
    cost_with_fee = round(amount / qty, 4) if qty > 0 else cost

    result = execute(
        """INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price, shares, portfolio_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (get_current_user_id(), body.stock_code, body.stock_name, body.market, at, qty, cost_with_fee, body.shares, body.portfolio_id),
    )
    holding_id = result["lastrowid"]
    # 同步创建初始买入交易记录；失败则删除持仓回滚
    try:
        execute(
            """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, fee, traded_at, note)
               VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, date('now','localtime'), '初始建仓')""",
            (get_current_user_id(), body.stock_code, body.stock_name, at, cost, qty, amount, fee),
        )
    except Exception:
        execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        raise HTTPException(500, "持仓创建失败，请重试")

    return {"id": holding_id, "message": "添加成功", "asset_type": at, "fee": fee, "amount": amount}


@router.put("/holdings/{holding_id}")
def update_holding(holding_id: int, body: HoldingBody):
    at = body.asset_type or detect_asset_type(body.stock_code)
    execute(
        """UPDATE holdings SET stock_code=?, stock_name=?, market=?, asset_type=?, quantity=?, cost_price=?, shares=?, portfolio_id=?
           WHERE id=? AND user_id=?""",
        (body.stock_code, body.stock_name, body.market, at, body.quantity, body.cost_price, body.shares, body.portfolio_id, holding_id, get_current_user_id()),
    )
    return {"message": "已更新"}


@router.delete("/holdings/{holding_id}")
def delete_holding(holding_id: int):
    execute("DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding_id, get_current_user_id()))
    return {"message": "已删除"}


class JournalBody(BaseModel):
    journal: str = ""


@router.put("/holdings/{holding_id}/journal")
def update_journal(holding_id: int, body: JournalBody):
    h = query_one("SELECT id FROM holdings WHERE id = ? AND user_id = ?", (holding_id, get_current_user_id()))
    if not h:
        raise HTTPException(404, "持仓不存在")
    execute("UPDATE holdings SET journal = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (body.journal, holding_id))
    return {"message": "已保存", "journal": body.journal}


@router.get("/holdings/with-pnl")
def get_holdings_with_pnl(portfolio_id: int | None = None):
    """持仓列表 + 实时盈亏（批量报价，避免串行 HTTP）"""
    if portfolio_id:
        rows = query_all("SELECT * FROM holdings WHERE user_id = ? AND portfolio_id = ? ORDER BY id DESC", (get_current_user_id(), portfolio_id))
    else:
        rows = query_all("SELECT * FROM holdings WHERE user_id = ? ORDER BY id DESC", (get_current_user_id(),))

    # ── 第一遍：分类 + 收集需要批量报价的代码 ──
    stock_codes = []
    fund_items = []
    stock_items = []

    for h in rows:
        item = dict(h)
        at = item.get("asset_type", "") or detect_asset_type(item["stock_code"])
        if at == "fund":
            fund_items.append(item)
        else:
            stock_items.append(item)
            stock_codes.append(item["stock_code"])

    # ── 批量拉取股票/ETF行情（一次 HTTP 替代 N 次串行）──
    quotes = {}
    if stock_codes:
        try:
            from services.vendor_router import route
            quotes = route("get_batch_quotes", codes=stock_codes)
            if not isinstance(quotes, dict):
                quotes = {}
        except Exception:
            pass

    results = []
    total_cost = 0.0
    total_value = 0.0
    today_pnl = 0.0

    # ── 处理基金 ──
    for item in fund_items:
        qty = item["quantity"] or 0
        cost = item["cost_price"] or 0
        item["current_price"] = None
        item["change_pct"] = None
        item["market_value"] = 0.0
        item["pnl"] = 0.0
        item["pnl_pct"] = 0.0
        item["today_pnl"] = 0.0
        item["est_label"] = ""
        nav_data = get_fund_nav(item["stock_code"])
        if nav_data:
            item["stock_name"] = item["stock_name"] or nav_data["name"]
            item["current_price"] = nav_data["nav"]
            item["est_nav"] = nav_data["est_nav"]
            item["change_pct"] = nav_data["est_change_pct"]
            item["est_label"] = nav_data["nav_date"]
            shares = item.get("shares") or qty
            item["market_value"] = nav_data["nav"] * shares
            item["pnl"] = round((nav_data["nav"] - cost) * shares, 2)
            item["pnl_pct"] = round(item["pnl"] / (cost * shares) * 100, 2) if cost > 0 and shares > 0 else 0
            item["today_pnl"] = nav_data["nav"] * shares * nav_data["est_change_pct"] / 100
            item["cost_amount"] = cost * shares
        else:
            item["cost_amount"] = cost * qty
        total_cost += item.get("cost_amount", 0)
        total_value += item["market_value"]
        today_pnl += item.get("today_pnl", 0)
        results.append(item)

    # ── 处理股票/ETF（用批量行情）──
    for item in stock_items:
        qty = item["quantity"] or 0
        cost = item["cost_price"] or 0
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
            item["market_value"] = q["price"] * qty
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
        today_pnl += item.get("today_pnl", 0)
        results.append(item)

    # 汇总
    total_pnl = sum(r.get("pnl", 0) for r in results)
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0

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


@router.get("/holdings/history")
def get_portfolio_history():
    """获取组合资产走势数据：从第一笔交易至今的累计成本 + 当前市值"""
    buys = query_all(
        """SELECT traded_at, amount FROM transactions
           WHERE user_id = ? AND direction = 'buy'
           ORDER BY traded_at ASC""",
        (get_current_user_id(),),
    )
    if not buys:
        return {"data": []}

    # 累计成本日线
    daily: dict[str, float] = {}
    for t in buys:
        date = (t["traded_at"] or "")[:10]
        daily[date] = daily.get(date, 0) + t["amount"]

    # 按日期排序，计算累计
    sorted_dates = sorted(daily.keys())
    cumulative = 0.0
    data = []
    for date in sorted_dates:
        cumulative += daily[date]
        data.append({"date": date, "cost": round(cumulative, 2)})

    # 最后一天加上当前市值
    holdings = query_all("SELECT * FROM holdings WHERE user_id = ?", (get_current_user_id(),))
    total_market_value = 0.0
    for h in holdings:
        at = h.get("asset_type") or detect_asset_type(h["stock_code"])
        from services.utils import get_market
        from routers.stocks import _cached_quote
        if at in ("fund",):
            from services.utils import get_fund_nav
            nav = get_fund_nav(h["stock_code"])
            price = (nav.get("est_nav") or nav.get("nav")) if nav else h["cost_price"]
        else:
            mkt = get_market(h["stock_code"])
            q = _cached_quote(h["stock_code"], mkt)
            price = q.get("price") if q and "error" not in q else h["cost_price"]
        qty = h.get("shares") or h["quantity"] or 0
        total_market_value += round(price * qty, 2)

    # Add today's market value point
    from datetime import date as dt_date
    today = dt_date.today().isoformat()
    if data and data[-1]["date"] == today:
        data[-1]["value"] = round(total_market_value, 2)
    else:
        data.append({"date": today, "cost": data[-1]["cost"] if data else 0, "value": round(total_market_value, 2)})

    return {"data": data}


@router.get("/holdings/xirr")
def get_xirr():
    """按持仓计算 XIRR 年化收益率（基于所有买入交易+当前市值）"""
    buys = query_all(
        """SELECT stock_code, stock_name, amount, traded_at FROM transactions
           WHERE user_id = ? AND direction = 'buy' ORDER BY traded_at ASC""",
        (get_current_user_id(),),
    )
    if not buys:
        return {"total_xirr": None, "by_holding": []}

    # 获取当前市值（复用 get_holdings_with_pnl 的计算逻辑）
    holdings = query_all("SELECT * FROM holdings WHERE user_id = ?", (get_current_user_id(),))
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
    fee: float | None = None  # None = 自动计算
    note: str = ""


@router.get("/holdings/{holding_id}/lots")
def get_holding_lots(holding_id: int):
    """获取某持仓的所有买入批次（从 transactions 表读取）"""
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, get_current_user_id()))
    if not h:
        raise HTTPException(404, "持仓不存在")

    at = h.get("asset_type") or detect_asset_type(h["stock_code"])
    is_fund = (at == "fund")
    lots = []

    txs = query_all(
        """SELECT * FROM transactions
           WHERE user_id = ? AND stock_code = ? AND direction = 'buy'
           ORDER BY traded_at ASC""",
        (get_current_user_id(), h["stock_code"]),
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
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, get_current_user_id()))
    if not h:
        raise HTTPException(404, "持仓不存在")

    at = h.get("asset_type") or detect_asset_type(h["stock_code"])

    from services.utils import calc_fee

    if at == "fund":
        # 基金：金额 ÷ 净值 = 份额（费率不固定，手动输入）
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
        fee = round(body.fee, 2) if body.fee is not None else 0.0
    else:
        # 股票/ETF：数量 × 单价 + 手续费 = 总金额
        if body.quantity <= 0 or body.price <= 0:
            raise HTTPException(400, "请填写有效的买入数量和单价")
        qty = body.quantity
        price = body.price
        if body.fee is not None:
            fee = round(body.fee, 2)
        else:
            calculated = calc_fee(price, qty, "buy", at)
            fee = round(calculated, 2) if calculated is not None else 0.0
        amount = round(qty * price + fee, 2)

    # 创建买入交易记录
    tx_result = execute(
        """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, fee, traded_at, note)
           VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, ?)""",
        (get_current_user_id(), h["stock_code"], h["stock_name"], at, price, qty, amount, fee, body.traded_at, body.note or "追加买入"),
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
    fee: float | None = None  # None = 自动计算


class ImportLotsBody(BaseModel):
    lots: list[ImportLotItem]
    note: str = "历史数据导入"


@router.post("/holdings/{holding_id}/import-lots")
def import_lots(holding_id: int, body: ImportLotsBody):
    """批量导入历史买入记录，更新加权成本"""
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, get_current_user_id()))
    if not h:
        raise HTTPException(404, "持仓不存在")

    if not body.lots:
        raise HTTPException(400, "没有可导入的记录")

    from services.utils import calc_fee

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
            fee = round(lot.fee, 2) if lot.fee is not None else 0.0
        else:
            qty = lot.amount  # 对股票来说 amount 字段是数量
            price = lot.nav   # nav 字段是单价
            if lot.fee is not None:
                fee = round(lot.fee, 2)
            else:
                calculated = calc_fee(price, qty, "buy", at)
                fee = round(calculated, 2) if calculated is not None else 0.0
            amount = round(qty * price + fee, 2)

        parsed.append({
            "traded_at": lot.traded_at.strip(),
            "price": price,
            "quantity": qty,
            "amount": amount,
            "fee": fee,
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
            """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, fee, traded_at, note)
               VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, ?)""",
            (get_current_user_id(), h["stock_code"], h["stock_name"], at, p["price"], p["quantity"], p["amount"], p.get("fee", 0), p["traded_at"], body.note),
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
    return query_all("SELECT * FROM portfolios WHERE user_id = ? ORDER BY id", (get_current_user_id(),))


@router.post("/portfolios")
def add_portfolio(body: PortfolioBody):
    result = execute(
        "INSERT INTO portfolios (user_id, name, type) VALUES (?, ?, ?)",
        (get_current_user_id(), body.name, body.type),
    )
    return {"id": result["lastrowid"], "message": "创建成功"}


@router.delete("/portfolios/{pf_id}")
def delete_portfolio(pf_id: int):
    # 将该组合下的持仓设为未分类
    execute("UPDATE holdings SET portfolio_id = NULL WHERE portfolio_id = ? AND user_id = ?", (pf_id, get_current_user_id()))
    execute("DELETE FROM portfolios WHERE id = ? AND user_id = ?", (pf_id, get_current_user_id()))
    return {"message": "已删除"}


# ==================== 自选股 ====================

@router.get("/watchlist")
def get_watchlist():
    return query_all("SELECT * FROM watchlist WHERE user_id = ? ORDER BY added_at DESC", (get_current_user_id(),))


class WatchlistBody(BaseModel):
    stock_code: str
    stock_name: str
    market: str = "SH"
    asset_type: str = ""


@router.post("/watchlist")
def add_watchlist(body: WatchlistBody):
    at = body.asset_type or detect_asset_type(body.stock_code)
    result = execute(
        "INSERT OR IGNORE INTO watchlist (user_id, stock_code, stock_name, market, asset_type) VALUES (?, ?, ?, ?, ?)",
        (get_current_user_id(), body.stock_code, body.stock_name, body.market, at),
    )
    return {"id": result["lastrowid"], "message": "添加成功"}


@router.delete("/watchlist/{item_id}")
def delete_watchlist(item_id: int):
    execute("DELETE FROM watchlist WHERE id = ? AND user_id = ?", (item_id, get_current_user_id()))
    return {"message": "已移除"}


# ==================== 手续费重算 ====================

@router.post("/recalc-fees")
def recalc_fees_and_holdings():
    """用当前配置的费率重新计算所有买入交易的手续费，并更新持仓成本"""
    from services.utils import calc_fee, get_fee_config

    cfg = get_fee_config()
    buys = query_all(
        """SELECT * FROM transactions
           WHERE user_id = ? AND direction = 'buy'
           ORDER BY traded_at ASC""",
        (get_current_user_id(),),
    )

    updated = []
    for t in buys:
        at = t.get("asset_type") or detect_asset_type(t["stock_code"])
        calculated = calc_fee(t["price"], t["quantity"], "buy", at)
        fee = round(calculated, 2) if calculated is not None else 0.0
        amount = round(t["price"] * t["quantity"] + fee, 2)

        if abs(fee - (t.get("fee") or 0)) > 0.01 or abs(amount - (t.get("amount") or 0)) > 0.01:
            execute(
                """UPDATE transactions SET fee = ?, amount = ? WHERE id = ?""",
                (fee, amount, t["id"]),
            )
            updated.append({
                "id": t["id"],
                "stock_code": t["stock_code"],
                "stock_name": t["stock_name"],
                "old_amount": t.get("amount", 0),
                "new_amount": amount,
                "fee": fee,
            })

    # 重算所有持仓成本
    holdings_updated = []
    holdings = query_all("SELECT * FROM holdings WHERE user_id = ?", (get_current_user_id(),))
    for h in holdings:
        at = h.get("asset_type") or detect_asset_type(h["stock_code"])
        is_fund = (at == "fund")
        buys_for_code = query_all(
            """SELECT * FROM transactions
               WHERE user_id = ? AND stock_code = ? AND direction = 'buy'
               ORDER BY traded_at ASC""",
            (get_current_user_id(), h["stock_code"]),
        )
        if buys_for_code:
            total_amount = sum(t["amount"] for t in buys_for_code)
            total_shares = sum(t["quantity"] for t in buys_for_code)
            new_cost = round(total_amount / total_shares, 4) if total_shares > 0 else 0
            old_cost = h["cost_price"]
            if abs(new_cost - old_cost) > 0.0001:
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
                holdings_updated.append({
                    "stock_code": h["stock_code"],
                    "stock_name": h["stock_name"],
                    "old_cost": old_cost,
                    "new_cost": new_cost,
                })

    return {
        "config": {
            "commission_rate": f"{cfg.commission_rate * 100:.3f}%",
            "commission_min": f"{cfg.commission_min}元",
        },
        "transactions_fixed": len(updated),
        "details": updated,
        "holdings_updated": len(holdings_updated),
        "holdings_details": holdings_updated,
    }


# ═══════════════════════════════════════════════════════════
# 持仓详情 → K 线图表数据
# ═══════════════════════════════════════════════════════════

_PERIOD_DAYS = {"5d": 5, "1m": 22, "3m": 66, "6m": 130}


def _agg_bars(dates, opens, highs, lows, closes, volumes, freq):
    if freq not in ("week", "month"):
        return dates, opens, highs, lows, closes, volumes
    groups = {}
    for i in range(len(dates)):
        if freq == "week":
            try:
                d = datetime.strptime(dates[i], "%Y-%m-%d")
                key = f"{d.year}-W{d.isocalendar()[1]:02d}"
            except Exception:
                key = dates[i][:7] if len(dates[i]) >= 7 else dates[i]
        else:
            key = dates[i][:7]
        if key not in groups:
            groups[key] = {"o": opens[i], "h": highs[i], "l": lows[i],
                          "c": closes[i], "v": volumes[i], "d": dates[i]}
        else:
            g = groups[key]
            g["h"] = max(g["h"], highs[i])
            g["l"] = min(g["l"], lows[i])
            g["c"] = closes[i]
            g["v"] += volumes[i]
            g["d"] = dates[i]
    keys = sorted(groups.keys())
    return ([groups[k]["d"] for k in keys], [groups[k]["o"] for k in keys],
            [groups[k]["h"] for k in keys], [groups[k]["l"] for k in keys],
            [groups[k]["c"] for k in keys], [groups[k]["v"] for k in keys])


def _sma(data, n):
    if len(data) < n:
        return [None] * len(data)
    return [None] * (n - 1) + [round(sum(data[i - n + 1:i + 1]) / n, 2) for i in range(n - 1, len(data))]


@router.get("/kline/{code}")
def get_kline_chart(code: str, period: str = "1m"):
    """K 线数据（持仓详情抽屉使用）
    period: 5d / 1m(日K) / 3m(周K) / 6m(月K)
    """
    import json as _json
    import urllib.request as _req

    days = _PERIOD_DAYS.get(period, 22)

    # 直连腾讯 API，绕过缓存
    c = code.strip()
    sym = f"sh{c}" if c.startswith(("51","56","58","60","68")) else f"sz{c}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{max(days+60,120)},qfq"
    try:
        raw = _req.urlopen(_req.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10).read().decode("utf-8")
        data = _json.loads(raw)
        klines = data.get("data", {}).get(sym, {}).get("qfqday", [])
    except Exception as e:
        raise HTTPException(500, f"获取K线失败: {e}")

    if not klines:
        raise HTTPException(500, "无K线数据")

    dates = [k[0] for k in klines]
    opens = [float(k[1]) for k in klines]
    closes = [float(k[2]) for k in klines]
    highs = [float(k[3]) for k in klines]
    lows = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    if not opens:
        opens = [closes[0]] + closes[:-1]
        opens = opens[:len(closes)]
    if not volumes or all(v == 0 for v in volumes):
        volumes = [0] * len(closes)

    freq = {"3m": "week", "6m": "month"}.get(period)
    if freq:
        dates, opens, highs, lows, closes, volumes = _agg_bars(
            dates, opens, highs, lows, closes, volumes, freq)

    n = min(len(dates), days + 10)
    dates = dates[-n:]
    opens = opens[-n:]
    highs = highs[-n:]
    lows = lows[-n:]
    closes = closes[-n:]
    volumes = volumes[-n:]

    ma5 = _sma(closes, 5)[-n:]
    ma10 = _sma(closes, 10)[-n:]
    ma20 = _sma(closes, 20)[-n:]

    return {
        "code": code, "period": period,
        "dates": dates, "opens": opens, "highs": highs, "lows": lows,
        "closes": closes, "volumes": volumes,
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
    }
