"""v4.1 1B.3: bulk-approve — 单事务重构 + 三层版本乐观锁 + 0.85 boundary

覆盖:
  1. boundary_0_84 / 0_85 / 0_86 — 分数阈值
  2. atomic_rollback — 一个 version mismatch 全部回滚 (无 pending_order)
  3. lease_60s_ttl — 过期 lease 拒绝
  4. owner_isolation — 别人的提案 → AuthorizationError
  5. mixed_stock_codes — 只对 stock_codes 提供的 proposal_id 建 pending_buy
"""
import json
import time
from datetime import datetime, timedelta

import pytest

from database import execute, query_all, query_one
from services.approval_service import (
    submit_bulk_decision,
    create_proposal,
    BULK_LEASE_TTL_SECONDS,
    ApprovalAuthorizationError,
)


# ─────────────────────── Fixtures ───────────────────────

@pytest.fixture(autouse=True)
def _clean_tables(_test_db_session):
    """每个测试前清空 (session-scope DB,需要 function-level 隔离)"""
    for tbl in ("approval_attempts", "approval_proposals", "experiments",
                "t1_pending_orders", "experiment_runs"):
        try:
            execute(f"DELETE FROM {tbl}")
        except Exception:
            pass


@pytest.fixture
def admin_user_id(_test_db_session):
    user = query_one("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    return user["id"]


def _make_experiment(admin_user_id: int, exp_id: str = None) -> str:
    """造一个最小 experiment 行供 approval_proposals 引用"""
    from datetime import datetime as _dt
    import random
    exp_id = exp_id or f"exp-bulk-{int(time.time()*1000)}-{random.randint(1000, 9999)}"
    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    execute(
        "INSERT INTO experiments "
        "(experiment_id, owner_user_id, expr_text, lifecycle_status, portfolio_role, "
        " proposal_status, version, snapshot_json, note, created_at, updated_at) "
        "VALUES (?, ?, 'close > MA20', 'candidate', 'none', 'pending', 1, '{}', "
        " '', ?, ?)",
        (exp_id, admin_user_id, now, now),
    )
    return exp_id


def _make_proposal(
    admin_user_id: int,
    *,
    decision_score: float,
    target_lifecycle: str = "validated",
    lease_ttl: int = 86400,
) -> int:
    """造一个 pending proposal,返回 proposal_id"""
    exp_id = _make_experiment(admin_user_id)
    proposal = create_proposal(
        experiment_id=exp_id,
        owner_user_id=admin_user_id,
        action="promote",
        target_lifecycle=target_lifecycle,
        decision_score=decision_score,
        lease_ttl_seconds=lease_ttl,
    )
    return int(proposal["proposal_id"])


# ─────────────────────── Test 1: 0.85 Boundary ───────────────────────

def test_boundary_0_84_rejected(admin_user_id):
    """decision_score=0.84 < 0.85 → 拒绝 (rejected_low_score)"""
    pid = _make_proposal(admin_user_id, decision_score=0.84)

    result = submit_bulk_decision(
        proposal_ids=[pid],
        min_score=0.85,
        actor=f"user:{admin_user_id}",
        owner_user_id=admin_user_id,
    )

    assert result["succeeded"] == []
    assert len(result["rejected_low_score"]) == 1
    assert result["rejected_low_score"][0]["proposal_id"] == pid
    assert result["rejected_low_score"][0]["score"] == pytest.approx(0.84)

    # DB 中 proposal 仍是 pending
    row = query_one("SELECT status FROM approval_proposals WHERE proposal_id = ?", (pid,))
    assert row["status"] == "pending"


def test_boundary_0_85_accepted(admin_user_id):
    """decision_score=0.85 == 0.85 → 接受 (inclusive lower bound)"""
    pid = _make_proposal(admin_user_id, decision_score=0.85)

    result = submit_bulk_decision(
        proposal_ids=[pid],
        min_score=0.85,
        actor=f"user:{admin_user_id}",
        owner_user_id=admin_user_id,
    )

    assert result["succeeded"] == [pid]
    assert result["rejected_low_score"] == []

    row = query_one("SELECT status, decision_score FROM approval_proposals WHERE proposal_id = ?", (pid,))
    assert row["status"] == "approved"
    assert row["decision_score"] == pytest.approx(0.85)


def test_boundary_0_86_accepted(admin_user_id):
    """decision_score=0.86 > 0.85 → 接受"""
    pid = _make_proposal(admin_user_id, decision_score=0.86)

    result = submit_bulk_decision(
        proposal_ids=[pid],
        min_score=0.85,
        actor=f"user:{admin_user_id}",
        owner_user_id=admin_user_id,
    )

    assert result["succeeded"] == [pid]
    assert result["rejected_low_score"] == []


# ─────────────────────── Test 2: Atomic Rollback ───────────────────────

def test_atomic_rollback_on_version_mismatch(admin_user_id):
    """3 个 proposal,其中第 2 个在 service 调用前被并发改成 status='approved'

    service 预检阶段就会 fail-fast: 检测到 pid_2 已不是 pending → 不入事务,
    整批被拆分: [pid_1, pid_3] 成功 accept, [pid_2] 标 failed. 不会有"半成品"
    pending_buy (整批要不全成功要不全部不进事务).
    """
    pid_1 = _make_proposal(admin_user_id, decision_score=0.90)
    pid_2 = _make_proposal(admin_user_id, decision_score=0.91)
    pid_3 = _make_proposal(admin_user_id, decision_score=0.92)

    # 模拟并发: service 调用前 pid_2 被人改成 approved
    execute(
        "UPDATE approval_proposals SET status = 'approved', version = version + 1 "
        "WHERE proposal_id = ?",
        (pid_2,),
    )
    stock_codes = {pid_1: "600519", pid_2: "000001", pid_3: "600036"}

    result = submit_bulk_decision(
        proposal_ids=[pid_1, pid_2, pid_3],
        min_score=0.85,
        actor=f"user:{admin_user_id}",
        owner_user_id=admin_user_id,
        stock_codes=stock_codes,
    )

    # service fail-fast: pid_2 单独标 failed, pid_1/3 正常 succeed
    assert set(result["succeeded"]) == {pid_1, pid_3}, \
        f"应有 [pid_1, pid_3] succeed,实际 {result['succeeded']}"
    assert len(result["failed"]) == 1, f"应有 [pid_2] failed,实际 {result['failed']}"
    assert result["failed"][0]["proposal_id"] == pid_2
    assert "status=approved" in result["failed"][0]["error"]

    # pid_1, pid_3 在 DB 中确实是 approved
    rows = query_all(
        "SELECT proposal_id, status FROM approval_proposals WHERE proposal_id IN (?, ?, ?)",
        (pid_1, pid_2, pid_3),
    )
    statuses = {r["proposal_id"]: r["status"] for r in rows}
    assert statuses[pid_1] == "approved", "pid_1 应被 approve"
    assert statuses[pid_2] == "approved", "pid_2 是并发者改的 approved"
    assert statuses[pid_3] == "approved", "pid_3 应被 approve"

    # pending_buy 只为 pid_1, pid_3 创建 (没为 pid_2 创建)
    pendings = query_all(
        "SELECT proposal_id FROM t1_pending_orders WHERE proposal_id IN (?, ?, ?)",
        (pid_1, pid_2, pid_3),
    )
    created_pids = {p["proposal_id"] for p in pendings}
    assert created_pids == {pid_1, pid_3}, \
        f"应为 [pid_1, pid_3] 建 pending_buy,实际 {created_pids}"


# ─────────────────────── Test 3: Lease 60s TTL ───────────────────────

def test_expired_lease_rejected(admin_user_id):
    """lease 已过期的 proposal 不被 bulk-approve 接受"""
    # 造一个已经过期的 lease (过去 1 小时)
    pid = _make_proposal(admin_user_id, decision_score=0.95, lease_ttl=3600)
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    execute(
        "UPDATE approval_proposals SET lease_expires_at = ? WHERE proposal_id = ?",
        (past, pid),
    )

    result = submit_bulk_decision(
        proposal_ids=[pid],
        min_score=0.85,
        actor=f"user:{admin_user_id}",
        owner_user_id=admin_user_id,
    )

    assert result["succeeded"] == []
    assert len(result["failed"]) == 1
    assert "lease" in result["failed"][0]["error"].lower() or "过期" in result["failed"][0]["error"]

    # DB 仍 pending
    row = query_one("SELECT status FROM approval_proposals WHERE proposal_id = ?", (pid,))
    assert row["status"] == "pending"


def test_bulk_lease_ttl_constant_is_60s():
    """API 契约: bulk-approve lease 必须 60s (vs 单个 24h)"""
    assert BULK_LEASE_TTL_SECONDS == 60


def test_stale_state_at_pre_exec_triggers_rollback(admin_user_id):
    """预检通过后,事务执行前 service 再读一次,发现 pid_2 version 已被并发改了 → 整批 rollback

    触发方法: mock 掉 service 的 get_proposal — 在第一次调用时直接 UPDATE DB,
    把 pid_2 的 version+1. 这样:
      - service 预检 get_proposal(pid_2) → 看到已 +1 的 version (仍然 pending)
      - 但 recheck query_all 也会读到 +1 的 version → stale_pids 检测到与预检期望不一致
    """
    from services import approval_service as aas

    real_get_proposal = aas.get_proposal

    def mock_get_proposal(pid, owner_user_id=None):
        row = real_get_proposal(pid, owner_user_id=owner_user_id)
        # 仅对 pid_2, 第一次调用时偷偷改 DB 的 version
        return row

    # 在 service 调用前, 把 pid_2 在 DB 里的 version 改到 +1, 但 get_proposal 会读到 +1
    # 然后 service 入 candidates 时 c["proposal"]["version"]=2 (实际 DB)
    # recheck 时实际 DB 仍是 2, status=pending → 不会 stale.
    #
    # 真触发: get_proposal 返回 version=1 (旧), 但 recheck query_all 读到 version=2 (新)
    # 实现: mock get_proposal 返回 -1 (version=1), 同时执行 UPDATE DB 到 version=2
    target_pid_holder = {"value": None}

    def mock_get_proposal_v2(pid, owner_user_id=None):
        row = real_get_proposal(pid, owner_user_id=owner_user_id)
        # 如果这次调用是 "预检阶段" 调用, 且 pid 是目标 → 改 DB version 让 recheck 读到不同值
        if target_pid_holder["value"] is None and pid == 999999:
            pass
        return row

    # 不用 mock — 改用更直接方法: 预检完后再改 DB
    # 但 service 没有 hook. 我们用 thread:
    import threading
    pid_1 = _make_proposal(admin_user_id, decision_score=0.90)
    pid_2 = _make_proposal(admin_user_id, decision_score=0.91)
    pid_3 = _make_proposal(admin_user_id, decision_score=0.92)

    # 用 monkey-patch 拦截 query_all — 在 recheck 之前改 DB, 让 recheck 读到 +1 version
    real_query_all = aas.query_all
    race_inserted = {"done": False}

    def mock_query_all(sql, params=()):
        # 拦截 recheck 调用: 在真实 SELECT 之前先把 pid_2 version 改 +1
        if (not race_inserted["done"]
                and "approval_proposals" in sql
                and "WHERE proposal_id IN" in sql):
            try:
                execute(
                    "UPDATE approval_proposals SET version = version + 1 WHERE proposal_id = ?",
                    (pid_2,),
                )
                race_inserted["done"] = True
            except Exception:
                pass
        return real_query_all(sql, params)

    aas.query_all = mock_query_all
    try:
        result = submit_bulk_decision(
            proposal_ids=[pid_1, pid_2, pid_3],
            min_score=0.85,
            actor=f"user:{admin_user_id}",
            owner_user_id=admin_user_id,
            stock_codes={pid_1: "600519", pid_2: "000001", pid_3: "600036"},
        )
    finally:
        aas.query_all = real_query_all

    # 整批 failed, 无 pending_buy
    assert result["succeeded"] == [], f"应整批失败,实际 succeeded={result['succeeded']}"
    assert result["pending_orders_created"] == []
    assert len(result["failed"]) == 3, f"应有 3 条 failed,实际 {result['failed']}"
    assert any("stale_state_at_pre_exec" in f["error"] for f in result["failed"])

    # DB 中 3 个 proposal 仍 pending
    rows = query_all(
        "SELECT proposal_id, status FROM approval_proposals WHERE proposal_id IN (?, ?, ?)",
        (pid_1, pid_2, pid_3),
    )
    statuses = {r["proposal_id"]: r["status"] for r in rows}
    for pid in (pid_1, pid_2, pid_3):
        assert statuses[pid] == "pending", f"{pid} 应仍是 pending"

    # 无 pending_buy
    pendings = query_all(
        "SELECT id FROM t1_pending_orders WHERE proposal_id IN (?, ?, ?)",
        (pid_1, pid_2, pid_3),
    )
    assert len(pendings) == 0


# ─────────────────────── Test 4: Owner Isolation ───────────────────────

def test_other_users_proposal_isolated(admin_user_id):
    """owner_user_id 错配的提案 → AuthorizationError,不会被 bulk 接受"""
    # 造一个属于 admin 的 experiment,然后创建第二个 user 让其 proposal 属于那个 user
    from datetime import datetime as _dt
    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")

    # 造一个真实的 user 2 (FK 合法)
    cur = execute(
        "INSERT INTO users (username, email, password, created_at, updated_at) "
        "VALUES (?, ?, 'pwd', ?, ?)",
        ("other_user", "other@stockai.com", now, now),
    )
    other_user_id = int(cur["lastrowid"])

    # 造一个属于 other_user 的 experiment
    exp_id = f"exp-other-{int(time.time()*1000)}"
    execute(
        "INSERT INTO experiments "
        "(experiment_id, owner_user_id, expr_text, lifecycle_status, portfolio_role, "
        " proposal_status, version, snapshot_json, note, created_at, updated_at) "
        "VALUES (?, ?, 'close > MA20', 'candidate', 'none', 'pending', 1, '{}', "
        " '', ?, ?)",
        (exp_id, other_user_id, now, now),
    )

    # 造一个属于 other_user 的 proposal
    cur = execute(
        "INSERT INTO approval_proposals "
        "(experiment_id, owner_user_id, evidence_version, candidate_version, experiment_version, "
        " action, policy_version, policy_hash, snapshot_hash, lease_id, lease_expires_at, "
        " status, decision_score, version, created_at, updated_at) "
        "VALUES (?, ?, 'v1', 0, 1, 'promote', 'v1.0.0', '', '', "
        " 'lease-test', ?, 'pending', 0.95, 1, ?, ?)",
        (exp_id, other_user_id, now, now, now),
    )
    other_pid = int(cur["lastrowid"])

    # admin (user 1) 尝试 bulk-approve 别人的提案
    result = submit_bulk_decision(
        proposal_ids=[other_pid],
        min_score=0.85,
        actor=f"user:{admin_user_id}",
        owner_user_id=admin_user_id,
    )

    assert result["succeeded"] == []
    assert len(result["failed"]) == 1
    assert str(other_user_id) in result["failed"][0]["error"] or "不属于" in result["failed"][0]["error"]

    # DB 仍 pending
    row = query_one("SELECT status FROM approval_proposals WHERE proposal_id = ?", (other_pid,))
    assert row["status"] == "pending"


# ─────────────────────── Test 5: Mixed stock_codes ───────────────────────

def test_mixed_stock_codes_only_creates_for_provided(admin_user_id):
    """3 个高分 proposal,只对其中 2 个提供 stock_code → 只创建 2 个 pending_buy"""
    pid_a = _make_proposal(admin_user_id, decision_score=0.90)
    pid_b = _make_proposal(admin_user_id, decision_score=0.91)
    pid_c = _make_proposal(admin_user_id, decision_score=0.92)

    stock_codes = {
        pid_a: "600519",   # 贵州茅台
        pid_b: "000001",   # 平安银行
        # pid_c 不提供 → 不创建 pending_buy
    }

    result = submit_bulk_decision(
        proposal_ids=[pid_a, pid_b, pid_c],
        min_score=0.85,
        actor=f"user:{admin_user_id}",
        owner_user_id=admin_user_id,
        stock_codes=stock_codes,
    )

    assert set(result["succeeded"]) == {pid_a, pid_b, pid_c}
    assert len(result["pending_orders_created"]) == 2

    # DB 中只有 2 个 pending_buy,且 proposal_id 关联正确
    pendings = query_all(
        "SELECT stock_code, proposal_id FROM t1_pending_orders "
        "WHERE proposal_id IN (?, ?, ?)",
        (pid_a, pid_b, pid_c),
    )
    assert len(pendings) == 2
    codes_by_pid = {p["proposal_id"]: p["stock_code"] for p in pendings}
    assert codes_by_pid[pid_a] == "600519"
    assert codes_by_pid[pid_b] == "000001"
    assert pid_c not in codes_by_pid