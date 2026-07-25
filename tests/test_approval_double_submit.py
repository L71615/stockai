"""T5 审批服务测试 — CAS / lease / 双 submit / 跨用户 / append-only 审计

覆盖:
  - create_proposal 自动生成 lease + expires_at
  - get_proposal owner 校验失败 → 403
  - list_proposals 按 status / experiment 过滤
  - submit_decision 同 lease 重复 submit → idempotent no-op (version 不增)
    (注: 第二次同 lease 提交会因为 status 已是 approved/rejected 抛 409)
  - submit_decision 跨 lease → 409
  - submit_decision version CAS 失败 → 409
  - submit_decision lease 过期 → 409
  - reopen_lease 发新 lease, version++
  - approve 触发 experiment 三轴 transition (lifecycle + portfolio)
  - list_attempts append-only, 不删除/不改
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_t5.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

_TEST_DB_PATH = Path("/tmp/stockai_test_t5.db")
if _TEST_DB_PATH.exists():
    try:
        _TEST_DB_PATH.unlink()
    except PermissionError:
        import time
        time.sleep(0.3)
        _TEST_DB_PATH.unlink(missing_ok=True)

from database import init_db, ensure_admin_user as _eua, execute as db_execute
init_db()
_eua()
# 加 user 2 (跨用户测试)
db_execute(
    "INSERT OR IGNORE INTO users (id, username, email, password) "
    "VALUES (2, 'user2', 'user2@test.com', 'x')"
)

import pytest

from services.experiment_service import (
    create_experiment, transition,
)
from services.approval_service import (
    create_proposal, get_proposal, list_proposals, list_attempts,
    submit_decision, reopen_lease,
    ApprovalNotFoundError, ApprovalConflictError,
    ApprovalExpiredError, ApprovalAuthorizationError,
)


# ════════════════════════════════════════════════════════════
#  创建提案
# ════════════════════════════════════════════════════════════

def test_create_proposal_basic():
    exp_id = create_experiment(owner_user_id=1, expr_text="ts_rank(close, 5)")
    proposal = create_proposal(
        experiment_id=exp_id,
        owner_user_id=1,
        action="promote",
        target_lifecycle="validated",
        evidence_version="v1",
    )
    assert proposal["proposal_id"] > 0
    assert proposal["experiment_id"] == exp_id
    assert proposal["status"] == "pending"
    assert proposal["lease_id"].startswith("lease-")
    assert proposal["lease_expires_at"] is not None
    assert proposal["version"] == 1


def test_create_proposal_cross_user_403():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_x")
    with pytest.raises(ApprovalAuthorizationError):
        create_proposal(experiment_id=exp_id, owner_user_id=2)


def test_create_proposal_experiment_not_found():
    with pytest.raises(ApprovalNotFoundError):
        create_proposal(experiment_id="exp-bogus-xxx", owner_user_id=1)


# ════════════════════════════════════════════════════════════
#  查询
# ════════════════════════════════════════════════════════════

def test_get_proposal_owner_check():
    exp_id = create_experiment(owner_user_id=1, expr_text="expr_owner")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    # user 2 看 → 403
    with pytest.raises(ApprovalAuthorizationError):
        get_proposal(proposal["proposal_id"], owner_user_id=2)
    # user 1 看 → OK
    p = get_proposal(proposal["proposal_id"], owner_user_id=1)
    assert p["proposal_id"] == proposal["proposal_id"]


def test_list_proposals_by_status():
    exp_id = create_experiment(owner_user_id=1, expr_text="list_test")
    p1 = create_proposal(experiment_id=exp_id, owner_user_id=1)
    p2 = create_proposal(experiment_id=exp_id, owner_user_id=1)

    rows = list_proposals(owner_user_id=1, status="pending")
    ids = {r["proposal_id"] for r in rows}
    assert p1["proposal_id"] in ids
    assert p2["proposal_id"] in ids


def test_list_proposals_cross_user_excluded():
    exp1 = create_experiment(owner_user_id=1, expr_text="u1_exp")
    exp2 = create_experiment(owner_user_id=2, expr_text="u2_exp")
    p1 = create_proposal(experiment_id=exp1, owner_user_id=1)
    p2 = create_proposal(experiment_id=exp2, owner_user_id=2)

    rows = list_proposals(owner_user_id=1)
    ids = {r["proposal_id"] for r in rows}
    assert p1["proposal_id"] in ids
    assert p2["proposal_id"] not in ids


# ════════════════════════════════════════════════════════════
#  submit_decision 基本
# ════════════════════════════════════════════════════════════

def test_approve_increments_version_and_status():
    exp_id = create_experiment(owner_user_id=1, expr_text="approve_test")
    proposal = create_proposal(
        experiment_id=exp_id, owner_user_id=1,
        target_lifecycle="validated",
    )
    lease_id = proposal["lease_id"]
    expected_version = proposal["version"]

    result = submit_decision(
        proposal_id=proposal["proposal_id"],
        action="approve",
        expected_version=expected_version,
        actor="user:1",
        reason="looks good",
        lease_id=lease_id,
        owner_user_id=1,
    )
    assert result["status"] == "approved"
    assert result["version"] == expected_version + 1
    assert result["decided_by"] == "user:1"


def test_approve_triggers_experiment_transition():
    """approve 应触发 T1 三轴状态机的 lifecycle transition."""
    exp_id = create_experiment(owner_user_id=1, expr_text="trans_test")
    create_proposal(
        experiment_id=exp_id, owner_user_id=1,
        target_lifecycle="validated",
    )
    proposal = list_proposals(owner_user_id=1, experiment_id=exp_id)[0]

    submit_decision(
        proposal_id=proposal["proposal_id"],
        action="approve",
        expected_version=proposal["version"],
        actor="user:1",
        lease_id=proposal["lease_id"],
        owner_user_id=1,
    )

    # 查 experiment: lifecycle_status 应该是 validated
    from services.experiment_service import get_experiment
    exp = get_experiment(exp_id)
    assert exp["lifecycle_status"] == "validated"
    # version 也增了
    assert exp["version"] == 2


# ════════════════════════════════════════════════════════════
#  CAS 冲突
# ════════════════════════════════════════════════════════════

def test_version_cas_conflict():
    exp_id = create_experiment(owner_user_id=1, expr_text="cas_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    # 用错的 expected_version 提交
    with pytest.raises(ApprovalConflictError, match="version"):
        submit_decision(
            proposal_id=proposal["proposal_id"],
            action="approve",
            expected_version=99,  # wrong
            actor="user:1",
            lease_id=proposal["lease_id"],
            owner_user_id=1,
        )


def test_cross_lease_rejected():
    exp_id = create_experiment(owner_user_id=1, expr_text="lease_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    with pytest.raises(ApprovalConflictError, match="lease"):
        submit_decision(
            proposal_id=proposal["proposal_id"],
            action="approve",
            expected_version=proposal["version"],
            actor="user:1",
            lease_id="lease-fake-xxx",  # wrong lease
            owner_user_id=1,
        )


def test_double_submit_after_approved_rejected():
    """已 approved 的 proposal 不能再 approve"""
    exp_id = create_experiment(owner_user_id=1, expr_text="double_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)

    submit_decision(
        proposal_id=proposal["proposal_id"],
        action="approve",
        expected_version=proposal["version"],
        actor="user:1",
        lease_id=proposal["lease_id"],
        owner_user_id=1,
    )
    # 第二次
    with pytest.raises(ApprovalConflictError, match="approved"):
        submit_decision(
            proposal_id=proposal["proposal_id"],
            action="approve",
            expected_version=2,  # even with right version
            actor="user:1",
            lease_id=proposal["lease_id"],
            owner_user_id=1,
        )


def test_double_submit_concurrent_only_one_wins():
    """两个 submit 同时打到同一 proposal, 只一个成功."""
    import threading
    exp_id = create_experiment(owner_user_id=1, expr_text="race_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            submit_decision(
                proposal_id=proposal["proposal_id"],
                action="approve",
                expected_version=proposal["version"],
                actor="user:1",
                lease_id=proposal["lease_id"],
                owner_user_id=1,
            )
            results.append("ok")
        except (ApprovalConflictError, ApprovalExpiredError) as e:
            results.append(("conflict", str(e)[:50]))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # SQLite 写锁串行, 第二个会看到 status=approved → 409
    oks = [r for r in results if r == "ok"]
    assert len(oks) == 1
    final = get_proposal(proposal["proposal_id"], owner_user_id=1)
    assert final["status"] == "approved"


# ════════════════════════════════════════════════════════════
#  Lease 过期 + reopen
# ════════════════════════════════════════════════════════════

def test_lease_expired_rejected():
    exp_id = create_experiment(owner_user_id=1, expr_text="expired_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1, lease_ttl_seconds=1)

    # 手动把 lease_expires_at 改到过去
    db_execute(
        "UPDATE approval_proposals SET lease_expires_at = '2000-01-01 00:00:00' "
        "WHERE proposal_id = ?",
        (proposal["proposal_id"],),
    )

    with pytest.raises(ApprovalExpiredError, match="过期"):
        submit_decision(
            proposal_id=proposal["proposal_id"],
            action="approve",
            expected_version=proposal["version"],
            actor="user:1",
            lease_id=proposal["lease_id"],
            owner_user_id=1,
        )


def test_reopen_lease_creates_new_lease():
    exp_id = create_experiment(owner_user_id=1, expr_text="reopen_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    old_lease = proposal["lease_id"]
    old_version = proposal["version"]

    new_proposal = reopen_lease(proposal["proposal_id"], owner_user_id=1)
    assert new_proposal["lease_id"] != old_lease
    assert new_proposal["version"] == old_version + 1
    # 新 lease 可以用, 旧 lease 已被废
    # 旧 lease_id 提交 → 409
    with pytest.raises(ApprovalConflictError, match="lease"):
        submit_decision(
            proposal_id=proposal["proposal_id"],
            action="approve",
            expected_version=old_version,
            actor="user:1",
            lease_id=old_lease,
            owner_user_id=1,
        )


def test_reopen_rejected_after_decided():
    """已 approved 的不能 reopen"""
    exp_id = create_experiment(owner_user_id=1, expr_text="reopen_reject")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    submit_decision(
        proposal_id=proposal["proposal_id"],
        action="approve",
        expected_version=proposal["version"],
        actor="user:1",
        lease_id=proposal["lease_id"],
        owner_user_id=1,
    )
    with pytest.raises(ApprovalConflictError, match="approved"):
        reopen_lease(proposal["proposal_id"], owner_user_id=1)


# ════════════════════════════════════════════════════════════
#  Append-only 审计
# ════════════════════════════════════════════════════════════

def test_attempts_appended_on_each_submit():
    exp_id = create_experiment(owner_user_id=1, expr_text="audit_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)

    # 1 个失败 (version CAS)
    try:
        submit_decision(
            proposal_id=proposal["proposal_id"],
            action="approve",
            expected_version=99,
            actor="user:1",
            lease_id=proposal["lease_id"],
            owner_user_id=1,
        )
    except ApprovalConflictError:
        pass

    attempts = list_attempts(proposal["proposal_id"])
    assert len(attempts) == 1
    assert attempts[0]["result"] == "conflict"
    assert attempts[0]["action"] == "approve"


def test_attempts_include_both_success_and_failure():
    exp_id = create_experiment(owner_user_id=1, expr_text="audit_mix")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)

    # 失败一次 (version)
    try:
        submit_decision(
            proposal_id=proposal["proposal_id"], action="reject",
            expected_version=99, actor="user:1",
            lease_id=proposal["lease_id"], owner_user_id=1,
        )
    except ApprovalConflictError:
        pass

    # 成功一次
    submit_decision(
        proposal_id=proposal["proposal_id"], action="reject",
        expected_version=proposal["version"], actor="user:1",
        reason="bad candidate", lease_id=proposal["lease_id"], owner_user_id=1,
    )

    attempts = list_attempts(proposal["proposal_id"])
    assert len(attempts) == 2
    results = [a["result"] for a in attempts]
    assert "conflict" in results
    assert "ok" in results


# ════════════════════════════════════════════════════════════
#  later / withdraw
# ════════════════════════════════════════════════════════════

def test_later_keeps_pending_status():
    exp_id = create_experiment(owner_user_id=1, expr_text="later_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)

    result = submit_decision(
        proposal_id=proposal["proposal_id"], action="later",
        expected_version=proposal["version"],
        actor="user:1", reason="will come back",
        lease_id=proposal["lease_id"], owner_user_id=1,
    )
    assert result["status"] == "pending"
    assert result["version"] == proposal["version"] + 1


def test_withdraw_changes_status():
    exp_id = create_experiment(owner_user_id=1, expr_text="withdraw_test")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)

    result = submit_decision(
        proposal_id=proposal["proposal_id"], action="withdraw",
        expected_version=proposal["version"],
        actor="user:1", reason="changed mind",
        lease_id=proposal["lease_id"], owner_user_id=1,
    )
    assert result["status"] == "withdrawn"