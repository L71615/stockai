"""交易记录路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute
from services.utils import detect_asset_type

router = APIRouter()

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


