"""反事实报告 API — v4.0 C1

GET /api/pipeline/counterfactual             反事实汇总(approved vs rejected 实际表现对比)
GET /api/pipeline/retrospectives             反事实详情列表(why / what happened / lesson)

设计: 直接读 proposal_outcomes + proposal_retrospectives(已有表,无 schema 变更)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

from services.retrospective_service import (
    counterfactual_summary,
    list_retrospectives,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["Counterfactual"])


@router.get("/counterfactual")
def get_counterfactual(
    days: int = Query(30, ge=1, le=365, description="回看天数,默认 30"),
    baseline: str = Query("csi300", description="基准代码,默认 csi300"),
):
    """反事实汇总: approved vs rejected 的实际表现对比

    Returns:
        {
            "window": {"since", "until"},
            "baseline_code": str,
            "accepted": {count, avg_fwd_return, avg_baseline_diff, good_rate, ...},
            "rejected": {count, avg_fwd_return, avg_baseline_diff, good_rate, ...},
            "edge": float,                      # accepted - rejected 平均收益差
            "interpretation": str,              # 人话解读
            "v4_metadata": {phase, since, data_source}
        }
    """
    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    summary = counterfactual_summary(since=since, baseline_code=baseline)
    summary["v4_metadata"] = {
        "phase": "C1",
        "days": days,
        "data_source": "proposal_outcomes",
    }
    return summary


@router.get("/retrospectives")
def get_retrospectives(
    experiment_id: Optional[str] = Query(None),
    decision: Optional[str] = Query(None, description="approved/rejected/withdrawn"),
    limit: int = Query(20, ge=1, le=100),
):
    """反事实详情列表 — 每条记录包含 hypothesis / evidence / realized / lesson

    Returns:
        {"retrospectives": [...], "count": N, "v4_metadata": {...}}
    """
    rows = list_retrospectives(
        experiment_id=experiment_id,
        decision=decision,
        limit=limit,
    )
    return {
        "retrospectives": rows,
        "count": len(rows),
        "v4_metadata": {
            "phase": "C1",
            "filters": {"experiment_id": experiment_id, "decision": decision, "limit": limit},
        },
    }
