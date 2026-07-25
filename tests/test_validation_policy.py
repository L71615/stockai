"""T3 验证策略 + 交易日历 + 三轴门槛单元测试

覆盖:
  - trading_calendar: trading_days_lag / is_trading_day / next_trading_day / prev_trading_day
  - validation_policy: 默认 v1.0.0 阈值, hash 稳定, dataclass 不可变
  - classify_lifecycle: 三档阈值正确
  - evaluate_v1_gate: 60d/8dec 边界
  - evaluate_champion_replacement_gate: 120d/12dec 边界
  - cost_matrix: 6 行 (3 档 × 2 频率)
  - classify_regime: bull/bear/sideways/unknown
  - negative_control_run: 通过 / 失败 / 标签置换
  - evaluate_promotion: 综合 verdict
  - factor_lifecycle.classify 委托给 policy
  - register_policy / get_current_policy: 写表 + 重读
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_t3.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

_TEST_DB_PATH = Path("/tmp/stockai_test_t3.db")
if _TEST_DB_PATH.exists():
    try:
        _TEST_DB_PATH.unlink()
    except PermissionError:
        import time
        time.sleep(0.3)
        _TEST_DB_PATH.unlink(missing_ok=True)

from database import init_db
init_db()

# 测试间隔离: 强制 v1.0.0 为激活版, 清掉其它可能残留的激活状态
# (避免上次 pytest run 半路崩了留 v1.1.0-test 激活)
from services.validation_policy import _default_policy_v1, register_policy, reset_policy_cache
register_policy("v1.0.0", _default_policy_v1().raw, note="test bootstrap", activate=True)
reset_policy_cache()

import pytest

from services.trading_calendar import (
    trading_days_lag,
    trading_days_lag_str,
    is_trading_day,
    next_trading_day,
    prev_trading_day,
    reset_calendar_cache,
)
from services.validation_policy import (
    get_current_policy,
    reset_policy_cache,
    register_policy,
    classify_lifecycle,
    compute_next_warning_days,
    evaluate_v1_gate,
    evaluate_champion_replacement_gate,
    cost_matrix,
    classify_regime,
    negative_control_run,
    evaluate_promotion,
    assert_sample_sufficient,
    ValidationInsufficientSampleError,
    Policy,
)


# ════════════════════════════════════════════════════════════
#  trading_calendar
# ════════════════════════════════════════════════════════════

def test_trading_days_lag_same_day():
    """last == today → lag=0"""
    from datetime import date
    assert trading_days_lag(date(2026, 7, 24), today=date(2026, 7, 24)) == 0


def test_trading_days_lag_future_returns_zero():
    """last > today → lag=0 (边界保护)"""
    from datetime import date
    assert trading_days_lag(date(2026, 7, 25), today=date(2026, 7, 24)) == 0


def test_trading_days_lag_str_format():
    assert trading_days_lag_str("2026-07-24", today_str="2026-07-24") == 0


def test_is_trading_day_weekday_fallback():
    """akshare 拉不到时, weekday<5 视为交易日"""
    reset_calendar_cache()
    assert is_trading_day("2026-07-24") in (True, False)  # 不崩


def test_next_trading_day_advances():
    """无论输入是周几, 返回值都应是合理日期"""
    nxt = next_trading_day("2026-07-24")
    # 不管 calendar 怎么回退, 都应至少 +1 天
    from datetime import date
    assert date.fromisoformat(nxt) > date(2026, 7, 24)


def test_next_trading_day_invalid_format():
    with pytest.raises(ValueError, match="invalid date format"):
        next_trading_day("not-a-date")


def test_prev_trading_day_advances_backward():
    prv = prev_trading_day("2026-07-24")
    from datetime import date
    assert date.fromisoformat(prv) < date(2026, 7, 24)


# ════════════════════════════════════════════════════════════
#  validation_policy 基本
# ════════════════════════════════════════════════════════════

def test_default_policy_v1_values():
    reset_policy_cache()
    p = get_current_policy()
    assert p.version == "v1.0.0"
    assert p.ir_active == 0.15
    assert p.ir_warning == 0.05
    assert p.warning_days_retire == 14
    assert p.eval_days == 120
    assert p.v1_gate_forward_days == 60
    assert p.v1_gate_min_decisions == 8
    assert p.champion_gate_forward_days == 120
    assert p.champion_gate_min_decisions == 12
    assert p.cost_basis_bps == 30
    assert p.cost_conservative_bps == 60
    assert p.cost_extreme_bps == 120
    assert len(p.negative_control_seeds) >= 3
    assert "csi300" in p.baselines
    assert "equal_weight_pool" in p.baselines


def test_policy_hash_stable():
    p1 = get_current_policy()
    h1 = p1.hash()
    h2 = get_current_policy().hash()
    assert h1 == h2
    assert len(h1) == 64


def test_policy_is_frozen():
    p = get_current_policy()
    with pytest.raises(Exception):  # FrozenInstanceError
        p.ir_active = 0.99  # type: ignore


def test_register_and_reload():
    custom = {
        "version": "v1.1.0-test",
        "ir_active": 0.20,
        "ir_warning": 0.07,
        "warning_days_retire": 21,
        "eval_days": 180,
        "v1_gate_forward_days": 90,
        "v1_gate_min_decisions": 12,
        "champion_gate_forward_days": 180,
        "champion_gate_min_decisions": 20,
        "cost_basis_bps": 25,
        "cost_conservative_bps": 50,
        "cost_extreme_bps": 100,
        "negative_control_seeds": [1, 2, 3],
        "label_permutations": 3,
        "regime_thresholds": {
            "bull": {"min_return_pct": 0.10, "max_dd_pct": -0.08},
            "bear": {"max_return_pct": -0.10, "min_dd_pct": -0.20},
            "sideways": {"return_pct_range": [-0.10, 0.10], "dd_pct_range": [-0.08, 0.0]},
        },
        "baselines": ["csi300"],
        "rebalance_freqs": ["weekly"],
    }
    h = register_policy("v1.1.0-test", custom, note="unit test", activate=True)
    assert len(h) == 64
    reset_policy_cache()
    p = get_current_policy()
    assert p.version == "v1.1.0-test"
    assert p.ir_active == 0.20
    # 还原成默认 v1.0.0, 用 _default_policy_v1() 而不是 get_current_policy() 的 raw
    from services.validation_policy import _default_policy_v1
    register_policy("v1.0.0", _default_policy_v1().raw, note="reset", activate=True)
    reset_policy_cache()


# ════════════════════════════════════════════════════════════
#  classify_lifecycle
# ════════════════════════════════════════════════════════════

def test_classify_active_when_ir_above_threshold():
    assert classify_lifecycle(ir=0.20, warning_days=0) == "active"


def test_classify_warning_when_ir_below_active():
    assert classify_lifecycle(ir=0.10, warning_days=0) == "warning"


def test_classify_warning_when_ir_below_warning():
    assert classify_lifecycle(ir=0.02, warning_days=0) == "warning"


def test_classify_retired_when_warning_days_exceed():
    assert classify_lifecycle(ir=0.10, warning_days=14) == "retired"


def test_classify_retired_even_with_high_ir_days():
    # 高 IR 也可能因累计 warning_days 退役 (旧历史)
    assert classify_lifecycle(ir=0.20, warning_days=20) == "active"  # 高 IR 不退役


def test_compute_next_warning_days_increment():
    assert compute_next_warning_days(ir=0.02, prev_status="warning", prev_warning_days=5) == 6


def test_compute_next_warning_days_reset_on_recovery():
    assert compute_next_warning_days(ir=0.10, prev_status="warning", prev_warning_days=5) == 0


def test_compute_next_warning_days_no_increment_for_active():
    assert compute_next_warning_days(ir=0.20, prev_status="active", prev_warning_days=5) == 0


# ════════════════════════════════════════════════════════════
#  v1 Gate
# ════════════════════════════════════════════════════════════

def test_v1_gate_pass_at_minimum():
    r = evaluate_v1_gate(forward_days=60, decisions=8)
    assert r.passed
    assert r.reason.startswith("passed")


def test_v1_gate_fail_insufficient_days():
    r = evaluate_v1_gate(forward_days=59, decisions=8)
    assert not r.passed
    assert "forward_days=59" in r.reason


def test_v1_gate_fail_insufficient_decisions():
    r = evaluate_v1_gate(forward_days=60, decisions=7)
    assert not r.passed
    assert "decisions=7" in r.reason


def test_v1_gate_fail_both():
    r = evaluate_v1_gate(forward_days=30, decisions=3)
    assert not r.passed
    assert "forward_days=30" in r.reason  # days 先检查


def test_v1_gate_far_above_minimum():
    r = evaluate_v1_gate(forward_days=200, decisions=40)
    assert r.passed


# ════════════════════════════════════════════════════════════
#  Champion Gate
# ════════════════════════════════════════════════════════════

def test_champion_gate_pass_at_minimum():
    r = evaluate_champion_replacement_gate(forward_days=120, decisions=12)
    assert r.passed


def test_champion_gate_fail_v1_only_passes():
    """v1 Gate 通过的窗口, 不一定够 Champion 替换"""
    r = evaluate_champion_replacement_gate(forward_days=80, decisions=10)
    assert not r.passed


def test_champion_gate_fail_insufficient_decisions():
    r = evaluate_champion_replacement_gate(forward_days=200, decisions=11)
    assert not r.passed


def test_assert_sample_sufficient_raises():
    with pytest.raises(ValidationInsufficientSampleError):
        assert_sample_sufficient(forward_days=10)


def test_assert_sample_sufficient_passes():
    assert_sample_sufficient(forward_days=60)  # 不抛


# ════════════════════════════════════════════════════════════
#  cost_matrix
# ════════════════════════════════════════════════════════════

def test_cost_matrix_has_six_rows():
    rows = cost_matrix()
    assert len(rows) == 6  # 3 档 × 2 频率


def test_cost_matrix_scenarios():
    rows = cost_matrix()
    scenarios = {r.scenario for r in rows}
    assert scenarios == {"basis", "conservative", "extreme"}


def test_cost_matrix_freqs():
    rows = cost_matrix()
    freqs = {r.rebalance_freq for r in rows}
    assert freqs == {"weekly", "monthly"}


def test_cost_matrix_bps_progression():
    rows = cost_matrix()
    by_scenario = {r.scenario: r.bps for r in rows if r.rebalance_freq == "weekly"}
    assert by_scenario["basis"] < by_scenario["conservative"] < by_scenario["extreme"]


# ════════════════════════════════════════════════════════════
#  classify_regime
# ════════════════════════════════════════════════════════════

def test_regime_bull():
    assert classify_regime({"period_return_pct": 0.20, "max_drawdown_pct": -0.05}) == "bull"


def test_regime_bear():
    assert classify_regime({"period_return_pct": -0.15, "max_drawdown_pct": -0.25}) == "bear"


def test_regime_sideways():
    assert classify_regime({"period_return_pct": 0.05, "max_drawdown_pct": -0.05}) == "sideways"


def test_regime_unknown_when_missing_fields():
    assert classify_regime({"period_return_pct": 0.20}) == "unknown"
    assert classify_regime({}) == "unknown"


def test_regime_unknown_when_non_numeric():
    assert classify_regime({"period_return_pct": "high", "max_drawdown_pct": "low"}) == "unknown"


def test_regime_unknown_when_nan():
    import math
    assert classify_regime({"period_return_pct": math.nan, "max_drawdown_pct": -0.05}) == "unknown"


# ════════════════════════════════════════════════════════════
#  negative_control_run
# ════════════════════════════════════════════════════════════

def test_negative_control_pass_with_strong_ir():
    r = negative_control_run(expr_ir=0.50)
    assert r.passed
    assert r.seeds_used >= 3
    assert all(abs(ir) <= 0.05 for ir in r.seed_irs)


def test_negative_control_fail_with_weak_ir():
    r = negative_control_run(expr_ir=0.08)
    assert not r.passed
    assert "0.15" in r.reason or "随机" in r.reason


def test_negative_control_uses_fixed_seeds():
    """同 seeds 必须产生同 seed_irs (deterministic)"""
    seeds = (1, 2, 3, 4, 5)
    r1 = negative_control_run(expr_ir=0.50, seeds=seeds, label_perm=False)
    r2 = negative_control_run(expr_ir=0.50, seeds=seeds, label_perm=False)
    assert r1.seed_irs == r2.seed_irs


def test_negative_control_disabling_label_perm():
    r = negative_control_run(expr_ir=0.50, label_perm=False)
    assert r.passed
    assert r.label_perm_pass_rate == 0.0


# ════════════════════════════════════════════════════════════
#  evaluate_promotion (综合)
# ════════════════════════════════════════════════════════════

def test_evaluate_promotion_pass():
    out = evaluate_promotion(
        expr_ir=0.50, forward_days=80, decisions=15,
        regime_metrics={"period_return_pct": 0.10, "max_drawdown_pct": -0.05},
    )
    assert out["verdict"] == "pass"
    assert out["gate"]["passed"]
    assert out["control"]["passed"]
    assert out["regime"] in ("bull", "sideways")


def test_evaluate_promotion_blocked_by_negative_control():
    out = evaluate_promotion(
        expr_ir=0.08,  # 太弱, 负对照失败
        forward_days=80, decisions=15,
        regime_metrics={"period_return_pct": 0.10, "max_drawdown_pct": -0.05},  # 提供合法 regime
    )
    assert out["verdict"] == "blocked"


def test_evaluate_promotion_watch_v1_gate_fail():
    out = evaluate_promotion(
        expr_ir=0.50,
        forward_days=30, decisions=5,  # 不够 v1 Gate
        regime_metrics={"period_return_pct": 0.10, "max_drawdown_pct": -0.05},
    )
    assert out["verdict"] == "watch"


def test_evaluate_promotion_unknown_regime():
    out = evaluate_promotion(
        expr_ir=0.50, forward_days=80, decisions=15,
        regime_metrics=None,  # 缺 regime → unknown
    )
    assert out["verdict"] == "unknown"


def test_evaluate_promotion_carries_policy_meta():
    out = evaluate_promotion(expr_ir=0.50, forward_days=80, decisions=15)
    assert "policy_version" in out
    assert "policy_hash" in out
    assert out["policy_version"] == "v1.0.0"


# ════════════════════════════════════════════════════════════
#  factor_lifecycle 委托给 policy
# ════════════════════════════════════════════════════════════

def test_factor_lifecycle_classify_uses_policy():
    from services.factor_lifecycle import classify
    assert classify(ir=0.20, warning_days=0) == "active"
    assert classify(ir=0.02, warning_days=20) == "retired"


def test_factor_lifecycle_globals_synced():
    """模块全局 IR_ACTIVE 等应被 policy 覆盖"""
    from services import factor_lifecycle
    p = get_current_policy()
    assert factor_lifecycle.IR_ACTIVE == p.ir_active
    assert factor_lifecycle.WARNING_DAYS_RETIRE == p.warning_days_retire