"""定投计划路由"""

import json
from datetime import datetime, date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import query_all, query_one, execute
from services.ai_service import ai_chat
from services.utils import run_curl, get_market
from services.akshare_adapter import get_quote as ak_get_quote
from dependencies import get_current_user_id

router = APIRouter()


class DcaPlanBody(BaseModel):
    holding_id: int
    stock_code: str
    stock_name: str = ""
    cycle: str            # daily / weekly / biweekly / monthly
    cycle_day: int | None = None   # 月定投 1-28，周定投 1-7；daily 忽略
    amount: float
    next_deduction: str = ""   # ISO 日期


class DcaUpdateBody(BaseModel):
    cycle: str | None = None
    cycle_day: int | None = None
    amount: float | None = None
    next_deduction: str | None = None


@router.get("/dca")
def list_dca():
    return query_all("SELECT * FROM dca_plans WHERE user_id = ? ORDER BY id DESC", (get_current_user_id(),))


@router.post("/dca")
def add_dca(body: DcaPlanBody):
    # 检查是否已有关联持仓的定投
    existing = query_one(
        "SELECT id FROM dca_plans WHERE holding_id = ? AND user_id = ?",
        (body.holding_id, get_current_user_id()),
    )
    if existing:
        raise HTTPException(400, "该持仓已绑定定投计划，请先编辑现有计划")

    result = execute(
        """INSERT INTO dca_plans (user_id, holding_id, stock_code, stock_name, cycle, cycle_day, amount, next_deduction)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (get_current_user_id(), body.holding_id, body.stock_code, body.stock_name, body.cycle, body.cycle_day, body.amount, body.next_deduction),
    )
    return {"id": result["lastrowid"], "message": "添加成功"}


@router.put("/dca/{plan_id}")
def update_dca(plan_id: int, body: DcaUpdateBody):
    existing = query_one("SELECT * FROM dca_plans WHERE id = ? AND user_id = ?", (plan_id, get_current_user_id()))
    if not existing:
        raise HTTPException(404, "定投计划不存在")

    updates = {}
    if body.cycle is not None:
        updates["cycle"] = body.cycle
    if body.cycle_day is not None:
        updates["cycle_day"] = body.cycle_day
    if body.amount is not None:
        updates["amount"] = body.amount
    if body.next_deduction is not None:
        updates["next_deduction"] = body.next_deduction

    if not updates:
        return {"message": "无更新"}

    # updated_at is special: set to current time, not bound from user input
    set_parts = [f"{k} = ?" for k in updates]
    set_parts.append("updated_at = ?")
    values = list(updates.values())
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    values.append(now)
    values.append(plan_id)

    execute(f"UPDATE dca_plans SET {', '.join(set_parts)} WHERE id = ?", tuple(values))
    return {"message": "更新成功"}


@router.delete("/dca/{plan_id}")
def delete_dca(plan_id: int):
    existing = query_one("SELECT * FROM dca_plans WHERE id = ? AND user_id = ?", (plan_id, get_current_user_id()))
    if not existing:
        raise HTTPException(404, "定投计划不存在")
    execute("DELETE FROM dca_plans WHERE id = ? AND user_id = ?", (plan_id, get_current_user_id()))
    return {"message": "已删除"}


@router.post("/dca/{plan_id}/toggle")
def toggle_dca(plan_id: int):
    existing = query_one("SELECT * FROM dca_plans WHERE id = ? AND user_id = ?", (plan_id, get_current_user_id()))
    if not existing:
        raise HTTPException(404, "定投计划不存在")
    new_active = 0 if existing["active"] else 1
    execute("UPDATE dca_plans SET active = ? WHERE id = ?", (new_active, plan_id))
    return {"active": new_active, "message": "已暂停" if new_active == 0 else "已激活"}


class MemoRequest(BaseModel):
    provider: str = ""    # 留空从 settings 读取
    apiKey: str = ""      # 留空从 settings 读取
    model: str = ""       # 留空使用默认


@router.post("/dca/{plan_id}/memo")
async def generate_memo(plan_id: int, body: MemoRequest):
    """为定投计划生成 AI 备忘录（apiKey 留空则使用已保存的配置）"""
    plan = query_one("SELECT * FROM dca_plans WHERE id = ? AND user_id = ?", (plan_id, get_current_user_id()))
    if not plan:
        raise HTTPException(404, "定投计划不存在")

    # 获取实时行情（AKShare 优先，东方财富兜底）
    code = plan["stock_code"]
    price, change_pct = None, None
    try:
        q = ak_get_quote(code)
        if q:
            price = q.get("price")
            change_pct = q.get("change_pct")
    except Exception:
        pass
    if price is None:
        market = get_market(code)
        secid = f"{market}.{code}"
        try:
            raw = run_curl(f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f170,f58")
            q = json.loads(raw).get("data", {})
            price = q.get("f43", 0) / 100 if q.get("f43") else None
            change_pct = q.get("f170", 0) / 100 if q.get("f170") else None
        except Exception:
            pass

    # 计算距下次扣款天数
    days_left = "未知"
    if plan["next_deduction"]:
        try:
            nd = date.fromisoformat(plan["next_deduction"])
            days_left = str((nd - date.today()).days)
        except Exception:
            pass

    cycle_label = {"daily": "每天", "weekly": "每周", "biweekly": "双周", "monthly": "每月"}.get(plan["cycle"], plan["cycle"])
    price_str = f"{price:.2f}" if price else "未知"
    change_str = f"{change_pct:+.2f}%" if change_pct is not None else "未知"

    prompt = f"""你是定投备忘录助手。请用 2-3 句话中文，为以下定投计划生成简短的扣款前提醒：

股票：{plan['stock_name']}（{plan['stock_code']}）
定投周期：{cycle_label}
每期金额：{plan['amount']} 元
下次扣款日：{plan['next_deduction'] or '未设置'}（距今天 {days_left} 天）
当前股价：{price_str}（今日涨跌 {change_str}）

要求：
- 第一句：提醒还有多少天扣款
- 第二句：结合当前涨跌给出简短建议（继续定投/稍微观望等）
- 不要超过 60 字
- 直接输出文本，不要加标题或前缀"""

    reply = await ai_chat(
        prompt,
        function="chat",
        provider=body.provider,
        api_key=body.apiKey,
        model=body.model,
    )

    memo = reply.strip()
    execute("UPDATE dca_plans SET memo = ? WHERE id = ?", (memo, plan_id))
    return {"memo": memo}
