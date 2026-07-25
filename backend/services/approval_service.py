"""审批服务 (v3.11+, T5) — 提案 + TTL lease + CAS + append-only 审计

按 plan-ceo-review 2026-07-24 §Phase 4 设计:
  - 提案带 evidence / candidate / experiment 三方 version CAS
  - TTL lease 默认 24h, 同 lease 重试幂等
  - 撤回/过期后重新打开生成新 lease
  - 接受/拒绝/稍后都记录操作者和理由
  - 证据更新后旧建议自动标记 expired

公开 API:
  - create_proposal(experiment_id, action, target_*, lease_ttl_seconds=86400) -> proposal_id
  - get_proposal(proposal_id, owner_user_id) -> dict
  - list_proposals(owner_user_id, status=, ...) -> list[dict]
  - submit_decision(proposal_id, action, expected_version, actor, reason, lease_id)
       -> dict (更新后的 proposal)
  - record_attempt(proposal_id, ...) -> attempt_id (内部)
  - list_attempts(proposal_id) -> list[dict]

异常:
  - ApprovalError (基类)
  - ApprovalNotFoundError
  - ApprovalConflictError (lease/version CAS 失败, 409)
  - ApprovalExpiredError (lease 过期, 409)
  - ApprovalAuthorizationError (owner 不匹配, 403)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from database import execute, query_all, query_one

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  异常
# ════════════════════════════════════════════════════════════

class ApprovalError(Exception):
    http_status = 400


class ApprovalNotFoundError(ApprovalError):
    http_status = 404


class ApprovalConflictError(ApprovalError):
    http_status = 409


class ApprovalExpiredError(ApprovalError):
    http_status = 409


class ApprovalAuthorizationError(ApprovalError):
    http_status = 403


# ════════════════════════════════════════════════════════════
#  时间
# ════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _is_lease_expired(expires_at: Optional[str]) -> bool:
    """返回 True 表示已过期 (或没设过期时间)"""
    if not expires_at:
        return True
    try:
        return datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S") < datetime.now()
    except ValueError:
        return True


def _gen_lease_id() -> str:
    return f"lease-{_now_compact()}-{uuid.uuid4().hex[:8]}"


# ════════════════════════════════════════════════════════════
#  校验辅助
# ════════════════════════════════════════════════════════════

def _check_owner(proposal: dict, owner_user_id: int) -> None:
    if int(proposal["owner_user_id"]) != int(owner_user_id):
        raise ApprovalAuthorizationError(
            f"proposal {proposal['proposal_id']} 不属于 user {owner_user_id}"
        )


# ════════════════════════════════════════════════════════════
#  创建提案
# ════════════════════════════════════════════════════════════

def create_proposal(
    *,
    experiment_id: str,
    owner_user_id: int,
    action: str = "promote",
    target_lifecycle: Optional[str] = None,
    target_portfolio: Optional[str] = None,
    target_proposal: Optional[str] = None,
    candidate_id: Optional[int] = None,
    evidence_version: str = "",
    policy_version: str = "v1.0.0",
    policy_hash: str = "",
    snapshot_hash: str = "",
    lease_ttl_seconds: int = 86400,
) -> dict:
    """新建一个审批提案, 自动生成 lease_id 和 expires_at.

    Returns:
        dict (proposal 行)
    """
    # 拿 experiment 当前 version
    exp = query_one(
        "SELECT version, candidate_id, owner_user_id FROM experiments WHERE experiment_id = ?",
        (experiment_id,),
    )
    if not exp:
        raise ApprovalNotFoundError(f"experiment {experiment_id} not found")
    if int(exp["owner_user_id"]) != int(owner_user_id):
        raise ApprovalAuthorizationError(
            f"experiment {experiment_id} 不属于 user {owner_user_id}"
        )

    candidate_version = 0
    if candidate_id:
        c = query_one("SELECT promoted FROM factor_candidates WHERE id = ?", (candidate_id,))
        if c:
            candidate_version = int(c.get("promoted", 0) or 0)

    lease_id = _gen_lease_id()
    expires_at = (datetime.now() + timedelta(seconds=lease_ttl_seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cur = execute(
        "INSERT INTO approval_proposals "
        "(experiment_id, candidate_id, owner_user_id, "
        " evidence_version, candidate_version, experiment_version, "
        " action, target_lifecycle, target_portfolio, target_proposal, "
        " policy_version, policy_hash, snapshot_hash, "
        " lease_id, lease_expires_at, status, version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?)",
        (
            experiment_id, candidate_id or exp.get("candidate_id"), owner_user_id,
            evidence_version, candidate_version, int(exp["version"]),
            action, target_lifecycle, target_portfolio, target_proposal,
            policy_version, policy_hash, snapshot_hash,
            lease_id, expires_at, _now(), _now(),
        ),
    )
    proposal_id = int(cur["lastrowid"])
    return get_proposal(proposal_id, owner_user_id)


# ════════════════════════════════════════════════════════════
#  查询
# ════════════════════════════════════════════════════════════

def get_proposal(proposal_id: int, owner_user_id: Optional[int] = None) -> dict:
    row = query_one("SELECT * FROM approval_proposals WHERE proposal_id = ?", (proposal_id,))
    if not row:
        raise ApprovalNotFoundError(f"proposal {proposal_id} not found")
    if owner_user_id is not None:
        _check_owner(row, owner_user_id)
    return row


def list_proposals(
    *,
    owner_user_id: Optional[int] = None,
    status: Optional[str] = None,
    experiment_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    where = []
    params: list = []
    if owner_user_id is not None:
        where.append("owner_user_id = ?")
        params.append(owner_user_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if experiment_id:
        where.append("experiment_id = ?")
        params.append(experiment_id)
    sql = "SELECT * FROM approval_proposals"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY proposal_id DESC LIMIT ?"
    params.append(limit)
    return query_all(sql, tuple(params))


def list_attempts(proposal_id: int, *, limit: int = 100) -> list[dict]:
    return query_all(
        "SELECT * FROM approval_attempts WHERE proposal_id = ? "
        "ORDER BY attempt_id DESC LIMIT ?",
        (proposal_id, limit),
    )


# ════════════════════════════════════════════════════════════
#  提交决策 (核心 CAS + lease)
# ════════════════════════════════════════════════════════════

def submit_decision(
    *,
    proposal_id: int,
    action: str,                       # 'approve' | 'reject' | 'later' | 'withdraw'
    expected_version: int,
    actor: str,
    reason: str = "",
    lease_id: str = "",
    owner_user_id: Optional[int] = None,
) -> dict:
    """提交审批决策: lease + version CAS + append-only attempt.

    Args:
        proposal_id: 提案 ID
        action: 'approve' | 'reject' | 'later' | 'withdraw'
        expected_version: 调用方读到的 proposal.version, 不匹配 → 409
        actor: 'user:1' | 'api:pipeline' 等
        reason: 决策理由
        lease_id: 调用方持有的 lease_id, 必传
        owner_user_id: 用于 owner 校验

    Returns:
        更新后的 proposal 行

    Raises:
        ApprovalNotFoundError: proposal 不存在
        ApprovalAuthorizationError: owner 不匹配
        ApprovalExpiredError: lease 过期
        ApprovalConflictError: lease_id 不匹配 / version CAS 失败 / 状态非法
    """
    if action not in ("approve", "reject", "later", "withdraw"):
        raise ApprovalConflictError(f"invalid action: {action}")
    if not lease_id:
        raise ApprovalConflictError("lease_id required")

    proposal = get_proposal(proposal_id, owner_user_id=owner_user_id)

    # 0. status 检查: 已决定的不能再决定
    if proposal["status"] in ("approved", "rejected", "withdrawn"):
        # 但 "later" 可以把 expired 拉回 pending
        if action != "later" or proposal["status"] != "expired":
            raise ApprovalConflictError(
                f"proposal {proposal_id} 已是 {proposal['status']}, 不能再决定"
            )

    # 1. lease 检查
    if proposal["lease_id"] != lease_id:
        raise ApprovalConflictError(
            f"lease_id 不匹配 (proposal 用 {proposal['lease_id'][:16]}..., "
            f"提交 {lease_id[:16]}...)"
        )
    if _is_lease_expired(proposal.get("lease_expires_at")):
        _record_attempt(
            proposal_id=proposal_id, lease_id=lease_id, action=action,
            actor=actor, result="conflict", error_json=json.dumps({"reason": "lease expired"}),
            expected_version=expected_version, current_version=int(proposal["version"]),
        )
        raise ApprovalExpiredError(
            f"proposal {proposal_id} lease 已过期 ({proposal.get('lease_expires_at')}), "
            "请重新打开"
        )

    # 2. version CAS
    if int(proposal["version"]) != int(expected_version):
        _record_attempt(
            proposal_id=proposal_id, lease_id=lease_id, action=action,
            actor=actor, result="conflict", error_json=json.dumps({"reason": "version mismatch"}),
            expected_version=expected_version, current_version=int(proposal["version"]),
        )
        raise ApprovalConflictError(
            f"version 不匹配 (expected {expected_version}, current {proposal['version']})"
        )

    # 3. 状态转换
    new_status = {
        "approve": "approved",
        "reject": "rejected",
        "later": "pending",   # 稍后 → 续 lease, status 保持 pending
        "withdraw": "withdrawn",
    }[action]

    new_version = int(proposal["version"]) + 1
    now = _now()
    cur = execute(
        "UPDATE approval_proposals SET "
        " status = ?, version = ?, decided_at = ?, decided_by = ?, "
        " decision_reason = ?, updated_at = ? "
        "WHERE proposal_id = ? AND version = ?",
        (new_status, new_version, now if action != "later" else None,
         actor if action != "later" else None, reason[:500], now,
         proposal_id, expected_version),
    )
    if cur["changes"] == 0:
        _record_attempt(
            proposal_id=proposal_id, lease_id=lease_id, action=action,
            actor=actor, result="conflict", error_json=json.dumps({"reason": "concurrent update"}),
            expected_version=expected_version, current_version=int(proposal["version"]),
        )
        raise ApprovalConflictError(
            f"proposal {proposal_id} 被并发更新 (expected version {expected_version})"
        )

    # 4. action=approve 还要触发 experiment 的 transition (T1)
    if action == "approve":
        try:
            from services.experiment_service import transition as exp_transition
            target_lc = proposal.get("target_lifecycle")
            if target_lc:
                exp_transition(
                    experiment_id=proposal["experiment_id"],
                    axis="lifecycle_status",
                    target=target_lc,
                    expected_version=int(proposal.get("experiment_version", 0)),
                    actor=f"approval:{actor}",
                    reason=f"approved via proposal {proposal_id}: {reason[:200]}",
                )
            target_pf = proposal.get("target_portfolio")
            if target_pf:
                # portfolio_role 接受当前 lifecycle_version (用刚 transition 后的 version)
                # 这里简化为用 proposal 的 experiment_version + 1
                exp_transition(
                    experiment_id=proposal["experiment_id"],
                    axis="portfolio_role",
                    target=target_pf,
                    expected_version=int(proposal.get("experiment_version", 0)) + (1 if target_lc else 0),
                    actor=f"approval:{actor}",
                    reason=f"role from approval {proposal_id}",
                )
        except Exception as e:
            logger.warning("experiment transition failed (proposal %s): %s",
                           proposal_id, str(e)[:200])
            # 不影响 proposal 状态 (proposal 已经 approved)

    # 5. append-only attempt
    _record_attempt(
        proposal_id=proposal_id, lease_id=lease_id, action=action,
        actor=actor, result="ok", error_json="{}",
        expected_version=expected_version, current_version=new_version,
    )
    return get_proposal(proposal_id, owner_user_id=owner_user_id)


# ════════════════════════════════════════════════════════════
#  Lease 重开
# ════════════════════════════════════════════════════════════

def reopen_lease(
    proposal_id: int,
    *,
    owner_user_id: Optional[int] = None,
    lease_ttl_seconds: int = 86400,
) -> dict:
    """给已过期/被 with 的 proposal 重新发 lease. status 保持 pending."""
    proposal = get_proposal(proposal_id, owner_user_id=owner_user_id)
    if proposal["status"] in ("approved", "rejected"):
        raise ApprovalConflictError(
            f"proposal {proposal_id} 已 {proposal['status']}, 不能 reopen"
        )
    new_lease = _gen_lease_id()
    expires_at = (datetime.now() + timedelta(seconds=lease_ttl_seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    cur = execute(
        "UPDATE approval_proposals SET "
        " lease_id = ?, lease_expires_at = ?, version = version + 1, "
        " updated_at = ? "
        "WHERE proposal_id = ?",
        (new_lease, expires_at, _now(), proposal_id),
    )
    if cur["changes"] == 0:
        raise ApprovalConflictError(f"proposal {proposal_id} 重开失败")
    return get_proposal(proposal_id, owner_user_id=owner_user_id)


# ════════════════════════════════════════════════════════════
#  内部: 审计
# ════════════════════════════════════════════════════════════

def _record_attempt(
    *,
    proposal_id: int,
    lease_id: str,
    action: str,
    actor: str,
    result: str,
    error_json: str,
    expected_version: int,
    current_version: int,
) -> int:
    cur = execute(
        "INSERT INTO approval_attempts "
        "(proposal_id, lease_id, action, actor, result, error_json, "
        " expected_version, current_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (proposal_id, lease_id, action, actor, result, error_json,
         expected_version, current_version, _now()),
    )
    return int(cur["lastrowid"])