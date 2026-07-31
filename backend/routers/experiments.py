"""实验查询 API — /api/pipeline/experiments (T5)

GET /api/pipeline/experiments                列表 (按 lifecycle_status / portfolio_role 过滤)
GET /api/pipeline/experiments/{id}           详情
GET /api/pipeline/experiments/{id}/events    审计事件

注: C1 反事实端点(/api/pipeline/counterfactual, /api/pipeline/retrospectives)
    已在 routers/counterfactual.py 独立实现,避免与本 router 的 /experiments 前缀冲突。
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from dependencies import get_current_user_id
from services.experiment_service import (
    get_experiment,
    list_experiments,
    list_events,
    ExperimentNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline/experiments", tags=["Experiments"])


@router.get("")
def list_my_experiments(
    lifecycle_status: str = Query("", description="candidate|validated|blocked|stale|paper|champion|retired|rejected"),
    portfolio_role: str = Query("", description="none|baseline|paper|champion|challenger"),
    proposal_status: str = Query("", description="pending|approved|rejected|expired|withdrawn"),
    limit: int = Query(50, le=200),
):
    """列当前用户的实验."""
    user_id = get_current_user_id()
    rows = list_experiments(
        owner_user_id=user_id,
        lifecycle_status=lifecycle_status or None,
        portfolio_role=portfolio_role or None,
        proposal_status=proposal_status or None,
        limit=limit,
    )
    return {"experiments": rows, "count": len(rows)}


@router.get("/champion-dryrun")
def get_champion_dryrun(
    pool: str = Query("hs300"),
    lookback_days: int = Query(60, ge=30, le=365),
    replace_threshold: float = Query(1.5, ge=1.0, le=5.0),
):
    """v4.2 候选 — Auto Champion Replacement DRY-RUN ONLY

    列出所有未 promoted 的 factor_candidates,计算每个相对 champion 的 IR 比,
    标记 would_replace。实际替换仍需人工审批,永不自动。
    """
    try:
        from services.experiment_service import compute_champion_dry_run
        return compute_champion_dry_run(
            stock_pool=pool,
            lookback_days=lookback_days,
            replace_threshold=replace_threshold,
        )
    except Exception as e:
        logger.error("champion dry-run failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"Champion dry-run 失败: {str(e)[:200]}")


@router.get("/{experiment_id}")
def get_experiment_detail(experiment_id: str):
    user_id = get_current_user_id()
    try:
        exp = get_experiment(experiment_id)
        if int(exp.get("owner_user_id", -1)) != int(user_id):
            raise HTTPException(403, "experiment 不属于当前 user")
        return exp
    except ExperimentNotFoundError as e:
        raise HTTPException(404, str(e)[:200])


@router.get("/{experiment_id}/events")
def get_experiment_events(experiment_id: str, limit: int = Query(100, le=500)):
    """审计事件 (append-only)."""
    user_id = get_current_user_id()
    try:
        exp = get_experiment(experiment_id)
        if int(exp.get("owner_user_id", -1)) != int(user_id):
            raise HTTPException(403, "experiment 不属于当前 user")
        return {"events": list_events(experiment_id=experiment_id, limit=limit)}
    except ExperimentNotFoundError as e:
        raise HTTPException(404, str(e)[:200])