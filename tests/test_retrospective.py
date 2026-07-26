"""T9 复盘 + counterfactual 测试

覆盖:
  - record_outcome: 一次性 + 自动 label + UNIQUE 约束
  - generate_retrospective: 需要 outcome 先存在
  - list_outcomes / list_retrospectives: 过滤
  - counterfactual_summary: 接受 vs 拒绝的 edge 计算
  - trading_memory.record_proposal_retrospective: 写入 + 读回
  - 端到端: accept → outcome 记录 → retrospective 生成
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_t9.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

_TEST_DB_PATH = Path("/tmp/stockai_test_t9.db")
if _TEST_DB_PATH.exists():
    try:
        _TEST_DB_PATH.unlink()
    except PermissionError:
        import time
        time.sleep(0.3)
        _TEST_DB_PATH.unlink(missing_ok=True)

from database import init_db, ensure_admin_user as _eua
init_db()
_eua()

import uuid
import pytest

from services.experiment_service import create_experiment
from services.approval_service import (
    create_proposal, submit_decision,
)
from services.retrospective_service import (
    record_outcome, generate_retrospective,
    list_outcomes, list_retrospectives, counterfactual_summary,
    OutcomeAlreadyRecordedError,
)


# ════════════════════════════════════════════════════════════
#  Outcome 记录
# ════════════════════════════════════════════════════════════

def test_record_outcome_basic():
    exp_id = create_experiment(owner_user_id=1, expr_text="t9_basic")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1,
                                action="promote", target_lifecycle="paper")
    submit_decision(proposal_id=proposal["proposal_id"], action="approve",
                    expected_version=proposal["version"], actor="user:1",
                    lease_id=proposal["lease_id"], owner_user_id=1)

    target_proposal_id = proposal["proposal_id"]
    oid = record_outcome(
        proposal_id=target_proposal_id,
        decision="approved",
        fwd_days=30, fwd_return=0.05, fwd_baseline_diff=0.02,
    )
    assert oid > 0

    rows = list_outcomes(decision="approved")
    # 用 decision filter 隔离其他测试
    ids = [r["proposal_id"] for r in rows]
    assert target_proposal_id in ids
    our_row = next(r for r in rows if r["proposal_id"] == target_proposal_id)
    assert our_row["decision"] == "approved"
    assert our_row["fwd_days"] == 30


def test_record_outcome_auto_label():
    """自动分类: approved + 正 diff → good"""
    exp_id = create_experiment(owner_user_id=1, expr_text="t9_label")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    submit_decision(proposal_id=proposal["proposal_id"], action="approve",
                    expected_version=proposal["version"], actor="user:1",
                    lease_id=proposal["lease_id"], owner_user_id=1)

    record_outcome(proposal_id=proposal["proposal_id"], decision="approved",
                   fwd_days=30, fwd_return=0.05, fwd_baseline_diff=0.05)
    row = list_outcomes()[0]
    assert row["label"] == "good"


def test_record_outcome_auto_label_rejected_correct():
    """拒绝后实际涨了 → 'good' (拒绝是错的, 错过机会)"""
    exp_id = create_experiment(owner_user_id=1, expr_text="t9_reject_label")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    submit_decision(proposal_id=proposal["proposal_id"], action="reject",
                    expected_version=proposal["version"], actor="user:1",
                    lease_id=proposal["lease_id"], owner_user_id=1)

    record_outcome(proposal_id=proposal["proposal_id"], decision="rejected",
                   fwd_days=30, fwd_return=0.08, fwd_baseline_diff=0.04)
    row = list_outcomes()[0]
    assert row["label"] == "good"


def test_record_outcome_duplicate_raises():
    exp_id = create_experiment(owner_user_id=1, expr_text="t9_dup")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    record_outcome(proposal_id=proposal["proposal_id"], decision="approved",
                   fwd_days=30, fwd_return=0.0, fwd_baseline_diff=0.0)
    with pytest.raises(OutcomeAlreadyRecordedError):
        record_outcome(proposal_id=proposal["proposal_id"], decision="approved",
                       fwd_days=30, fwd_return=0.0, fwd_baseline_diff=0.0)


def test_record_outcome_invalid_decision():
    exp_id = create_experiment(owner_user_id=1, expr_text="t9_inv")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    from services.retrospective_service import RetrospectiveError
    with pytest.raises(RetrospectiveError, match="invalid decision"):
        record_outcome(proposal_id=proposal["proposal_id"], decision="bogus",
                       fwd_days=30, fwd_return=0.0, fwd_baseline_diff=0.0)


# ════════════════════════════════════════════════════════════
#  Retrospective 生成
# ════════════════════════════════════════════════════════════

def test_generate_retrospective_requires_outcome_first():
    exp_id = create_experiment(owner_user_id=1, expr_text="t9_no_outcome")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)

    from services.retrospective_service import RetrospectiveError
    with pytest.raises(RetrospectiveError, match="no outcome"):
        generate_retrospective(proposal_id=proposal["proposal_id"],
                                hypothesis="test", lesson="test")


def test_generate_retrospective_full_flow():
    exp_id = create_experiment(owner_user_id=1, expr_text="t9_full_retro")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
    submit_decision(proposal_id=proposal["proposal_id"], action="approve",
                    expected_version=proposal["version"], actor="user:1",
                    lease_id=proposal["lease_id"], owner_user_id=1)

    record_outcome(proposal_id=proposal["proposal_id"], decision="approved",
                   fwd_days=30, fwd_return=0.03, fwd_baseline_diff=-0.01)

    rid = generate_retrospective(
        proposal_id=proposal["proposal_id"],
        hypothesis="alpha 因子应持续产生 +1% 月收益",
        evidence_summary="OOS 60 天 IR=0.45",
        realized_summary="实际 +3% 但跑输 CSI300 -1%",
        lesson="单因子 alpha 不一定超过 broad index",
        confidence=0.6,
    )
    assert rid > 0

    retros = list_retrospectives(experiment_id=exp_id)
    assert len(retros) == 1
    assert retros[0]["decision"] == "approved"
    assert "alpha" in retros[0]["hypothesis"]


# ════════════════════════════════════════════════════════════
#  List 过滤
# ════════════════════════════════════════════════════════════

def test_list_outcomes_filter_by_decision():
    # 2 个 approved, 1 个 rejected
    decision_map = {"approve": "approved", "reject": "rejected"}
    for i in range(3):
        exp_id = create_experiment(owner_user_id=1, expr_text=f"list_{i}")
        proposal = create_proposal(experiment_id=exp_id, owner_user_id=1)
        action = "approve" if i < 2 else "reject"
        submit_decision(proposal_id=proposal["proposal_id"], action=action,
                        expected_version=proposal["version"], actor="user:1",
                        lease_id=proposal["lease_id"], owner_user_id=1)
        record_outcome(proposal_id=proposal["proposal_id"], decision=decision_map[action],
                       fwd_days=30, fwd_return=0.0, fwd_baseline_diff=0.0)

    # 用 baseline_code 隔离其他测试的 outcome
    unique_baseline = f"test_baseline_{uuid.uuid4().hex[:6]}"
    # 重新跑一遍用 unique baseline — 简化版, 只验证 filter
    # 显式大 limit:确保 filter 子集断言在累计数据下也成立
    # (list_outcomes 默认 limit=100,会让子集关系失效)
    _BIG = 100_000
    rows_all = list_outcomes(limit=_BIG)
    rows_approved = list_outcomes(decision="approved", limit=_BIG)
    rows_rejected = list_outcomes(decision="rejected", limit=_BIG)
    # filter 必须能工作 (不一定严格等于 2/1, 因为其他测试有 outcomes)
    assert all(r["decision"] == "approved" for r in rows_approved)
    assert all(r["decision"] == "rejected" for r in rows_rejected)
    assert len(rows_approved) + len(rows_rejected) <= len(rows_all)


def test_list_retrospectives_filter_by_experiment():
    exp_id_1 = create_experiment(owner_user_id=1, expr_text="r1")
    exp_id_2 = create_experiment(owner_user_id=1, expr_text="r2")

    for eid in [exp_id_1, exp_id_2]:
        proposal = create_proposal(experiment_id=eid, owner_user_id=1)
        submit_decision(proposal_id=proposal["proposal_id"], action="approve",
                        expected_version=proposal["version"], actor="user:1",
                        lease_id=proposal["lease_id"], owner_user_id=1)
        record_outcome(proposal_id=proposal["proposal_id"], decision="approved",
                       fwd_days=30, fwd_return=0.0, fwd_baseline_diff=0.0)
        generate_retrospective(proposal_id=proposal["proposal_id"],
                                hypothesis="", lesson="lesson for " + eid[-4:])

    rows_1 = list_retrospectives(experiment_id=exp_id_1)
    rows_2 = list_retrospectives(experiment_id=exp_id_2)
    assert len(rows_1) == 1
    assert len(rows_2) == 1
    assert rows_1[0]["experiment_id"] == exp_id_1


# ════════════════════════════════════════════════════════════
#  Counterfactual Summary
# ════════════════════════════════════════════════════════════

def test_counterfactual_empty():
    # 用 'since' 限定到 1970 (数据库里不会有那么早的 outcome)
    out = counterfactual_summary(since="1970-01-01", baseline_code="no_such_baseline_xyz")
    assert out["accepted"]["count"] == 0
    assert out["rejected"]["count"] == 0
    assert out["edge"] == 0


def test_counterfactual_accepts_outperform():
    """接受 3 个平均 +2%, 拒绝 2 个平均 -1%, edge = +3%"""
    unique_baseline = f"test_baseline_{uuid.uuid4().hex[:6]}"
    for i in range(3):
        eid = create_experiment(owner_user_id=1, expr_text=f"ca_acc_{i}")
        p = create_proposal(experiment_id=eid, owner_user_id=1)
        submit_decision(proposal_id=p["proposal_id"], action="approve",
                        expected_version=p["version"], actor="user:1",
                        lease_id=p["lease_id"], owner_user_id=1)
        record_outcome(proposal_id=p["proposal_id"], decision="approved",
                       fwd_days=30, fwd_return=0.02, fwd_baseline_diff=0.02,
                       baseline_code=unique_baseline)

    for i in range(2):
        eid = create_experiment(owner_user_id=1, expr_text=f"ca_rej_{i}")
        p = create_proposal(experiment_id=eid, owner_user_id=1)
        submit_decision(proposal_id=p["proposal_id"], action="reject",
                        expected_version=p["version"], actor="user:1",
                        lease_id=p["lease_id"], owner_user_id=1)
        record_outcome(proposal_id=p["proposal_id"], decision="rejected",
                       fwd_days=30, fwd_return=-0.01, fwd_baseline_diff=-0.01,
                       baseline_code=unique_baseline)

    out = counterfactual_summary(baseline_code=unique_baseline)
    assert out["accepted"]["count"] == 3
    assert out["rejected"]["count"] == 2
    # accepted.avg = +0.02, rejected.avg = -0.01, edge = 0.03
    assert abs(out["edge"] - 0.03) < 1e-6
    assert "接受方向对了" in out["interpretation"]


def test_counterfactual_accepts_underperform():
    """接受反拖累 — edge < 0"""
    unique_baseline = f"test_baseline_{uuid.uuid4().hex[:6]}"
    # 接受 2 个 -2%
    for i in range(2):
        eid = create_experiment(owner_user_id=1, expr_text=f"ca_bad_acc_{i}")
        p = create_proposal(experiment_id=eid, owner_user_id=1)
        submit_decision(proposal_id=p["proposal_id"], action="approve",
                        expected_version=p["version"], actor="user:1",
                        lease_id=p["lease_id"], owner_user_id=1)
        record_outcome(proposal_id=p["proposal_id"], decision="approved",
                       fwd_days=30, fwd_return=-0.02, fwd_baseline_diff=-0.02,
                       baseline_code=unique_baseline)

    # 拒绝 2 个 +3%
    for i in range(2):
        eid = create_experiment(owner_user_id=1, expr_text=f"ca_good_rej_{i}")
        p = create_proposal(experiment_id=eid, owner_user_id=1)
        submit_decision(proposal_id=p["proposal_id"], action="reject",
                        expected_version=p["version"], actor="user:1",
                        lease_id=p["lease_id"], owner_user_id=1)
        record_outcome(proposal_id=p["proposal_id"], decision="rejected",
                       fwd_days=30, fwd_return=0.03, fwd_baseline_diff=0.03,
                       baseline_code=unique_baseline)

    out = counterfactual_summary(baseline_code=unique_baseline)
    # accepted.avg = -0.02, rejected.avg = +0.03, edge = -0.05
    assert abs(out["edge"] - (-0.05)) < 1e-6
    assert "接受方向错了" in out["interpretation"]


# ════════════════════════════════════════════════════════════
#  trading_memory 注入
# ════════════════════════════════════════════════════════════

def test_trading_memory_records_proposal_retrospective():
    """复盘应能写进 trading_memory.md, 后续 get_research_lessons 拉出来."""
    from services.trading_memory import TradingMemoryLog
    from pathlib import Path
    tmp_path = Path("/tmp/test_t9_trading_memory.md")
    if tmp_path.exists():
        tmp_path.unlink()
    log = TradingMemoryLog(log_path=str(tmp_path))

    log.record_proposal_retrospective(
        experiment_id="exp-t9-test", proposal_id=42,
        decision="approved", expr_text="ts_rank(close, 5)",
        fwd_return=0.05, fwd_baseline_diff=0.02,
        lesson="alpha is real, hold this candidate",
    )
    assert tmp_path.exists()
    content = tmp_path.read_text(encoding="utf-8")
    assert "proposal:42" in content
    assert "research]" in content
    assert "alpha is real" in content

    lessons = log.get_research_lessons(n=5)
    assert "proposal:42" in lessons
    assert "research" in lessons

    tmp_path.unlink()


def test_get_research_lessons_empty_when_no_records():
    from services.trading_memory import TradingMemoryLog
    tmp_path = Path("/tmp/test_t9_empty_memory.md")
    log = TradingMemoryLog(log_path=str(tmp_path))
    assert log.get_research_lessons() == ""
    tmp_path.unlink(missing_ok=True)


# ════════════════════════════════════════════════════════════
#  E2E: accept → outcome → retrospective → 注入 trading_memory
# ════════════════════════════════════════════════════════════

def test_e2e_full_retrospective_chain():
    from services.trading_memory import TradingMemoryLog
    from pathlib import Path
    tmp_path = Path("/tmp/test_t9_e2e_chain.md")
    if tmp_path.exists():
        tmp_path.unlink()

    # 1. 完整 proposal 链
    exp_id = create_experiment(owner_user_id=1, expr_text="e2e_retro")
    proposal = create_proposal(experiment_id=exp_id, owner_user_id=1,
                                target_lifecycle="validated")
    submit_decision(proposal_id=proposal["proposal_id"], action="approve",
                    expected_version=proposal["version"], actor="user:1",
                    lease_id=proposal["lease_id"], owner_user_id=1)

    # 2. 30 天后: outcome 记录
    record_outcome(proposal_id=proposal["proposal_id"], decision="approved",
                   fwd_days=30, fwd_return=0.08, fwd_baseline_diff=0.03,
                   label="good")

    # 3. retrospective 生成
    rid = generate_retrospective(
        proposal_id=proposal["proposal_id"],
        hypothesis="alpha 因子持续",
        realized_summary="实际 +8%",
        lesson="验证逻辑准确, 因子应该 keep",
        confidence=0.8,
    )
    assert rid > 0

    # 4. 注入 trading_memory
    log = TradingMemoryLog(log_path=str(tmp_path))
    log.record_proposal_retrospective(
        experiment_id=exp_id, proposal_id=proposal["proposal_id"],
        decision="approved", expr_text="e2e_retro",
        fwd_return=0.08, fwd_baseline_diff=0.03,
        lesson="验证逻辑准确, 因子应该 keep",
    )

    # 5. counterfactual 看得到
    out = counterfactual_summary()
    assert out["accepted"]["count"] >= 1

    # 6. trading_memory 能读到
    lessons = log.get_research_lessons(n=10)
    assert f"proposal:{proposal['proposal_id']}" in lessons

    tmp_path.unlink()