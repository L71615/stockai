"""审批 API — /api/pipeline/proposals/* (T5)

REST endpoints:
  GET    /api/pipeline/proposals                  列表 (按 status 过滤)
  POST   /api/pipeline/proposals                  创建提案 (from experiment_id + action + target_*)
  GET    /api/pipeline/proposals/{id}             详情
  GET    /api/pipeline/proposals/{id}/attempts    审计日志
  POST   /api/pipeline/proposals/{id}/accept      接受 (CAS + lease)
  POST   /api/pipeline/proposals/{id}/reject      拒绝
  POST   /api/pipeline/proposals/{id}/later       稍后 (续 lease)
  POST   /api/pipeline/proposals/{id}/withdraw    撤回
  POST   /api/pipeline/proposals/{id}/reopen      重开发 lease

CAS 必填 header/body 字段:
  expected_version: int       proposal.version CAS
  lease_id: str                proposal.lease_id 校验

错误码:
  403  owner 不匹配
  404  proposal 不存在
  409  lease 过期 / version 不匹配 / 状态非法
  422  入参缺失
"""
import logging

from fastapi import APIRouter, HTTPException

from dependencies import get_current_user_id
from services.approval_service import (
    create_proposal,
    get_proposal,
    list_proposals,
    list_attempts,
    submit_decision,
    submit_bulk_decision,
    reopen_lease,
    BULK_LEASE_TTL_SECONDS,
    ApprovalNotFoundError,
    ApprovalConflictError,
    ApprovalExpiredError,
    ApprovalAuthorizationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline/proposals", tags=["Approvals"])


def _to_http(e: Exception) -> HTTPException:
    if isinstance(e, (ApprovalNotFoundError,)):
        return HTTPException(404, str(e)[:200])
    if isinstance(e, ApprovalAuthorizationError):
        return HTTPException(403, str(e)[:200])
    if isinstance(e, (ApprovalConflictError, ApprovalExpiredError)):
        return HTTPException(409, str(e)[:200])
    return HTTPException(500, str(e)[:200])


@router.get("")
def list_my_proposals(
    status: str = "",
    limit: int = 50,
):
    """列当前用户的提案 (按 status 过滤)."""
    user_id = get_current_user_id()
    return {
        "proposals": list_proposals(
            owner_user_id=user_id,
            status=status or None,
            limit=limit,
        ),
        "count": 0,  # 由调用方算
    }


@router.post("")
def create_new_proposal(payload: dict):
    """新建提案.

    Body:
      {
        "experiment_id": "exp-...",
        "action": "promote" | "demote" | "retire",
        "target_lifecycle": "validated" | "paper" | "champion" | ...   (可选)
        "target_portfolio": "paper" | "champion" | ...                 (可选)
        "evidence_version": "v1",
        "policy_version": "v1.0.0",
        "policy_hash": "...",
        "snapshot_hash": "...",
        "lease_ttl_seconds": 86400
      }
    """
    user_id = get_current_user_id()
    experiment_id = payload.get("experiment_id")
    if not experiment_id:
        raise HTTPException(422, "experiment_id required")
    try:
        proposal = create_proposal(
            experiment_id=experiment_id,
            owner_user_id=user_id,
            action=payload.get("action", "promote"),
            target_lifecycle=payload.get("target_lifecycle"),
            target_portfolio=payload.get("target_portfolio"),
            target_proposal=payload.get("target_proposal"),
            candidate_id=payload.get("candidate_id"),
            evidence_version=payload.get("evidence_version", ""),
            policy_version=payload.get("policy_version", "v1.0.0"),
            policy_hash=payload.get("policy_hash", ""),
            snapshot_hash=payload.get("snapshot_hash", ""),
            decision_score=float(payload.get("decision_score", 0.0)),
            lease_ttl_seconds=int(payload.get("lease_ttl_seconds", 86400)),
        )
        return proposal
    except (ApprovalNotFoundError, ApprovalAuthorizationError,
            ApprovalConflictError, ApprovalExpiredError) as e:
        raise _to_http(e)


@router.get("/{proposal_id}")
def get_proposal_detail(proposal_id: int):
    user_id = get_current_user_id()
    try:
        return get_proposal(proposal_id, owner_user_id=user_id)
    except (ApprovalNotFoundError, ApprovalAuthorizationError) as e:
        raise _to_http(e)


@router.get("/{proposal_id}/attempts")
def get_proposal_attempts(proposal_id: int):
    """审计日志 (append-only)."""
    user_id = get_current_user_id()
    try:
        # 先确认 owner
        get_proposal(proposal_id, owner_user_id=user_id)
        return {"attempts": list_attempts(proposal_id), "proposal_id": proposal_id}
    except (ApprovalNotFoundError, ApprovalAuthorizationError) as e:
        raise _to_http(e)


@router.post("/bulk-approve")
def bulk_approve(payload: dict):
    """一键接受高分提案 (v4.1 1B.3).

    Body:
      {
        "proposal_ids": [101, 102, 103, ...],       # 必填
        "min_score": 0.85,                           # 必填, decision_score 阈值
        "stock_codes": {101: "600519", 102: "000001"},  # 可选, 只对提供的 proposal_id 创建 pending_buy
        "order_params": {                            # 可选, 每条 pending_buy 的参数
          "101": {"shares": 100, "hold_days": 1, "slippage_bps": 10.0}
        },
        "reason": "auto accept high-score batch"
      }

    Returns:
      {
        "succeeded": [proposal_id, ...],
        "rejected_low_score": [{...}],
        "failed": [{...}],
        "pending_orders_created": [order_id, ...],
        "lease_expires_at": "...",
        "min_score": 0.85
      }

    Notes:
      - 全部 approve + pending_buy INSERT 在一个事务里,任何一条失败全部回滚
      - lease TTL = 60s (vs 单个 24h),防止 stale batch
      - experiment transition 失败仅记日志,不回滚 proposal
    """
    user_id = get_current_user_id()
    proposal_ids = payload.get("proposal_ids") or []
    min_score = payload.get("min_score")
    if not proposal_ids:
        raise HTTPException(422, "proposal_ids required")
    if min_score is None:
        raise HTTPException(422, "min_score required")
    try:
        return submit_bulk_decision(
            proposal_ids=list(proposal_ids),
            min_score=float(min_score),
            actor=f"user:{user_id}",
            owner_user_id=user_id,
            stock_codes=payload.get("stock_codes") or {},
            order_params=payload.get("order_params") or {},
            default_shares=int(payload.get("default_shares", 100)),
            default_hold_days=int(payload.get("default_hold_days", 1)),
            default_slippage_bps=float(payload.get("default_slippage_bps", 10.0)),
            reason=str(payload.get("reason", "bulk_approve"))[:500],
        )
    except (ApprovalNotFoundError, ApprovalAuthorizationError,
            ApprovalConflictError, ApprovalExpiredError) as e:
        raise _to_http(e)


@router.post("/{proposal_id}/accept")
def accept_proposal(proposal_id: int, payload: dict):
    """接受提案 — CAS + lease 校验."""
    return _do_decision(proposal_id, "approve", payload)


@router.post("/{proposal_id}/reject")
def reject_proposal(proposal_id: int, payload: dict):
    return _do_decision(proposal_id, "reject", payload)


@router.post("/{proposal_id}/later")
def later_proposal(proposal_id: int, payload: dict):
    """稍后 — status 保持 pending, lease 不变 (或续 lease by reopen)."""
    return _do_decision(proposal_id, "later", payload)


@router.post("/{proposal_id}/withdraw")
def withdraw_proposal(proposal_id: int, payload: dict):
    return _do_decision(proposal_id, "withdraw", payload)


@router.post("/{proposal_id}/reopen")
def reopen_proposal(proposal_id: int, payload: dict | None = None):
    """重新打开 (发新 lease). 仅 owner 可调."""
    user_id = get_current_user_id()
    payload = payload or {}
    try:
        return reopen_lease(
            proposal_id,
            owner_user_id=user_id,
            lease_ttl_seconds=int(payload.get("lease_ttl_seconds", 86400)),
        )
    except (ApprovalNotFoundError, ApprovalAuthorizationError,
            ApprovalConflictError, ApprovalExpiredError) as e:
        raise _to_http(e)


def _do_decision(proposal_id: int, action: str, payload: dict):
    """公共决策路径."""
    user_id = get_current_user_id()
    expected_version = payload.get("expected_version")
    lease_id = payload.get("lease_id", "")
    reason = payload.get("reason", "")

    if expected_version is None:
        raise HTTPException(422, "expected_version required")
    try:
        result = submit_decision(
            proposal_id=proposal_id,
            action=action,
            expected_version=int(expected_version),
            actor=f"user:{user_id}",
            reason=reason,
            lease_id=lease_id,
            owner_user_id=user_id,
        )

        # v4.1 1A.3: 接受成功 → 自动创建 pending_buy
        # 仅当 payload 含 stock_code 时触发 (UI 决定是否下单, 不是 implicit)
        if action == "approve":
            stock_code = payload.get("stock_code")
            if stock_code:
                try:
                    from services.t1_watcher import create_pending_order
                    order = create_pending_order(
                        user_id=user_id,
                        stock_code=stock_code,
                        stock_name=payload.get("stock_name", ""),
                        shares=int(payload.get("shares", 100)),
                        planned_entry_price=payload.get("planned_entry_price"),
                        planned_exit_price=payload.get("planned_exit_price"),
                        hold_days=int(payload.get("hold_days", 1)),
                        slippage_bps=float(payload.get("slippage_bps", 10.0)),
                        entry_date=payload.get("entry_date"),
                        reason=f"pipeline_proposal:{proposal_id}",
                        source="pipeline_proposal",
                        proposal_id=proposal_id,
                    )
                    result["pending_buy"] = order
                except Exception as e:
                    logger.warning("v4.1 1A.3: 创建 pending_buy 失败 (proposal %s): %s", proposal_id, e)
                    result["pending_buy_error"] = str(e)
        return result
    except (ApprovalNotFoundError, ApprovalAuthorizationError,
            ApprovalConflictError, ApprovalExpiredError) as e:
        raise _to_http(e)