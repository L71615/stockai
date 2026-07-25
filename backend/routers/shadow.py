"""影子组合查询 API — /api/pipeline/shadow (T5)

GET /api/pipeline/shadow                          列表
GET /api/pipeline/shadow/{portfolio_id}           详情
GET /api/pipeline/shadow/{portfolio_id}/snapshots 快照列表 (按日期范围)
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from dependencies import get_current_user_id
from services.shadow_portfolio_service import (
    get_portfolio,
    list_portfolios,
    get_snapshots,
    ShadowPortfolioNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline/shadow", tags=["Shadow"])


@router.get("")
def list_my_shadow_portfolios(limit: int = Query(50, le=200)):
    user_id = get_current_user_id()
    rows = list_portfolios(owner_user_id=user_id)[:limit]
    return {"portfolios": rows, "count": len(rows)}


@router.get("/{portfolio_id}")
def get_shadow_detail(portfolio_id: int):
    user_id = get_current_user_id()
    try:
        p = get_portfolio(portfolio_id)
        if int(p.get("owner_user_id", -1)) != int(user_id):
            raise HTTPException(403, "portfolio 不属于当前 user")
        return p
    except ShadowPortfolioNotFoundError as e:
        raise HTTPException(404, str(e)[:200])


@router.get("/{portfolio_id}/snapshots")
def get_shadow_snapshots(
    portfolio_id: int,
    start: str = Query("", description="YYYY-MM-DD"),
    end: str = Query("", description="YYYY-MM-DD"),
    limit: int = Query(500, le=2000),
):
    user_id = get_current_user_id()
    try:
        p = get_portfolio(portfolio_id)
        if int(p.get("owner_user_id", -1)) != int(user_id):
            raise HTTPException(403, "portfolio 不属于当前 user")
        rows = get_snapshots(
            portfolio_id, start=start or None, end=end or None, limit=limit,
        )
        return {"snapshots": rows, "count": len(rows)}
    except ShadowPortfolioNotFoundError as e:
        raise HTTPException(404, str(e)[:200])