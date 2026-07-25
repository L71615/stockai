"""实验账本服务 (v3.11+) — 三轴状态机 + 版本 CAS + append-only 审计

按 plan-ceo-review 2026-07-24 §Phase 1 设计:
  - 实验状态用三轴 (lifecycle_status / portfolio_role / proposal_status)
  - 数据库是唯一事实源, 状态迁移走版本 CAS
  - 所有迁移写 append-only experiment_run_events
  - 单飞锁 pipeline_lock 防并发

迁移表见 _ALLOWED_TRANSITIONS, 任何不在表里的 from→to 都拒绝.

公开 API:
  - create_experiment(...)
  - get_experiment(experiment_id)
  - list_experiments(filters...)
  - transition(experiment_id, axis, target, expected_version, actor, reason, run_id=None)
  - append_event(experiment_id, run_id, actor, event_type, reason)
  - acquire_pipeline_lock(scope, holder_pid, ttl_seconds)
  - release_pipeline_lock(scope, holder_pid)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from database import execute, execute_many, query_all, query_one

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  异常 (typed errors, 路由层映射到 HTTP)
# ════════════════════════════════════════════════════════════

class ExperimentError(Exception):
    """基类"""
    http_status = 400


class ExperimentNotFoundError(ExperimentError):
    http_status = 404


class ExperimentConflictError(ExperimentError):
    """版本 CAS 冲突, 或违反唯一约束"""
    http_status = 409


class ExperimentTransitionError(ExperimentError):
    """非法状态迁移"""
    http_status = 422


class PipelineLockHeldError(ExperimentError):
    """单飞锁被别的 worker 持有"""
    http_status = 409


# ════════════════════════════════════════════════════════════
#  迁移表 (from → set of allowed to)
# ════════════════════════════════════════════════════════════

# 合法值
LIFECYCLE_STATES = {"candidate", "validated", "blocked", "stale", "rejected", "paper", "champion", "retired"}
PORTFOLIO_ROLES = {"none", "baseline", "paper", "champion", "challenger"}
PROPOSAL_STATUSES = {"pending", "approved", "rejected", "expired", "withdrawn"}

# 迁移白名单
_LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"validated", "blocked", "rejected"},
    "validated": {"paper", "rejected", "stale"},
    "blocked":   {"validated"},        # 新一次跑成功后从 blocked 解锁
    "stale":     {"validated"},        # 有了新证据可以从 stale 复活
    "paper":     {"champion", "retired", "rejected"},
    "champion":  {"retired", "rejected"},
    "rejected":  set(),                # 终态
    "retired":   set(),                # 终态
}
_PORTFOLIO_TRANSITIONS: dict[str, set[str]] = {
    "none":       {"baseline", "paper", "champion", "challenger"},
    "baseline":   {"none"},
    "paper":      {"champion", "challenger", "none"},
    "challenger": {"paper", "none"},
    "champion":   {"none"},            # 被替换时回 none
}
_PROPOSAL_TRANSITIONS: dict[str, set[str]] = {
    "pending":    {"approved", "rejected", "expired", "withdrawn"},
    "approved":   set(),
    "rejected":   set(),
    "expired":    set(),
    "withdrawn":  set(),
}

AXIS_TRANSITIONS = {
    "lifecycle_status": _LIFECYCLE_TRANSITIONS,
    "portfolio_role":   _PORTFOLIO_TRANSITIONS,
    "proposal_status":  _PROPOSAL_TRANSITIONS,
}
AXIS_VALUES = {
    "lifecycle_status": LIFECYCLE_STATES,
    "portfolio_role":   PORTFOLIO_ROLES,
    "proposal_status":  PROPOSAL_STATUSES,
}


# ════════════════════════════════════════════════════════════
#  时间工具
# ════════════════════════════════════════════════════════════

def _now() -> str:
    """ISO 本地时间, 与项目其他表一致"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ════════════════════════════════════════════════════════════
#  实验 CRUD
# ════════════════════════════════════════════════════════════

