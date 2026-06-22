"""交易记录路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute
from services.utils import detect_asset_type
from dependencies import get_current_user_id

router = APIRouter()

@router.get("/transactions")
def get_transactions():
    return query_all(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY traded_at DESC",
        (get_current_user_id(),)
    )


class TransactionBody(BaseModel):
    stock_code: str
    stock_name: str
    asset_type: str = ""
    direction: str
    price: float
    quantity: int
    fee: float | None = None   # None = 自动计算，有值 = 手动覆盖
    traded_at: str
    note: str = ""
    portfolio_id: int | None = None  # 可选：买入时自动创建的持仓归属组合


@router.post("/transactions")
def add_transaction(body: TransactionBody):
    from services.utils import calc_fee, get_market

    at = body.asset_type or detect_asset_type(body.stock_code)

    # 手续费：手动覆盖 or 自动计算
    if body.fee is not None:
        fee = round(body.fee, 2)
    else:
        calculated = calc_fee(body.price, body.quantity, body.direction, at)
        fee = round(calculated, 2) if calculated is not None else 0.0

    if body.direction == "buy":
        amount = round(body.price * body.quantity + fee, 2)
    else:
        amount = round(body.price * body.quantity - fee, 2)

    result = execute(
        """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, fee, traded_at, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (get_current_user_id(), body.stock_code, body.stock_name, at, body.direction, body.price, body.quantity, amount, fee, body.traded_at, body.note),
    )

    holding_result = None
    if body.direction == "buy":
        holding = query_one(
            "SELECT * FROM holdings WHERE user_id = ? AND stock_code = ?",
            (get_current_user_id(), body.stock_code),
        )
        if not holding:
            market = get_market(body.stock_code)
            # 若未指定 portfolio_id，尝试继承用户首个组合
            pid = body.portfolio_id
            if pid is None:
                pf = query_one("SELECT id FROM portfolios WHERE user_id = ? ORDER BY id LIMIT 1", (get_current_user_id(),))
                pid = pf["id"] if pf else None
            execute(
                """INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price, shares, portfolio_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    get_current_user_id(),
                    body.stock_code,
                    body.stock_name,
                    market,
                    at,
                    0,
                    body.price,
                    0 if at != "fund" else 0,
                    pid,
                ),
            )
        holding_result = _recalc_holding_for_code(body.stock_code)

    return {
        "id": result["lastrowid"],
        "message": "添加成功",
        "fee": fee,
        "amount": amount,
        "holding_updated": holding_result is not None,
        "holding": holding_result,
    }


def _recalc_holding_for_code(stock_code: str):
    """根据某代码的所有买入交易重新计算持仓成本和数量"""
    h = query_one(
        "SELECT * FROM holdings WHERE user_id = ? AND stock_code = ?", (get_current_user_id(), stock_code)
    )
    if not h:
        return None

    at = h.get("asset_type") or detect_asset_type(stock_code)
    is_fund = (at == "fund")

    buys = query_all(
        """SELECT * FROM transactions
           WHERE user_id = ? AND stock_code = ? AND direction = 'buy'
           ORDER BY traded_at ASC""",
        (get_current_user_id(), stock_code),
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
    tx = query_one("SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, get_current_user_id()))
    if not tx:
        raise HTTPException(404, "交易记录不存在")

    stock_code = tx["stock_code"]
    direction = tx["direction"]

    execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, get_current_user_id()))

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
    fee: float | None = None       # None = keep existing / auto-calc
    note: str | None = None


@router.put("/transactions/{tx_id}")
def update_transaction(tx_id: int, body: UpdateTransactionBody):
    """更新交易记录，并重新计算对应持仓成本"""
    from services.utils import calc_fee

    tx = query_one("SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, get_current_user_id()))
    if not tx:
        raise HTTPException(404, "交易记录不存在")

    # 合并：传了的字段更新，没传的保留原值
    traded_at = body.traded_at if body.traded_at is not None else tx["traded_at"]
    price = body.price if body.price is not None else tx["price"]
    quantity = body.quantity if body.quantity is not None else tx["quantity"]
    note = body.note if body.note is not None else tx["note"]

    # 手续费：手动指定 > 保留原值 > 自动计算
    at = tx.get("asset_type") or detect_asset_type(tx["stock_code"])
    if body.fee is not None:
        fee = round(body.fee, 2)
    elif tx.get("fee"):
        fee = tx["fee"]  # 保留用户之前设置的手动值
    else:
        calculated = calc_fee(price, quantity, tx["direction"], at)
        fee = round(calculated, 2) if calculated is not None else 0.0

    if tx["direction"] == "buy":
        amount = round(price * quantity + fee, 2)
    else:
        amount = round(price * quantity - fee, 2)

    execute(
        """UPDATE transactions SET traded_at = ?, price = ?, quantity = ?, amount = ?, fee = ?, note = ?
           WHERE id = ? AND user_id = ?""",
        (traded_at, price, quantity, amount, fee, note, tx_id, get_current_user_id()),
    )

    holding_result = None
    if tx["direction"] == "buy":
        holding_result = _recalc_holding_for_code(tx["stock_code"])

    return {
        "message": "已更新",
        "updated_id": tx_id,
        "fee": fee,
        "amount": amount,
        "holding_updated": holding_result is not None,
        "holding": holding_result,
    }


