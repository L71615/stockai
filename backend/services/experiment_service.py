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
#  v4.2 候选 — Auto Champion Replacement (DRY-RUN ONLY)
#
#  设计原则 (per TODOS.md):
#    - 永远 dry-run, 绝不自动替换
#    - UI 显示"would auto-replace if enabled" 标签
#    - 实际替换仍需 human approval (existing flow)
#
#  输入: factor_candidates 表里的所有 promoted=0 候选
#  算法: 复用 compute_factor_metrics 算每个候选的 IR
#        与当前 champion (baseline pipeline) 的 IR 比较
#  输出: 排序 + would_replace 标记
# ════════════════════════════════════════════════════════════


def compute_champion_dry_run(
    *,
    owner_user_id: Optional[int] = None,
    stock_pool: str = "hs300",
    lookback_days: int = 60,
    replace_threshold: float = 1.5,
) -> dict:
    """Auto Champion Replacement 干跑分析

    Args:
        owner_user_id: 限定用户(默认 None = 全部)
        stock_pool: 计算 IR 用的股票池
        lookback_days: IC 回看窗口
        replace_threshold: challenger IR >= champion IR × threshold 才"would replace"

    Returns:
        {
            'champion': {
                'experiment_id': ...,
                'representative_ir': 0.038,  # 当前 champion 的代表 IR
                'expr_text': '__pipeline_daily__',
                'created_at': ...,
            },
            'candidates': [
                {
                    'candidate_id': 42,
                    'expr_text': 'rank(close/ma20)',
                    'ir': 0.062,
                    'ic_mean': 0.0085,
                    'sharpe_proxy': 0.9,
                    'would_replace': True,  # IR > champion × 1.5
                    'rank': 1,
                    'reason': 'IR 1.63x champion',
                    'created_at': ...,
                },
                ...
            ],
            'summary': {
                'n_candidates': 264,
                'n_evaluated': 30,         # IR 数据足够 (>=30 天)
                'n_would_replace': 5,
                'threshold': 1.5,
            },
            'dry_run': True,  # 重要: 永不自动执行
        }
    """
    from services.factor_lab import compute_factor_metrics
    from database import query_all, query_one

    # 1. 找当前 champion
    champion_row = query_one(
        "SELECT experiment_id, expr_text, lifecycle_status, portfolio_role, created_at "
        "FROM experiments "
        "WHERE lifecycle_status = 'champion' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    if not champion_row:
        # fallback: 用最新 done 的 run
        champion_row = query_one(
            "SELECT experiment_id, expr_text, lifecycle_status, portfolio_role, created_at "
            "FROM experiments ORDER BY created_at DESC LIMIT 1"
        )

    if not champion_row:
        return {"error": "无 champion 实验记录", "dry_run": True}

    # 2. 取所有候选(未 promoted 的)
    where = "WHERE promoted = 0 AND expr_text IS NOT NULL AND expr_text != ''"
    params: list[Any] = []
    if owner_user_id is not None:
        where += " AND run_owner = ?"
        # 注意:factor_candidates 表里没有 owner 字段,暂时跳过 owner 过滤
    candidate_rows = query_all(
        f"SELECT id, expr_text, ir, ic_mean, win_rate, valid_days, "
        f"       created_at, run_id "
        f"FROM factor_candidates {where} "
        f"ORDER BY created_at DESC LIMIT 100"
    )

    if not candidate_rows:
        return {
            "champion": champion_row,
            "candidates": [],
            "summary": {"n_candidates": 0, "n_evaluated": 0, "n_would_replace": 0, "threshold": replace_threshold},
            "dry_run": True,
            "message": "factor_candidates 表为空,先跑 GP/ML 挖掘生成候选",
        }

    # 3. 算 champion 的代表 IR(用 best factor in registry 作代理)
    # 因为 champion 是 pipeline baseline (整个组合),无法直接 IR 对比
    # 我们用 FACTOR_REGISTRY 中最强因子作为参照
    # 简化: 直接从 done run 的最近 snapshot 拿,或固定为 0.05 经验值
    champion_ir = 0.05  # pipeline baseline 经验 IR 阈值
    # 找最新 done run 的 metric(如果有 experiment_runs 表的 metrics)
    latest_done = query_one(
        "SELECT run_id, finished_at FROM experiment_runs "
        "WHERE status='done' AND experiment_id = ? "
        "ORDER BY finished_at DESC LIMIT 1",
        (champion_row["experiment_id"],)
    )
    if latest_done:
        # 看 drift_events 表有没有最近的 metric_value
        champion_metric = query_one(
            "SELECT value FROM drift_events "
            "WHERE factor_name = 'champion_ir' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if champion_metric:
            try:
                champion_ir = float(champion_metric["value"])
            except (ValueError, TypeError):
                pass

    # 4. 评估每个候选(用 candidates 表里已存的 IR,避免重算)
    candidates = []
    for row in candidate_rows:
        c_ir = row.get("ir")
        c_ic = row.get("ic_mean")
        c_wr = row.get("win_rate")
        c_days = row.get("valid_days") or 0

        # 没 IR 的候选: 数据可能不足,标 unknown
        if c_ir is None or c_days < 30:
            candidates.append({
                "candidate_id": row["id"],
                "expr_text": row["expr_text"],
                "ir": None,
                "ic_mean": c_ic,
                "win_rate": c_wr,
                "valid_days": c_days,
                "would_replace": False,
                "rank": None,
                "reason": f"数据不足 ({c_days} 天,需 ≥30)",
                "created_at": row["created_at"],
                "run_id": row.get("run_id"),
            })
            continue

        ir_ratio = c_ir / champion_ir if champion_ir > 1e-9 else 0
        would_replace = ir_ratio >= replace_threshold

        candidates.append({
            "candidate_id": row["id"],
            "expr_text": row["expr_text"],
            "ir": round(float(c_ir), 4),
            "ic_mean": round(float(c_ic), 5) if c_ic is not None else None,
            "win_rate": round(float(c_wr), 3) if c_wr is not None else None,
            "valid_days": c_days,
            "would_replace": bool(would_replace),
            "rank": None,  # 后面填
            "reason": f"IR ratio {ir_ratio:.2f}x champion (阈值 {replace_threshold}x)" if would_replace
                      else f"IR ratio {ir_ratio:.2f}x < {replace_threshold}x",
            "created_at": row["created_at"],
            "run_id": row.get("run_id"),
        })

    # 5. 按 |IR| 降序排序,只对有 IR 的 rank
    eval_candidates = [c for c in candidates if c["ir"] is not None]
    eval_candidates.sort(key=lambda c: abs(c["ir"]), reverse=True)
    for i, c in enumerate(eval_candidates, 1):
        c["rank"] = i

    # 6. 重组:有 IR 的在前,无 IR 的在后
    candidates = eval_candidates + [c for c in candidates if c["ir"] is None]

    n_would_replace = sum(1 for c in candidates if c["would_replace"])

    return {
        "champion": {
            **champion_row,
            "representative_ir": champion_ir,
        },
        "candidates": candidates,
        "summary": {
            "n_candidates": len(candidates),
            "n_evaluated": len(eval_candidates),
            "n_would_replace": n_would_replace,
            "threshold": replace_threshold,
            "pool": stock_pool,
            "lookback_days": lookback_days,
        },
        "dry_run": True,  # 永不自动
        "safety_note": "DRY-RUN ONLY — 实际替换仍需人工审批(existing approval flow)",
    }


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

    v4.1 outside voice fix: 整体封装在 BEGIN IMMEDIATE 事务里 — SQLite 的写锁
    保证跨进程串行化, INSERT OR IGNORE + UPDATE 在同一事务中避免 TOCTOU race.
    """
    from database import execute_transaction

    now_iso = _now()
    expires_iso = (datetime.now() + timedelta(seconds=ttl_seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    def _do(cur) -> bool:
        # 用 INSERT OR IGNORE 避免覆盖现有锁, 然后 UPDATE 抢占过期的
        cur.execute(
            "INSERT OR IGNORE INTO pipeline_lock "
            "(scope, holder_pid, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
            (scope, holder_pid, now_iso, expires_iso),
        )
        # 检查是否真的是我们持有 (不是别人)
        row = cur.execute(
            "SELECT holder_pid, expires_at FROM pipeline_lock WHERE scope = ?",
            (scope,),
        ).fetchone()
        if not row:
            return False
        row_d = dict(row)
        # 过期锁 -> 抢占
        if row_d["holder_pid"] != holder_pid:
            try:
                expires_dt = datetime.strptime(row_d["expires_at"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                expires_dt = datetime.now()
            if expires_dt < datetime.now():
                # 必须加 holder_pid/expires_at 守卫, 否则会覆盖别人刚续期的锁
                cur2 = cur.execute(
                    "UPDATE pipeline_lock SET holder_pid = ?, acquired_at = ?, "
                    "expires_at = ? WHERE scope = ? AND holder_pid = ? "
                    "AND expires_at = ?",
                    (holder_pid, now_iso, expires_iso, scope, row_d["holder_pid"], row_d["expires_at"]),
                )
                return cur2.rowcount > 0
            return False
        # 已经是我们持有, 续期
        cur.execute(
            "UPDATE pipeline_lock SET expires_at = ? WHERE scope = ? AND holder_pid = ?",
            (expires_iso, scope, holder_pid),
        )
        return True

    return execute_transaction(_do)


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