def create_experiment(
    *,
    owner_user_id: int,
    expr_text: str,
    candidate_id: Optional[int] = None,
    policy_version: str = "v1.0.0",
    snapshot_hash: str = "",
    snapshot: Optional[dict] = None,
    note: str = "",
) -> str:
    """新建一个实验, 返回 experiment_id"""
    exp_id = f"exp-{_now_compact()}-{uuid.uuid4().hex[:6]}"
    execute(
        "INSERT INTO experiments "
        "(experiment_id, owner_user_id, expr_text, candidate_id, policy_version, "
        " snapshot_hash, lifecycle_status, portfolio_role, proposal_status, "
        " version, snapshot_json, note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'candidate', 'none', 'pending', 1, ?, ?, ?, ?)",
        (
            exp_id, owner_user_id, expr_text, candidate_id, policy_version,
            snapshot_hash, json.dumps(snapshot or {}, ensure_ascii=False),
            note, _now(), _now(),
        ),
    )
    append_event(
        experiment_id=exp_id,
        run_id=None,
        actor="system",
        event_type="create",
        reason="experiment created",
    )
    return exp_id


def get_experiment(experiment_id: str) -> dict:
    """取单个实验; 不存在抛 NotFoundError"""
    row = query_one("SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,))
    if not row:
        raise ExperimentNotFoundError(f"experiment {experiment_id} not found")
    return row


def list_experiments(
    *,
    owner_user_id: Optional[int] = None,
    lifecycle_status: Optional[str] = None,
    portfolio_role: Optional[str] = None,
    proposal_status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """按 filter 列实验"""
    where = []
    params: list[Any] = []
    if owner_user_id is not None:
        where.append("owner_user_id = ?")
        params.append(owner_user_id)
    if lifecycle_status:
        where.append("lifecycle_status = ?")
        params.append(lifecycle_status)
    if portfolio_role:
        where.append("portfolio_role = ?")
        params.append(portfolio_role)
    if proposal_status:
        where.append("proposal_status = ?")
        params.append(proposal_status)
    sql = "SELECT * FROM experiments"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    return query_all(sql, tuple(params))


# ════════════════════════════════════════════════════════════
#  状态迁移 (核心 CAS)
# ════════════════════════════════════════════════════════════

def transition(
    *,
    experiment_id: str,
    axis: str,
    target: str,
    expected_version: int,
    actor: str = "system",
    reason: str = "",
    run_id: Optional[int] = None,
    evidence_version: str = "",
) -> dict:
    """三轴状态迁移, 带版本 CAS.

    Args:
        experiment_id: 实验 ID
        axis: 'lifecycle_status' | 'portfolio_role' | 'proposal_status'
        target: 目标状态值
        expected_version: 调用方读到的当前 version, 不匹配抛 409
        actor: 'system' | 'user:<id>' | 'api:<endpoint>'
        reason: 迁移理由, 入审计
        run_id: 关联 run, 可选
        evidence_version: 关联 evidence version 字符串, 可选

    Returns:
        更新后的实验行 dict

    Raises:
        ExperimentNotFoundError: 实验不存在
        ExperimentTransitionError: 非法迁移 (from→to 不在白名单)
        ExperimentConflictError: version CAS 失败 (rowcount=0)
    """
    if axis not in AXIS_TRANSITIONS:
        raise ExperimentTransitionError(f"unknown axis: {axis}")
    if target not in AXIS_VALUES[axis]:
        raise ExperimentTransitionError(
            f"invalid target {target!r} for axis {axis}; "
            f"allowed: {sorted(AXIS_VALUES[axis])}"
        )

    row = get_experiment(experiment_id)
    current_value = row[axis]
    current_version = int(row["version"])

    if current_value == target:
        # 幂等 no-op: 不变 version, 不写审计, 直接返回
        return row

    allowed = AXIS_TRANSITIONS[axis].get(current_value, set())
    if target not in allowed:
        raise ExperimentTransitionError(
            f"transition not allowed: {axis} {current_value!r} → {target!r}; "
            f"allowed from {current_value!r}: {sorted(allowed)}"
        )

    if current_version != expected_version:
        raise ExperimentConflictError(
            f"version mismatch on {experiment_id}: expected {expected_version}, "
            f"current {current_version}"
        )

    new_version = current_version + 1
    cur = execute(
        f"UPDATE experiments SET {axis} = ?, version = ?, updated_at = ? "
        "WHERE experiment_id = ? AND version = ?",
        (target, new_version, _now(), experiment_id, current_version),
    )
    if cur["changes"] == 0:
        # 别人在我们检查后写了, 抢锁失败
        raise ExperimentConflictError(
            f"concurrent update on {experiment_id}: "
            f"expected version {current_version}"
        )

    append_event(
        experiment_id=experiment_id,
        run_id=run_id,
        actor=actor,
        event_type=f"transition:{axis}",
        from_state=current_value,
        to_state=target,
        from_version=current_version,
        to_version=new_version,
        reason=reason,
        evidence_version=evidence_version,
    )
    return get_experiment(experiment_id)


# ════════════════════════════════════════════════════════════
#  append-only 审计事件
# ════════════════════════════════════════════════════════════

def append_event(
    *,
    experiment_id: str,
    run_id: Optional[int],
    actor: str,
    event_type: str,
    reason: str = "",
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    from_version: Optional[int] = None,
    to_version: Optional[int] = None,
    evidence_version: str = "",
) -> int:
    """写一条审计事件, 返回 event_id"""
    cur = execute(
        "INSERT INTO experiment_run_events "
        "(experiment_id, run_id, actor, event_type, from_state, to_state, "
        " from_version, to_version, reason, evidence_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            experiment_id, run_id, actor, event_type, from_state, to_state,
            from_version, to_version, reason, evidence_version, _now(),
        ),
    )
    return int(cur["lastrowid"])


def list_events(
    *,
    experiment_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """列审计事件"""
    if experiment_id:
        return query_all(
            "SELECT * FROM experiment_run_events WHERE experiment_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (experiment_id, limit),
        )
    return query_all(
        "SELECT * FROM experiment_run_events ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )


# ════════════════════════════════════════════════════════════
#  单飞锁 (pipeline_lock)
# ════════════════════════════════════════════════════════════

def acquire_pipeline_lock(
    scope: str,
    holder_pid: str,
    ttl_seconds: int = 600,
) -> bool:
    """尝试获取 scope 的单飞锁.

    Returns True if acquired, False if another holder owns it.
    过期锁会被新 holder 抢占 (读 expires_at 判断).
    """
    now_iso = _now()
    expires_iso = (datetime.now() + timedelta(seconds=ttl_seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    # 用 INSERT OR IGNORE 避免覆盖现有锁, 然后 UPDATE 抢占过期的
    execute(
        "INSERT OR IGNORE INTO pipeline_lock "
        "(scope, holder_pid, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
        (scope, holder_pid, now_iso, expires_iso),
    )
    # 检查是否真的是我们持有 (不是别人)
    row = query_one(
        "SELECT holder_pid, expires_at FROM pipeline_lock WHERE scope = ?",
        (scope,),
    )
    if not row:
        return False
    # 过期锁 -> 抢占
    if row["holder_pid"] != holder_pid:
        try:
            expires_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            expires_dt = datetime.now()
        if expires_dt < datetime.now():
            cur = execute(
                "UPDATE pipeline_lock SET holder_pid = ?, acquired_at = ?, "
                "expires_at = ? WHERE scope = ? AND holder_pid = ? "
                "AND expires_at = ?",
                (holder_pid, now_iso, expires_iso, scope, row["holder_pid"], row["expires_at"]),
            )
            return cur["changes"] > 0
        return False
    # 已经是我们持有, 续期
    execute(
        "UPDATE pipeline_lock SET expires_at = ? WHERE scope = ? AND holder_pid = ?",
        (expires_iso, scope, holder_pid),
    )
    return True


def release_pipeline_lock(scope: str, holder_pid: str) -> bool:
    """释放本 holder 的锁. 只删自己的锁, 不删别人的."""
    cur = execute(
        "DELETE FROM pipeline_lock WHERE scope = ? AND holder_pid = ?",
        (scope, holder_pid),
    )
    return cur["changes"] > 0


def get_pipeline_lock(scope: str) -> Optional[dict]:
    """看锁的当前状态 (用于 UI/调试, 不持有锁)"""
    return query_one("SELECT * FROM pipeline_lock WHERE scope = ?", (scope,))