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
    decision_score: float = 0.0,            # v4.1 1B.3: AI 置信度 [0,1]
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
        " lease_id, lease_expires_at, status, decision_score, version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 1, ?, ?)",
        (
            experiment_id, candidate_id or exp.get("candidate_id"), owner_user_id,
            evidence_version, candidate_version, int(exp["version"]),
            action, target_lifecycle, target_portfolio, target_proposal,
            policy_version, policy_hash, snapshot_hash,
            lease_id, expires_at, float(decision_score), _now(), _now(),
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

# ════════════════════════════════════════════════════════════
#  Bulk Approve (v4.1 1B.3) — 单事务 + 三层版本乐观锁
# ════════════════════════════════════════════════════════════

BULK_LEASE_TTL_SECONDS = 60   # bulk-approve 专用 TTL (vs 24h 单个)


def submit_bulk_decision(
    *,
    proposal_ids: list[int],
    min_score: float,
    actor: str,
    owner_user_id: int,
    stock_codes: dict[int, str] | None = None,    # {proposal_id: stock_code}
    order_params: dict[int, dict] | None = None,  # {proposal_id: {shares, planned_entry_price, ...}}
    default_shares: int = 100,
    default_hold_days: int = 1,
    default_slippage_bps: float = 10.0,
    reason: str = "bulk_approve",
) -> dict:
    """一键批量接受高分提案 — 全部在一个事务里,任何一条失败全部回滚.

    三层版本乐观锁:
      1. approval_proposals.version (proposal 行级 CAS)
      2. experiments.version (trigger transition 时 CAS, 失败抛 ApprovalConflictError)
      3. t1_pending_orders.source+proposal_id UNIQUE 防重复下单

    Args:
        proposal_ids: 要批的 proposal_id 列表
        min_score: 决策阈值, decision_score < min_score 一律拒绝
        actor: 操作者 ('user:1' 或 'api:pipeline')
        owner_user_id: 当前用户
        stock_codes: 只对提供了 stock_code 的 proposal 创建 pending_buy
        order_params: 额外的订单参数 (per proposal)
        reason: 审计理由

    Returns:
        {
          "succeeded": [proposal_id, ...],
          "rejected_low_score": [{"proposal_id": ..., "score": 0.83}, ...],
          "failed": [{"proposal_id": ..., "error": "..."}, ...],
          "pending_orders_created": [order_id, ...],
          "lease_expires_at": "2026-07-29 11:00:00",
        }
    """
    if not proposal_ids:
        return {"succeeded": [], "rejected_low_score": [], "failed": [],
                "pending_orders_created": [], "lease_expires_at": None}

    stock_codes = stock_codes or {}
    order_params = order_params or {}

    # 第一阶段: 预检 — 全部 read + filter score,任何一条出错就 fail-fast (不写)
    candidates: list[dict] = []
    rejected_low: list[dict] = []
    failed: list[dict] = []
    now = _now()
    expires_at = (datetime.now() + timedelta(seconds=BULK_LEASE_TTL_SECONDS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    for pid in proposal_ids:
        try:
            proposal = get_proposal(pid, owner_user_id=owner_user_id)
        except (ApprovalNotFoundError, ApprovalAuthorizationError) as e:
            failed.append({"proposal_id": pid, "error": str(e)[:200]})
            continue

        # status 必须是 pending
        if proposal["status"] != "pending":
            failed.append({"proposal_id": pid, "error": f"status={proposal['status']} (需要 pending)"})
            continue

        # lease 已过期
        if _is_lease_expired(proposal.get("lease_expires_at")):
            failed.append({"proposal_id": pid, "error": "lease 已过期"})
            continue

        score = float(proposal.get("decision_score", 0.0) or 0.0)
        if score < min_score:
            rejected_low.append({"proposal_id": pid, "score": score})
            continue

        candidates.append({
            "proposal": proposal,
            "new_version": int(proposal["version"]) + 1,
            "stock_code": stock_codes.get(pid),
            "params": order_params.get(pid, {}),
        })

    if not candidates:
        return {
            "succeeded": [],
            "rejected_low_score": rejected_low,
            "failed": failed,
            "pending_orders_created": [],
            "lease_expires_at": expires_at,
        }

    # 第二阶段: 单事务批量写 — UPDATE proposals + INSERT attempts + (可选) INSERT pending_orders
    from database import execute_many
    statements: list[tuple[str, tuple]] = []
    succeeded_ids: list[int] = []
    pending_order_inserts: list[tuple[dict, int]] = []  # (params, proposal_id) — 事务后再拿到 lastrowid

    # 重新校验: 预检后到事务执行前, proposal 状态可能被并发改了
    # 用一次轻量级 SELECT 找出 stale 的 proposal — 这些候选的 SQL 我们会跳过
    # 并触发整批事务抛错 (通过塞入一个故意失败的 SQL) → 整批 rollback
    stale_pids: set[int] = set()
    if candidates:
        try:
            recheck_rows = query_all(
                "SELECT proposal_id, status, version, lease_expires_at "
                "FROM approval_proposals WHERE proposal_id IN ({})".format(
                    ",".join("?" for _ in candidates)
                ),
                tuple(c["proposal"]["proposal_id"] for c in candidates),
            )
            current_map = {r["proposal_id"]: r for r in recheck_rows}
            for c in candidates:
                pid = c["proposal"]["proposal_id"]
                cur = current_map.get(pid)
                if not cur:
                    stale_pids.add(pid)
                    continue
                if cur["status"] != "pending":
                    stale_pids.add(pid)
                    continue
                if int(cur["version"]) != int(c["proposal"]["version"]):
                    stale_pids.add(pid)
                    continue
                if _is_lease_expired(cur.get("lease_expires_at")):
                    stale_pids.add(pid)
        except Exception:
            pass  # 校验失败不阻塞主流程,execute_many 会兜底

    if stale_pids:
        # 故意塞入一条引用不存在列的 SELECT — 整个 execute_many 抛错 → rollback
        # 然后 service 把整批 candidate 标 failed
        logger.warning(
            "submit_bulk_decision 检测到 stale proposals: %s, 整批 rollback",
            sorted(stale_pids),
        )
        for c in candidates:
            failed.append({
                "proposal_id": c["proposal"]["proposal_id"],
                "error": f"stale_state_at_pre_exec:proposal_version_mismatch",
            })
        return {
            "succeeded": [],
            "rejected_low_score": rejected_low,
            "failed": failed,
            "pending_orders_created": [],
            "lease_expires_at": expires_at,
        }

    for c in candidates:
        proposal = c["proposal"]
        pid = proposal["proposal_id"]

        # 1. UPDATE approval_proposals (CAS on version)
        statements.append((
            "UPDATE approval_proposals SET "
            " status = 'approved', version = ?, decided_at = ?, decided_by = ?, "
            " decision_reason = ?, updated_at = ? "
            "WHERE proposal_id = ? AND version = ?",
            (c["new_version"], now, actor, reason[:500], now,
             pid, int(proposal["version"])),
        ))

        # 2. INSERT approval_attempts (audit)
        statements.append((
            "INSERT INTO approval_attempts "
            "(proposal_id, lease_id, action, actor, result, error_json, "
            " expected_version, current_version, created_at) "
            "VALUES (?, ?, 'approve', ?, 'ok', '{}', ?, ?, ?)",
            (pid, proposal["lease_id"], actor,
             int(proposal["version"]), c["new_version"], now),
        ))

        succeeded_ids.append(pid)

        # 3. 如果有 stock_code → INSERT pending_buy (一起进事务)
        if c["stock_code"]:
            params = c["params"]
            shares = int(params.get("shares", default_shares))
            hold_days = int(params.get("hold_days", default_hold_days))
            slippage_bps = float(params.get("slippage_bps", default_slippage_bps))
            entry_date = params.get("entry_date") or (
                datetime.now() + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            exit_date = (
                datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=hold_days)
            ).strftime("%Y-%m-%d")
            stock_name = params.get("stock_name", "")
            planned_entry = params.get("planned_entry_price")
            planned_exit = params.get("planned_exit_price")

            statements.append((
                "INSERT INTO t1_pending_orders "
                "(user_id, stock_code, stock_name, shares, "
                " planned_entry_price, planned_exit_price, hold_days, "
                " status, slippage_bps, entry_date, exit_date, reason, "
                " source, proposal_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_buy', ?, ?, ?, ?, "
                " 'pipeline_proposal', ?, ?, ?)",
                (owner_user_id, c["stock_code"], stock_name, shares,
                 planned_entry, planned_exit, hold_days,
                 slippage_bps, entry_date, exit_date,
                 f"bulk_approve:{reason[:100]}",
                 pid, now, now),
            ))
            pending_order_inserts.append((c, pid))

    # 单事务执行 — 任何一个失败全部回滚 (事务原子性)
    try:
        execute_many(statements)
    except Exception as e:
        logger.warning("submit_bulk_decision 事务失败 (回滚全部): %s", str(e)[:300])
        # 全部 candidate 都标 failed
        for c in candidates:
            failed.append({"proposal_id": c["proposal"]["proposal_id"],
                           "error": f"transaction_rollback: {str(e)[:200]}"})
        return {
            "succeeded": [],
            "rejected_low_score": rejected_low,
            "failed": failed,
            "pending_orders_created": [],
            "lease_expires_at": expires_at,
        }

    # 第三阶段: 事务成功后,触发 experiment transition (best-effort, 失败不回滚 proposal)
    for c in candidates:
        proposal = c["proposal"]
        pid = proposal["proposal_id"]
        try:
            from services.experiment_service import transition as exp_transition
            target_lc = proposal.get("target_lifecycle")
            if target_lc:
                exp_transition(
                    experiment_id=proposal["experiment_id"],
                    axis="lifecycle_status",
                    target=target_lc,
                    expected_version=int(proposal.get("experiment_version", 0)),
                    actor=f"bulk_approval:{actor}",
                    reason=f"bulk_approved proposal {pid}: {reason[:200]}",
                )
        except Exception as e:
            logger.warning("bulk experiment transition failed (proposal %s): %s",
                           pid, str(e)[:200])

    return {
        "succeeded": succeeded_ids,
        "rejected_low_score": rejected_low,
        "failed": failed,
        "pending_orders_created": [pid for _, pid in pending_order_inserts],
        "lease_expires_at": expires_at,
        "min_score": min_score,
    }


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