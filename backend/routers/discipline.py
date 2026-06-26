"""交易纪律系统 — 止损绑定 + 连亏保护 + 交易日志"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import query_one, query_all, execute
from dependencies import get_current_user_id

router = APIRouter(prefix="/api/discipline", tags=["discipline"])


# ═══════════════════════════════════════════════════════════
#  Types
# ═══════════════════════════════════════════════════════════

class StopLossBody(BaseModel):
    stop_loss_price: float
    take_profit_price: float | None = None


class TriggerBody(BaseModel):
    exit_price: float


# ═══════════════════════════════════════════════════════════
#  Stop-Loss CRUD
# ═══════════════════════════════════════════════════════════

def _cached_quote(code: str) -> dict | None:
    """快速获取实时报价（带5秒内存缓存）"""
    import time
    if not hasattr(_cached_quote, "_cache"):
        _cached_quote._cache = {}
    now = time.time()
    cache = _cached_quote._cache
    if code in cache:
        ts, price = cache[code]
        if now - ts < 5:
            return {"price": price}
    try:
        from services.utils import get_market
        from services.akshare_adapter import get_batch_quotes
        quotes = get_batch_quotes([code])
        if code in quotes and quotes[code].get("price"):
            price = quotes[code]["price"]
            cache[code] = (now, price)
            return {"price": price}
    except Exception:
        pass
    return None


@router.post("/stop-loss/{holding_id}")
def set_stop_loss(holding_id: int, body: StopLossBody):
    """为持仓设置止损/止盈价"""
    uid = get_current_user_id()
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, uid))
    if not h:
        raise HTTPException(404, "持仓不存在")

    execute(
        "UPDATE holdings SET stop_loss_price = ?, take_profit_price = ?, updated_at = datetime('now','localtime') WHERE id = ?",
        (body.stop_loss_price, body.take_profit_price, holding_id),
    )
    return {"ok": True, "holding_id": holding_id,
            "stop_loss_price": body.stop_loss_price,
            "take_profit_price": body.take_profit_price}


@router.get("/stop-loss/check")
def check_stop_losses():
    """检查所有持仓的止损/止盈状态"""
    uid = get_current_user_id()
    holdings = query_all(
        "SELECT * FROM holdings WHERE user_id = ? AND quantity > 0",
        (uid,),
    )

    triggered = []
    approaching = []
    safe = []

    for h in holdings:
        code = h["stock_code"]
        sl = h.get("stop_loss_price")
        tp = h.get("take_profit_price")
        if sl is None and tp is None:
            continue

        quote = _cached_quote(code)
        price = quote["price"] if quote else None
        if price is None:
            safe.append({**h, "current_price": None, "status": "unknown"})
            continue

        cost = h["cost_price"]
        sl_pct = round((sl - price) / price * 100, 2) if sl else None
        tp_pct = round((tp - price) / price * 100, 2) if tp else None

        entry = {
            "holding_id": h["id"],
            "stock_code": code,
            "stock_name": h.get("stock_name", ""),
            "cost_price": round(cost, 2),
            "current_price": round(price, 2),
            "stop_loss_price": sl,
            "take_profit_price": tp,
            "stop_loss_distance_pct": sl_pct,
            "take_profit_distance_pct": tp_pct,
        }

        # Trigger check
        if sl and price <= sl:
            entry["status"] = "triggered_stop_loss"
            triggered.append(entry)
        elif tp and price >= tp:
            entry["status"] = "triggered_take_profit"
            triggered.append(entry)
        elif sl and sl_pct is not None and sl_pct < 2:
            entry["status"] = "approaching_stop_loss"
            approaching.append(entry)
        else:
            entry["status"] = "safe"
            safe.append(entry)

    return {"triggered": triggered, "approaching": approaching, "safe": safe}


@router.post("/stop-loss/{holding_id}/trigger")
def trigger_stop_loss(holding_id: int, body: TriggerBody):
    """执行止损/止盈卖出，创建自动卖出交易记录"""
    uid = get_current_user_id()
    h = query_one("SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, uid))
    if not h or h["quantity"] <= 0:
        raise HTTPException(404, "无可用持仓")

    price = body.exit_price
    qty = h["quantity"]
    amount = round(price * qty, 2)
    fee = round(max(amount * 0.00025, 5), 2)
    net = round(amount - fee, 2)

    tid = execute(
        """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, fee, traded_at, note)
           VALUES (?, ?, ?, ?, 'sell', ?, ?, ?, ?, date('now','localtime'), '止损自动卖出')""",
        (uid, h["stock_code"], h.get("stock_name", ""), h.get("asset_type", ""), price, qty, net, fee),
    )["lastrowid"]

    execute("UPDATE holdings SET quantity = 0, updated_at = datetime('now','localtime') WHERE id = ?", (holding_id,))
    execute("UPDATE holdings SET stop_loss_price = NULL, take_profit_price = NULL WHERE id = ?", (holding_id,))

    return {"ok": True, "transaction_id": tid, "message": f"已触发卖出 {h['stock_code']} @ {price}"}


@router.get("/stop-loss/history")
def stop_loss_history(limit: int = 20):
    """止损/止盈触发历史"""
    uid = get_current_user_id()
    rows = query_all(
        """SELECT t.*, h.cost_price
           FROM transactions t
           LEFT JOIN holdings h ON h.user_id = t.user_id AND h.stock_code = t.stock_code
           WHERE t.user_id = ? AND t.direction = 'sell' AND (t.note LIKE '%止损%' OR t.note LIKE '%止盈%')
           ORDER BY t.traded_at DESC LIMIT ?""",
        (uid, limit),
    )
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════
#  Dashboard aggregator
# ═══════════════════════════════════════════════════════════

@router.get("/dashboard")
def discipline_dashboard():
    """交易纪律仪表板聚合数据"""
    uid = get_current_user_id()

    # Active holdings with stop-loss
    holdings = query_all(
        "SELECT * FROM holdings WHERE user_id = ? AND quantity > 0",
        (uid,),
    )

    stop_loss_items = []
    for h in holdings:
        if h.get("stop_loss_price"):
            quote = _cached_quote(h["stock_code"])
            price = quote["price"] if quote else None
            sl_pct = None
            if price and h["stop_loss_price"]:
                sl_pct = round((h["stop_loss_price"] - price) / price * 100, 2)
            stop_loss_items.append({
                "holding_id": h["id"],
                "stock_code": h["stock_code"],
                "stock_name": h.get("stock_name", ""),
                "cost_price": h["cost_price"],
                "current_price": price,
                "stop_loss_price": h["stop_loss_price"],
                "stop_loss_distance_pct": sl_pct,
                "danger": sl_pct is not None and sl_pct < 3,
            })

    return {
        "holdings_with_stop_loss": stop_loss_items,
        "active_stop_loss_count": len(stop_loss_items),
        "danger_count": sum(1 for s in stop_loss_items if s["danger"]),
    }


# ═══════════════════════════════════════════════════════════
#  Loss streak & protection mode
# ═══════════════════════════════════════════════════════════

class ProtectionToggleBody(BaseModel):
    enabled: bool


@router.get("/loss-streak")
def get_loss_streak():
    """获取当前连亏状态和保护模式"""
    from services.discipline_service import check_protection
    return check_protection(get_current_user_id())


@router.post("/protection/toggle")
def toggle_protection(body: ProtectionToggleBody):
    """开关保护模式"""
    from services.discipline_service import get_protection_config, save_protection_config
    cfg = get_protection_config()
    cfg["enabled"] = body.enabled
    save_protection_config(cfg)
    return {"ok": True, "enabled": body.enabled}


# ═══════════════════════════════════════════════════════════
#  Trading journal
# ═══════════════════════════════════════════════════════════

class JournalEntryBody(BaseModel):
    discipline_score: int | None = None
    emotional_state: str | None = None
    lessons_learned: str | None = None


@router.get("/journal")
def list_journal(limit: int = 50):
    """交易日志列表"""
    from services.discipline_service import get_journal
    return get_journal(get_current_user_id(), limit)


@router.put("/journal/{journal_id}")
def update_journal(journal_id: int, body: JournalEntryBody):
    """更新日志（纪律评分、情绪、教训）"""
    updates = {}
    if body.discipline_score is not None:
        updates["discipline_score"] = body.discipline_score
    if body.emotional_state is not None:
        updates["emotional_state"] = body.emotional_state
    if body.lessons_learned is not None:
        updates["lessons_learned"] = body.lessons_learned
    if not updates:
        return {"ok": True}

    sets = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [journal_id]
    execute(f"UPDATE trade_journal SET {sets} WHERE id = ?", tuple(vals))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
#  Trading plans
# ═══════════════════════════════════════════════════════════

class PlanBody(BaseModel):
    date: str | None = None
    market_state: str = ""
    strategy: str = ""
    targets: list[dict] = []
    risk_notes: str = ""
    max_position_pct: int = 50
    summary: str = ""


@router.post("/plan")
def save_plan(body: PlanBody):
    """保存/更新盘前计划"""
    from datetime import date as dt_date
    import json
    uid = get_current_user_id()
    plan_date = body.date or dt_date.today().isoformat()
    content = json.dumps({
        "targets": body.targets,
        "strategy": body.strategy,
        "risk_notes": body.risk_notes,
        "max_position_pct": body.max_position_pct,
    }, ensure_ascii=False)

    existing = query_one(
        "SELECT id FROM trading_plans WHERE user_id = ? AND plan_date = ? AND plan_type = 'pre_market'",
        (uid, plan_date),
    )
    if existing:
        execute(
            "UPDATE trading_plans SET market_state = ?, content = ?, summary = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (body.market_state, content, body.summary, existing["id"]),
        )
        pid = existing["id"]
    else:
        pid = execute(
            """INSERT INTO trading_plans (user_id, plan_date, plan_type, market_state, content, summary)
               VALUES (?, ?, 'pre_market', ?, ?, ?)""",
            (uid, plan_date, body.market_state, content, body.summary),
        )["lastrowid"]
    return {"id": pid, "plan_date": plan_date, "ok": True}


@router.get("/plan")
def get_plan(date: str = ""):
    """读取盘前计划"""
    from datetime import date as dt_date
    uid = get_current_user_id()
    plan_date = date or dt_date.today().isoformat()
    row = query_one(
        "SELECT * FROM trading_plans WHERE user_id = ? AND plan_date = ? AND plan_type = 'pre_market'",
        (uid, plan_date),
    )
    if not row:
        return None
    import json
    d = dict(row)
    try:
        d["content"] = json.loads(d.get("content", "{}"))
    except Exception:
        d["content"] = {}
    return d
