"""v4.1 Phase 2A — 漂移检测纯函数 + orchestrator

覆盖:
  - PSI / KL 数学正确性 (identical → 0, shifted → >0)
  - 三档分类 (none / warning / severe)
  - 边界 (empty / constant)
  - run_drift_check 写表 (monkeypatched factor_snapshot)
"""
from __future__ import annotations

import math

import pytest


# ─────────────────────── 纯函数 ───────────────────────


def test_compute_psi_identical_is_zero():
    from backend.services.drift_policy import compute_psi

    b = [1.0, 2, 3, 4, 5] * 20
    psi = compute_psi(b, b)
    assert math.isnan(psi) is False
    assert abs(psi) < 1e-6


def test_compute_psi_shifted_distribution_positive():
    from backend.services.drift_policy import compute_psi

    baseline = [1.0, 2, 3, 4, 5] * 20
    current  = [6.0, 7, 8, 9, 10] * 20
    psi = compute_psi(baseline, current)
    assert psi > 0.2, f"expected significant drift, got psi={psi}"


def test_compute_kl_zero_when_identical():
    from backend.services.drift_policy import compute_kl

    b = [1.0, 2, 3, 4, 5] * 20
    kl = compute_kl(b, b)
    assert math.isnan(kl) is False
    assert abs(kl) < 1e-6


def test_classify_drift_thresholds():
    """三档表驱动.

    psi 阈值: warn=0.10, severe=0.25 (默认)
    kl  阈值: warn=0.10, severe=0.50 (默认)
    任一指标跨越阈值即跨越对应 severity 档.
    """
    from backend.services.drift_policy import classify_drift, DEFAULT_THRESHOLDS

    th = DEFAULT_THRESHOLDS
    cases = [
        # (psi, kl, expected_severity)
        (0.0, 0.0, "none"),
        (0.05, 0.05, "none"),
        (0.15, 0.20, "warning"),   # psi>=warn, kl<severe
        (0.20, 0.05, "warning"),   # psi alone warning
        (0.05, 0.30, "warning"),   # kl alone warning
        (0.30, 0.20, "severe"),    # psi alone severe (>=0.25)
        (0.30, 0.60, "severe"),    # both severe
        (0.05, 0.60, "severe"),    # kl alone severe (>=0.50)
        (0.30, 0.05, "severe"),    # psi alone severe
    ]
    for psi, kl, expected in cases:
        got = classify_drift(psi, kl, th)
        assert got == expected, f"psi={psi} kl={kl} → {got}, expected {expected}"


def test_compute_psi_small_sample_returns_nan():
    from backend.services.drift_policy import compute_psi

    assert math.isnan(compute_psi([1.0], [2.0]))
    assert math.isnan(compute_psi([1.0, 2], [2.0]))  # < 5


def test_compute_psi_constant_returns_finite():
    """全相等值 — 不应除零, PSI 应为 0 (identical constant)."""
    from backend.services.drift_policy import compute_psi

    b = [5.0] * 100
    psi = compute_psi(b, b)
    assert math.isfinite(psi), f"got {psi}"
    assert abs(psi) < 1e-3


# ─────────────────────── Orchestrator ───────────────────────


@pytest.fixture(autouse=True)
def _clean_tables(_test_db_session):
    from database import execute
    for tbl in ("drift_events", "factor_snapshot"):
        try:
            execute(f"DELETE FROM {tbl}")
        except Exception:
            pass


def test_run_drift_check_writes_events_for_watch_factors(monkeypatch):
    """monkeypatch factor_snapshot 读路径 → 至少 4 行入 drift_events."""
    from backend.services import drift_monitor

    # 准备 factor_snapshot — 50 只股票上每个 WATCH_FACTOR 都有一行
    factor_values = {}
    for factor in drift_monitor.WATCH_FACTORS:
        # baseline / current 用同一组 (Phase 2A trivial), 真实值 -2 ~ +2 分布
        factor_values[factor] = [(-2.0 + i * 0.08) for i in range(50)]

    def fake_read(factor_name):
        return factor_values.get(factor_name, [])

    monkeypatch.setattr(drift_monitor, "_read_factor_series", fake_read)
    # 屏蔽 notify 副作用
    monkeypatch.setattr(
        "backend.services.notify_service.send_notification",
        lambda **kwargs: {"ok": True},
        raising=False,
    )

    # Phase 2B 加了 pipeline_status='done' gate — 测试单元不依赖 pipeline 状态, 旁路
    result = drift_monitor.run_drift_check(skip_pipeline_gate=True)

    # Phase 2A trivial: baseline == current 同一组 → PSI ≈ 0, severity='none'
    assert result["events_written"] >= 4, f"unexpected writes: {result}"
    assert result["by_severity"].get("severe", 0) == 0
    # 4 因子 × 2 metric (psi, kl) = 8 行
    rows = drift_monitor.query_all("SELECT COUNT(*) AS c FROM drift_events")
    assert rows[0]["c"] >= 4


def test_run_drift_check_skips_insufficient_factors(monkeypatch):
    """samples<5 的因子被 skip, 但其它因子仍写."""
    from backend.services import drift_monitor
    from database import execute

    # 第 1 个因子: 只 2 行样本, 其余 OK
    insufficient = {drift_monitor.WATCH_FACTORS[0]: [1.0, 2.0]}
    for factor in drift_monitor.WATCH_FACTORS[1:]:
        insufficient[factor] = [(-2.0 + i * 0.08) for i in range(50)]

    monkeypatch.setattr(
        drift_monitor, "_read_factor_series",
        lambda f: insufficient.get(f, []),
    )

    # Phase 2B 加了 pipeline_status='done' gate — 测试单元不依赖 pipeline 状态, 旁路
    result = drift_monitor.run_drift_check(skip_pipeline_gate=True)
    skipped = result.get("skipped_factors", [])
    assert drift_monitor.WATCH_FACTORS[0] in skipped
    # 其余 3 因子 × 2 metric = 6 行
    rows = drift_monitor.query_all("SELECT COUNT(*) AS c FROM drift_events")
    assert rows[0]["c"] == 6
