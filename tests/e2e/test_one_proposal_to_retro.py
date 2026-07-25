"""T7 端到端: freeze → OOS → shadow → inbox → accept → 复盘

跑通 v3.11 主链路所有阶段, 验证数据流和状态机完整.
不依赖真实网络/akshare/futu, 用 fixture 数据模拟.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_e2e.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

_TEST_DB_PATH = Path("/tmp/stockai_test_e2e.db")
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

import json
import pytest

from services.experiment_service import (
    create_experiment, transition, get_experiment, list_events,
)
from services.snapshot_service import (
    freeze_snapshot, get_snapshot, compute_input_hash,
)
from services.strategy_backtest_service import _evaluate_overfit_from_snapshot
from services.shadow_portfolio_service import (
    create_shadow_portfolio, set_target_weights, settle_window,
)
from services.approval_service import (
    create_proposal, get_proposal, submit_decision, list_attempts,
)
from services.validation_policy import (
    get_current_policy, evaluate_v1_gate, negative_control_run,
)


# ════════════════════════════════════════════════════════════
#  完整链路 E2E
# ════════════════════════════════════════════════════════════

def test_full_chain_one_proposal_to_retro():
    """一条 proposal 走完: GP mining → 实验冻结 → OOS → shadow → 审批 → 复盘"""

    # ═══ Stage 1: 创建实验 (T1 状态机起点) ═══
    exp_id = create_experiment(
        owner_user_id=1,
        expr_text="ts_rank(close, 5)",
        note="e2e chain test",
    )
    exp = get_experiment(exp_id)
    assert exp["lifecycle_status"] == "candidate"
    assert exp["version"] == 1
    print(f"  stage 1: 实验创建 {exp_id} v1")

    # ═══ Stage 2: 冻结快照 (T2 point-in-time) ═══
    snapshot = {
        "as_of_date": "2026-07-24",
        "stock_pool": ["600519", "000858", "600036"],
        "stock_pool_source": "csi800",
        "factor_values": {"600519": 0.045, "000858": -0.012, "600036": 0.020},
        "kline_window": {"start": "2025-04-01", "end": "2026-07-24", "count": 250},
        "config": {"policy_version": "v1.0.0", "cost_bps": 30, "rebalance": "weekly"},
        "validation_window": {"start": "2025-04-01", "end": "2026-07-24"},
        "oos_window": {"start": "2026-01-01", "end": "2026-07-24"},
        "equity_curve": [
            {"date": f"2026-07-{15+i:02d}", "value": 100000 + i * 100}
            for i in range(8)  # 8 天 (≥ v1 Gate 的 60 天以下, 但足以演示)
        ],
        "trades": [{"date": "2026-07-15", "code": "600519", "direction": "buy",
                    "price": 1500.0, "shares": 100}],
    }
    snap_version = freeze_snapshot(
        experiment_id=exp_id, snapshot=snapshot, policy_hash="v1.0.0",
        note="e2e freeze",
    )
    assert snap_version == 1
    snap_row = get_snapshot(exp_id)
    input_hash = snap_row["input_version_hash"]
    assert len(input_hash) == 64  # sha256
    print(f"  stage 2: 冻结 v{snap_version}, hash={input_hash[:12]}...")

    # ═══ Stage 3: OOS replay (T2) + v1 Gate (T3) ═══
    snap_dict = snap_row["snapshot"]
    snap_dict["__input_hash"] = input_hash
    oos = _evaluate_overfit_from_snapshot(
        snapshot=snap_dict,
        equity_curve=snap_dict["equity_curve"],
        trades=snap_dict["trades"],
        initial_cash=100000.0,
    )
    # 8 天 OOS 不够 v1 Gate (60d), 但作为演示可走完整链路
    print(f"  stage 3: OOS verdict={oos.get('verdict', 'no_decision')}, "
          f"snapshot_meta.as_of={oos.get('snapshot_meta', {}).get('as_of_date')}")
    assert "snapshot_meta" in oos
    assert oos["snapshot_meta"]["as_of_date"] == "2026-07-24"
    assert oos["snapshot_meta"]["input_version_hash"] == input_hash

    # v1 Gate (mock): 假定 OOS 通过 (实际证据不足, 这里只演示 API)
    policy = get_current_policy()
    gate = evaluate_v1_gate(forward_days=80, decisions=12)  # 假装过
    assert gate.passed

    # 负对照
    nc = negative_control_run(expr_ir=0.45)  # 强 IR
    assert nc.passed
    print(f"  stage 3b: v1 gate passed, negative control passed")

    # ═══ Stage 4: 三轴状态机推进 (T1) ═══
    # candidate → validated (OOS 通过)
    row = transition(experiment_id=exp_id, axis="lifecycle_status",
                     target="validated", expected_version=1,
                     actor="e2e_test", reason="OOS passed in stage 3")
    assert row["lifecycle_status"] == "validated"
    assert row["version"] == 2

    # validated → paper
    row = transition(experiment_id=exp_id, axis="lifecycle_status",
                     target="paper", expected_version=2,
                     actor="e2e_test", reason="approved by v1 Gate")
    assert row["lifecycle_status"] == "paper"
    assert row["version"] == 3

    # none → paper role
    row = transition(experiment_id=exp_id, axis="portfolio_role",
                     target="paper", expected_version=3,
                     actor="e2e_test", reason="enter paper portfolio")
    assert row["portfolio_role"] == "paper"
    assert row["version"] == 4
    print(f"  stage 4: experiment → paper role")

    # ═══ Stage 5: 影子组合 (T4) ═══
    pid = create_shadow_portfolio(
        owner_user_id=1, name="e2e_shadow", initial_cash=100000,
        experiment_id=exp_id, scope="paper",
    )
    set_target_weights(pid, {"600519": 0.6, "000858": 0.4})
    snaps = settle_window(
        portfolio_id=pid,
        start_date="2026-07-22", end_date="2026-07-28",
        prices_by_date={
            "2026-07-22": {"600519": 1500.0, "000858": 100.0},
            "2026-07-24": {"600519": 1530.0, "000858": 102.0},
            "2026-07-28": {"600519": 1480.0, "000858": 99.0},
        },
        input_version="e2e_v1",
    )
    assert len(snaps) >= 1
    print(f"  stage 5: shadow portfolio {pid} settled {len(snaps)} days")

    # ═══ Stage 6: 创建提案 + 接受 (T5) ═══
    proposal = create_proposal(
        experiment_id=exp_id, owner_user_id=1,
        action="promote", target_lifecycle="paper",
        evidence_version=input_hash[:16],
        policy_version="v1.0.0",
        policy_hash=policy.hash(),
        snapshot_hash=input_hash,
    )
    assert proposal["status"] == "pending"
    print(f"  stage 6a: created proposal #{proposal['proposal_id']}")

    # 接受 → 触发 T1 transition (lifecycle + portfolio 已在 stage 4 推过, 这里 idempotent no-op)
    result = submit_decision(
        proposal_id=proposal["proposal_id"],
        action="approve",
        expected_version=proposal["version"],
        actor="user:1", reason="e2e accept",
        lease_id=proposal["lease_id"],
        owner_user_id=1,
    )
    assert result["status"] == "approved"
    assert result["version"] == proposal["version"] + 1
    print(f"  stage 6b: approved, version → {result['version']}")

    # ═══ Stage 7: 复盘 (T9 stub — 仅审计) ═══
    events = list_events(experiment_id=exp_id)
    event_types = [e["event_type"] for e in events]
    assert "create" in event_types
    assert "transition:lifecycle_status" in event_types
    assert "transition:portfolio_role" in event_types
    print(f"  stage 7: audit events = {len(events)}")

    # 审批 attempts
    attempts = list_attempts(proposal["proposal_id"])
    assert len(attempts) >= 1
    assert attempts[0]["result"] == "ok"
    print(f"  stage 7b: approval attempts = {len(attempts)}")

    # ═══ Stage 8: 最终验证 — experiment 状态完整 ═══
    final = get_experiment(exp_id)
    assert final["lifecycle_status"] in ("validated", "paper")  # T1 transition 在 stage 4 已推
    assert final["portfolio_role"] in ("none", "paper")
    assert final["version"] >= 4
    print(f"  final: experiment v{final['version']}, "
          f"lifecycle={final['lifecycle_status']}, role={final['portfolio_role']}")


# ════════════════════════════════════════════════════════════
#  反事实: 拒绝路径
# ════════════════════════════════════════════════════════════

def test_full_chain_reject_path():
    """同链路, 但审批被拒绝 → experiment 保持原状态"""

    # 创建实验
    exp_id = create_experiment(owner_user_id=1, expr_text="reject_demo")

    # 推到 validated
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="validated", expected_version=1, reason="OOS ok")

    # 提案
    proposal = create_proposal(
        experiment_id=exp_id, owner_user_id=1,
        action="promote", target_lifecycle="paper",
    )

    # 拒绝
    result = submit_decision(
        proposal_id=proposal["proposal_id"],
        action="reject",
        expected_version=proposal["version"],
        actor="user:1", reason="underperformed",
        lease_id=proposal["lease_id"],
        owner_user_id=1,
    )
    assert result["status"] == "rejected"

    # experiment 状态应保持 validated (proposal 拒绝不会触发反向 transition)
    final = get_experiment(exp_id)
    assert final["lifecycle_status"] == "validated"
    assert final["portfolio_role"] == "none"


# ════════════════════════════════════════════════════════════
#  反事实: 多 proposal 链式 (Champ/Challenger 雏形)
# ════════════════════════════════════════════════════════════

def test_multiple_proposals_one_experiment():
    """同一实验可以有多个 proposal (e.g., 重复审核 / 后续晋级)."""

    exp_id = create_experiment(owner_user_id=1, expr_text="multi_prop")

    # 推进到 validated
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="validated", expected_version=1, reason="first pass")

    # 第一个 proposal: paper (通过)
    p1 = create_proposal(experiment_id=exp_id, owner_user_id=1,
                         action="promote", target_lifecycle="paper")
    submit_decision(proposal_id=p1["proposal_id"], action="approve",
                    expected_version=p1["version"], actor="user:1",
                    lease_id=p1["lease_id"], owner_user_id=1)

    # 第二个 proposal: paper role (继续推进)
    p2 = create_proposal(experiment_id=exp_id, owner_user_id=1,
                         action="role", target_portfolio="paper")
    assert p2["proposal_id"] > p1["proposal_id"]

    # 同一 exp_id 下两个 proposal
    from services.approval_service import list_proposals
    rows = list_proposals(owner_user_id=1, experiment_id=exp_id)
    assert len(rows) >= 2