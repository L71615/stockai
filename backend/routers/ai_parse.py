"""v5.1 — AI 解析交易路由

POST /api/ai/parse-transactions  接收粘贴文本 → AI 解析 + 后置校验 → 返回预览
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from dependencies import get_current_user_id
from services.ai_parse_transactions import (
    TEMPLATE,
    parse_transactions_with_ai,
    lookup_stock_names,
)

router = APIRouter()


class ParseRequest(BaseModel):
    text: str  # 用户粘贴的文本


@router.post("/parse-transactions")
async def parse_transactions(req: ParseRequest):
    """AI 批量解析 — 只解析, 不写库

    Returns:
        {
            "template": "...",      # 给前端展示用
            "transactions": [...],  # 通过校验的交易
            "errors": [...],        # 单行解析/校验失败原因
            "summary": {...},       # 行数/成功/失败统计
        }
    """
    user_id = get_current_user_id()

    result = await parse_transactions_with_ai(req.text, user_id)

    # 补全股票名称(给前端预览用)
    codes = [t["code"] for t in result["transactions"]]
    name_map = lookup_stock_names(codes)
    for tx in result["transactions"]:
        tx["stock_name"] = name_map.get(tx["code"], tx["code"])

    return {
        "template": TEMPLATE,
        **result,
    }