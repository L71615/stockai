"""v4.1 1A.4: run_retrospective_writer 测试
"""
import pytest
from datetime import datetime, timedelta

from services.retrospective_service import (
    run_retrospective_writer,
    record_outcome,
    OutcomeAlreadyRecordedError,
)
from database import execute, query_one


@pytest.fixture
def admin_user_id(_test_db_session):
    """确保 admin user 存在并返回 id"""
    user = query_one("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    return user["id"]


def _make_old_proposal(status: str, decided_days_ago: int, user_id: int) -> int:
    """插入一个已 decided N 天的 approval_proposal, 返回 proposal_id"""
    decided_at = (datetime.now() - timedelta(days=decided_days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 创建 minimal experiment
    eid = f"test_exp_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    execute(
        "INSERT INTO experiments (experiment_id, owner_user_id, expr_text, snapshot_json, policy_version, snapshot_hash, created_at, updated_at) "
        "VALUES (?, ?, 'test_expr', '{}', 'v1.0.0', 'test', ?, ?)",
        (eid, user_id, now, now),
    )

    cur = execute(
        """INSERT INTO approval_proposals
           (experiment_id, owner_user_id, status, decided_at, decided_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (eid, user_id, status, decided_at, str(user_id), now, now),
    )
    return int(cur["lastrowid"])


def test_run_writer_skips_young_proposals(admin_user_id):
    """decided_at < fwd_days ago 的 proposal 不被写入"""
    pid = _make_old_proposal("approved", decided_days_ago=5, user_id=admin_user_id)
    result = run_retrospective_writer(fwd_days=30)
    row = query_one("SELECT proposal_id FROM proposal_outcomes WHERE proposal_id = ?", (pid,))
    assert row is None, "5 天前的 proposal 不应被记录"


def test_run_writer_records_old_proposal(admin_user_id):
    """decided_at >= fwd_days ago 的 proposal 被写入"""
    pid = _make_old_proposal("approved", decided_days_ago=35, user_id=admin_user_id)
    run_retrospective_writer(fwd_days=30)
    row = query_one("SELECT proposal_id, decision, fwd_days, baseline_code FROM proposal_outcomes WHERE proposal_id = ?", (pid,))
    assert row is not None
    assert row["decision"] == "approved"
    assert row["fwd_days"] == 30
    assert row["baseline_code"] == "csi300"


def test_run_writer_idempotent(admin_user_id):
    """第二次跑同一个 proposal 不会重复写"""
    pid = _make_old_proposal("rejected", decided_days_ago=40, user_id=admin_user_id)
    run_retrospective_writer(fwd_days=30)
    run_retrospective_writer(fwd_days=30)
    rows = query_one("SELECT COUNT(*) as cnt FROM proposal_outcomes WHERE proposal_id = ?", (pid,))
    assert rows["cnt"] == 1, "outcome 应该只有一条"


def test_run_writer_handles_rejected_decision(admin_user_id):
    """rejected proposal 也被记录"""
    pid = _make_old_proposal("rejected", decided_days_ago=45, user_id=admin_user_id)
    run_retrospective_writer(fwd_days=30)
    row = query_one("SELECT decision FROM proposal_outcomes WHERE proposal_id = ?", (pid,))
    assert row is not None
    assert row["decision"] == "rejected"


def test_run_writer_skips_pending(admin_user_id):
    """pending 状态的 proposal 不被扫描"""
    pid = _make_old_proposal("pending", decided_days_ago=50, user_id=admin_user_id)
    run_retrospective_writer(fwd_days=30)
    row = query_one("SELECT proposal_id FROM proposal_outcomes WHERE proposal_id = ?", (pid,))
    assert row is None, "pending 不应被记录"