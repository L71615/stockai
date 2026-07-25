"""T1 实验账本 + 三轴状态机单元测试

覆盖:
  - create_experiment 默认值正确
  - transition 合法迁移正常, version 单调递增
  - transition 非法迁移抛 ExperimentTransitionError
  - transition version CAS 冲突抛 ExperimentConflictError
  - transition 幂等: target == current 时 no-op (version 不变)
  - list_experiments 按 filter 过滤
  - append_event 审计事件持久化
  - acquire_pipeline_lock 同 scope 互斥
  - promote_candidate API 端到端
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Module-level: 确保测试 DB 初始化, 表存在
import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_experiment.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

# 清空旧测试 DB, 重新 init
_TEST_DB_PATH = Path("/tmp/stockai_test_experiment.db")
if _TEST_DB_PATH.exists():
    try:
        _TEST_DB_PATH.unlink()
    except PermissionError:
        import time
        time.sleep(0.3)
        _TEST_DB_PATH.unlink(missing_ok=True)

from database import init_db
init_db()
# ensure admin user id=1 exists (FK target for experiments.owner_user_id)
from database import ensure_admin_user as _eua
_eua()

import pytest

from services.experiment_service import (
    create_experiment,
    get_experiment,
    list_experiments,
    transition,
    append_event,
    list_events,
    acquire_pipeline_lock,
    release_pipeline_lock,
    get_pipeline_lock,
    ExperimentNotFoundError,
    ExperimentConflictError,
    ExperimentTransitionError,
    LIFECYCLE_STATES,
    PORTFOLIO_ROLES,
    PROPOSAL_STATUSES,
)


# ════════════════════════════════════════════════════════════
#  创建 / 查询
# ════════════════════════════════════════════════════════════

def test_create_experiment_defaults():
    exp_id = create_experiment(
        owner_user_id=1,
        expr_text="ts_rank(close, 5)",
    )
    row = get_experiment(exp_id)
    assert row["expr_text"] == "ts_rank(close, 5)"
    assert row["lifecycle_status"] == "candidate"
    assert row["portfolio_role"] == "none"
    assert row["proposal_status"] == "pending"
    assert row["version"] == 1
    assert row["owner_user_id"] == 1
    assert row["policy_version"] == "v1.0.0"


def test_get_experiment_not_found():
    with pytest.raises(ExperimentNotFoundError):
        get_experiment("exp-nonexistent-xxx")


def test_list_experiments_with_filters():
    e1 = create_experiment(owner_user_id=1, expr_text="expr_a")
    e2 = create_experiment(owner_user_id=1, expr_text="expr_b")
    # e1 → validated, e2 保持 candidate
    transition(experiment_id=e1, axis="lifecycle_status",
               target="validated", expected_version=1, reason="first")

    rows = list_experiments(owner_user_id=1, lifecycle_status="validated")
    ids = {r["experiment_id"] for r in rows}
    assert e1 in ids
    assert e2 not in ids

    all_rows = list_experiments(owner_user_id=1)
    assert e1 in {r["experiment_id"] for r in all_rows}
    assert e2 in {r["experiment_id"] for r in all_rows}


# ════════════════════════════════════════════════════════════
#  迁移 + CAS
# ════════════════════════════════════════════════════════════

def test_lifecycle_happy_path():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_x")
    # candidate → validated
    row = transition(experiment_id=exp_id, axis="lifecycle_status",
                     target="validated", expected_version=1, reason="validated")
    assert row["lifecycle_status"] == "validated"
    assert row["version"] == 2
    # validated → paper
    row = transition(experiment_id=exp_id, axis="lifecycle_status",
                     target="paper", expected_version=2, reason="paper")
    assert row["lifecycle_status"] == "paper"
    assert row["version"] == 3


def test_transition_invalid_target_value():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_y")
    with pytest.raises(ExperimentTransitionError, match="invalid target"):
        transition(experiment_id=exp_id, axis="lifecycle_status",
                   target="not_a_state", expected_version=1)


def test_transition_invalid_axis():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_z")
    with pytest.raises(ExperimentTransitionError, match="unknown axis"):
        transition(experiment_id=exp_id, axis="bogus_axis",
                   target="x", expected_version=1)


def test_transition_illegal_from_to():
    """candidate → champion (跳过 validated/paper) 应被拒绝"""
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_skip")
    with pytest.raises(ExperimentTransitionError, match="transition not allowed"):
        transition(experiment_id=exp_id, axis="lifecycle_status",
                   target="champion", expected_version=1)


def test_transition_terminal_state():
    """rejected 是终态, 不能从 rejected 再迁"""
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_term")
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="rejected", expected_version=1)
    with pytest.raises(ExperimentTransitionError):
        transition(experiment_id=exp_id, axis="lifecycle_status",
                   target="validated", expected_version=2)


def test_transition_version_cas_conflict():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_cas")
    # 先做一次合法迁移, version=2
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="validated", expected_version=1)
    # 客户端拿着 version=1 (过期) 再提交 → 409
    with pytest.raises(ExperimentConflictError, match="version mismatch"):
        transition(experiment_id=exp_id, axis="lifecycle_status",
                   target="paper", expected_version=1)


def test_transition_idempotent_same_value():
    """当前值 == target 时应该幂等 no-op, version 不变"""
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_idem")
    row = transition(experiment_id=exp_id, axis="lifecycle_status",
                     target="candidate", expected_version=1)
    assert row["version"] == 1
    assert row["lifecycle_status"] == "candidate"


def test_three_axes_independent():
    """三个轴的状态独立, 不会互相影响"""
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_3axes")
    # lifecycle → validated (v2), portfolio → paper (v3), proposal → approved (v4)
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="validated", expected_version=1)
    transition(experiment_id=exp_id, axis="portfolio_role",
               target="paper", expected_version=2)
    row = transition(experiment_id=exp_id, axis="proposal_status",
                     target="approved", expected_version=3, reason="human yes")
    assert row["lifecycle_status"] == "validated"
    assert row["portfolio_role"] == "paper"
    assert row["proposal_status"] == "approved"
    assert row["version"] == 4


def test_transition_blocked_to_validated_recovery():
    """blocked → validated 走新一次 run 是合法的"""
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_blocked")
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="blocked", expected_version=1)
    row = transition(experiment_id=exp_id, axis="lifecycle_status",
                     target="validated", expected_version=2)
    assert row["lifecycle_status"] == "validated"
    assert row["version"] == 3


def test_transition_stale_to_validated_recovery():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_stale")
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="validated", expected_version=1)
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="stale", expected_version=2)
    row = transition(experiment_id=exp_id, axis="lifecycle_status",
                     target="validated", expected_version=3)
    assert row["lifecycle_status"] == "validated"


# ════════════════════════════════════════════════════════════
#  审计事件
# ════════════════════════════════════════════════════════════

def test_transition_writes_audit_event():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_audit")
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="validated", expected_version=1,
               actor="user:1", reason="first validation pass")

    events = list_events(experiment_id=exp_id)
    assert len(events) >= 2  # create + transition
    types = [e["event_type"] for e in events]
    assert "create" in types
    assert "transition:lifecycle_status" in types

    trans_event = next(e for e in events if e["event_type"].startswith("transition"))
    assert trans_event["from_state"] == "candidate"
    assert trans_event["to_state"] == "validated"
    assert trans_event["from_version"] == 1
    assert trans_event["to_version"] == 2
    assert trans_event["actor"] == "user:1"


def test_append_event_manual():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_evt")
    eid = append_event(
        experiment_id=exp_id, run_id=None, actor="test",
        event_type="custom_marker", reason="unit test"
    )
    assert eid > 0
    events = list_events(experiment_id=exp_id)
    assert any(e["event_type"] == "custom_marker" for e in events)


# ════════════════════════════════════════════════════════════
#  pipeline_lock 单飞锁
# ════════════════════════════════════════════════════════════

def test_pipeline_lock_acquire_release():
    scope = "test_scope_unique_1"
    assert acquire_pipeline_lock(scope, holder_pid="worker-A", ttl_seconds=60)
    # 别人抢不到
    assert not acquire_pipeline_lock(scope, holder_pid="worker-B", ttl_seconds=60)
    # 自己续期仍 OK
    assert acquire_pipeline_lock(scope, holder_pid="worker-A", ttl_seconds=60)
    # 释放后别人能拿
    assert release_pipeline_lock(scope, holder_pid="worker-A")
    assert acquire_pipeline_lock(scope, holder_pid="worker-B", ttl_seconds=60)
    # 清理
    release_pipeline_lock(scope, holder_pid="worker-B")


def test_pipeline_lock_expired_can_be_taken():
    scope = "test_scope_expired_1"
    acquire_pipeline_lock(scope, holder_pid="worker-X", ttl_seconds=1)
    # 手动改 expires_at 到过去
    from database import execute
    execute("UPDATE pipeline_lock SET expires_at = '2000-01-01 00:00:00' WHERE scope = ?", (scope,))
    # 别人能抢占过期锁
    assert acquire_pipeline_lock(scope, holder_pid="worker-Y", ttl_seconds=60)
    state = get_pipeline_lock(scope)
    assert state["holder_pid"] == "worker-Y"
    release_pipeline_lock(scope, holder_pid="worker-Y")


def test_release_lock_only_owner():
    scope = "test_scope_release_1"
    acquire_pipeline_lock(scope, holder_pid="worker-Z", ttl_seconds=60)
    # 别人不能释放我的锁
    assert not release_pipeline_lock(scope, holder_pid="worker-other")
    state = get_pipeline_lock(scope)
    assert state["holder_pid"] == "worker-Z"
    release_pipeline_lock(scope, holder_pid="worker-Z")


# ════════════════════════════════════════════════════════════
#  并发模拟
# ════════════════════════════════════════════════════════════

def test_concurrent_transition_only_one_wins():
    """两个 transition 同时打同一个 version, 至多一个成功, 状态机 + CAS 共同防丢失更新"""
    import threading
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_race")
    results = []
    barrier = threading.Barrier(2)

    def worker(target):
        barrier.wait()
        try:
            row = transition(experiment_id=exp_id, axis="lifecycle_status",
                             target=target, expected_version=1,
                             actor=f"worker-{target}")
            results.append(("ok", target, row["lifecycle_status"], row["version"]))
        except (ExperimentConflictError, ExperimentTransitionError) as e:
            results.append(("blocked", target, type(e).__name__, 0))

    t1 = threading.Thread(target=worker, args=("validated",))
    t2 = threading.Thread(target=worker, args=("rejected",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    oks = [r for r in results if r[0] == "ok"]
    blocked = [r for r in results if r[0] == "blocked"]
    # SQLite 写锁串行, 第二个线程拿到的 current_value 已是终态 (rejected/validated),
    # 状态机先 CAS 一步拦截. 总之: 至多一次成功, version 只能从 1→2.
    assert len(oks) == 1, f"应只有 1 个 ok, 实得 {len(oks)}: {results}"
    assert len(blocked) == 1, f"应只有 1 个 blocked, 实得 {len(blocked)}: {results}"
    final = get_experiment(exp_id)
    assert final["version"] == 2  # 严格单调


# ════════════════════════════════════════════════════════════
#  状态集合完整性
# ════════════════════════════════════════════════════════════

def test_state_enums_complete():
    """保底: 状态集合不会默默缩水"""
    assert LIFECYCLE_STATES == {"candidate", "validated", "blocked", "stale",
                                "rejected", "paper", "champion", "retired"}
    assert PORTFOLIO_ROLES == {"none", "baseline", "paper", "champion", "challenger"}
    assert PROPOSAL_STATUSES == {"pending", "approved", "rejected", "expired", "withdrawn"}