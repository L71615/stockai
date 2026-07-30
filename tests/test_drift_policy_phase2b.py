"""v4.1 Phase 2B — Drift 接入 experiment_runs.done + 阈值版本化

覆盖:
  - load_active_policy: 取 drift_policies 当前生效 policy
  - run_drift_check: pipeline_status != 'done' → 跳过 (events_written=0)
  - run_drift_check: pipeline_status='done' → 走完整流程 + baseline_value 真实填
  - run_drift_check: skip_pipeline_gate=True 测试旁路
  - drift_policies 表 schema + 默认 v1.0-default policy 已建
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest


# ─────────────────────── Fixtures ───────────────────────


@pytest.fixture(autouse=True)
def _clean_tables(_test_db_session):
    """清理运行时表 + 清理非 default 的 drift_policies, 避免 cross-test 污染.

    v1.0-default 是 init_db 自动插入的 baseline, 保留; 其它测试自己插入的 override 删除.
    """
    from database import execute
    for tbl in ("drift_events", "experiment_runs", "users", "experiments"):
        try:
            execute(f"DELETE FROM {tbl}")
        except Exception:
            pass
    try:
        execute("DELETE FROM drift_policies WHERE version != 'v1.0-default'")
    except Exception:
        pass


def _seed_experiment_run(*, status: str, finished_at: str) -> None:
    """插入 experiment_runs 记录 — 需要先 seed users + experiments (FK 链)."""
    from database import execute, query_one
    # 复用 init_db 自动建的 admin 用户 (id=1)
    user = query_one("SELECT id FROM users LIMIT 1")
    if not user:
        execute(
            "INSERT INTO users (username, email, password) VALUES ('admin','a@b.c','x')"
        )
        user = query_one("SELECT id FROM users LIMIT 1")
    execute(
        """INSERT INTO experiments
           (experiment_id, owner_user_id, expr_text, created_at, updated_at)
           VALUES (?, ?, 'test', ?, ?)""",
        (f"exp-{finished_at}", user["id"], finished_at, finished_at),
    )
    execute(
        """INSERT INTO experiment_runs
           (experiment_id, scope, status, current_step, started_at, finished_at, error_json)
           VALUES (?, 'pipeline', ?, '', ?, ?, '{}')""",
        (f"exp-{finished_at}", status, finished_at, finished_at),
    )


# ─────────────────────── schema + 默认 policy ───────────────────────


def test_init_db_creates_drift_policies_with_default():
    """init_db 应建 drift_policies 表 + 默认 v1.0-default policy."""
    from database import query_all, query_one

    tables = {r["name"] for r in query_all(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "drift_policies" in tables

    row = query_one("SELECT version, psi_warn, psi_severe FROM drift_policies WHERE version='v1.0-default'")
    assert row is not None
    assert abs(float(row["psi_warn"]) - 0.10) < 1e-9
    assert abs(float(row["psi_severe"]) - 0.25) < 1e-9


# ─────────────────────── load_active_policy ───────────────────────


def test_load_active_policy_returns_default_when_no_policy():
    """无任何 policy → 返回 DEFAULT_THRESHOLDS."""
    from database import execute
    # 临时删除所有 policy, 测试后不恢复 (conftest session DB 重启时 init_db 会重建)
    execute("DELETE FROM drift_policies")
    from services.drift_policy import load_active_policy, DEFAULT_THRESHOLDS

    th = load_active_policy(as_of="2026-07-29")
    assert th.psi_warn == DEFAULT_THRESHOLDS.psi_warn
    assert th.kl_severe == DEFAULT_THRESHOLDS.kl_severe
    # 重建默认 policy 防止下一个测试受影响
    execute(
        """INSERT INTO drift_policies
           (version, psi_warn, psi_severe, kl_warn, kl_severe, bins,
            effective_from, created_by, note, created_at)
           VALUES ('v1.0-default', 0.10, 0.25, 0.10, 0.50, 10,
                   ?, 'system', 'rebuild after test', ?)""",
        ("2026-07-30", "2026-07-30"),
    )


def test_load_active_policy_picks_effective_one(monkeypatch):
    """v1.0-default 在有效期内 → 返回其值."""
    from database import query_all
    rows = query_all("SELECT COUNT(*) AS c FROM drift_policies")
    assert rows[0]["c"] >= 1  # init_db 自动建了

    from services.drift_policy import load_active_policy
    th = load_active_policy(as_of=datetime.now().strftime("%Y-%m-%d"))
    # v1.0-default 数值
    assert th.psi_warn == pytest.approx(0.10, abs=1e-9)


def test_load_active_policy_picks_strict_override():
    """插一条今日生效的更严格 policy → 切换阈值."""
    from database import execute
    today = datetime.now().strftime("%Y-%m-%d")
    execute(
        """INSERT INTO drift_policies
           (version, psi_warn, psi_severe, kl_warn, kl_severe, bins,
            effective_from, created_by, note, created_at)
           VALUES ('v2.0-strict', 0.05, 0.15, 0.05, 0.30, 10,
                   ?, 'test', '更严格阈值 — 测试', ?)""",
        (today, today),
    )
    from services.drift_policy import load_active_policy
    th = load_active_policy(as_of=today)
    assert th.psi_warn == pytest.approx(0.05, abs=1e-9)
    assert th.psi_severe == pytest.approx(0.15, abs=1e-9)


# ─────────────────────── run_drift_check pipeline gate ───────────────────────


_FAKE_FACTOR_SERIES = {
    "alpha_158_momentum_20": [(-2.0 + i * 0.08) for i in range(50)],
    "alpha_158_volatility_60": [(0.5 + i * 0.05) for i in range(50)],
    "alpha_158_volume_ratio_20": [(0.1 + i * 0.02) for i in range(50)],
    "csi300_momentum_20": [(-1.0 + i * 0.04) for i in range(50)],
}


@pytest.fixture(autouse=True)
def _patch_factor_read(monkeypatch):
    """所有 Phase 2B test 都 monkeypatch _read_factor_series — 不依赖 factor_snapshot 表."""
    from backend.services import drift_monitor
    monkeypatch.setattr(
        drift_monitor, "_read_factor_series",
        lambda f: _FAKE_FACTOR_SERIES.get(f, []),
    )


def test_run_drift_check_skips_when_pipeline_not_done():
    """pipeline_status=running → 跳过, events_written=0, skip_reason 含 status."""
    from backend.services import drift_monitor

    _seed_experiment_run(status="running", finished_at="2026-07-29 22:00:00")

    result = drift_monitor.run_drift_check(snapshot_at="2026-07-29")

    assert result["events_written"] == 0
    assert result["pipeline_status"] == "running"
    assert "skipped_reason" in result
    assert "running" in result["skipped_reason"]

    from database import query_all
    rows = query_all("SELECT COUNT(*) AS c FROM drift_events")
    assert rows[0]["c"] == 0


def test_run_drift_check_skips_when_no_experiment_runs():
    """experiment_runs 表空 → pipeline_status=None → 跳过."""
    from backend.services import drift_monitor

    result = drift_monitor.run_drift_check(snapshot_at="2026-07-29")

    assert result["events_written"] == 0
    assert result["pipeline_status"] is None
    assert "skipped_reason" in result


def test_run_drift_check_runs_when_pipeline_done(monkeypatch):
    """pipeline_status='done' → 走完整流程, baseline_value 真实填值."""
    from backend.services import drift_monitor

    today_str = datetime.now().strftime("%Y-%m-%d")
    _seed_experiment_run(status="done", finished_at=f"{today_str} 22:30:00")

    # 屏蔽 notify
    monkeypatch.setattr(
        "backend.services.notify_service.send_notification",
        lambda **kwargs: {"ok": True},
        raising=False,
    )

    result = drift_monitor.run_drift_check(snapshot_at=today_str)

    assert result["pipeline_status"] == "done"
    assert result["policy_version"] == "v1.0-default"
    # 4 factors × 2 metrics = 8 行
    assert result["events_written"] >= 8

    # baseline_value 真实填值 — 无历史 → 应为 None
    from database import query_all
    rows = query_all(
        "SELECT factor_name, metric_type, baseline_value FROM drift_events "
        "WHERE factor_name='alpha_158_momentum_20' AND snapshot_at = ?",
        (today_str,),
    )
    assert len(rows) == 2
    for r in rows:
        # 历史<5 → None
        assert r["baseline_value"] is None


def test_run_drift_check_baseline_value_filled_when_history_enough(monkeypatch):
    """历史 drift_events >=5 → baseline_value 填历史均值."""
    from backend.services import drift_monitor
    from database import execute

    _seed_experiment_run(status="done", finished_at="2026-07-29 22:30:00")

    # 历史 5 条同 metric 同 factor (snapshot_at 须在最近 30 天内)
    today = datetime.now()
    for i in range(5):
        snap = (today - timedelta(days=5 + i)).strftime("%Y-%m-%d")
        execute(
            """INSERT INTO drift_events
               (factor_name, metric_type, value, baseline_value,
                threshold_warn, threshold_severe, severity,
                snapshot_at, baseline_as_of, n_baseline, n_current)
               VALUES ('alpha_158_momentum_20', 'psi', ?, NULL,
                       0.1, 0.25, 'none', ?, '2026-07-15', 50, 50)""",
            (0.05 + i * 0.01, snap),
        )

    monkeypatch.setattr(
        "backend.services.notify_service.send_notification",
        lambda **kwargs: {"ok": True},
        raising=False,
    )

    today_str = today.strftime("%Y-%m-%d")
    drift_monitor.run_drift_check(snapshot_at=today_str)

    from database import query_all
    rows = query_all(
        "SELECT metric_type, baseline_value FROM drift_events "
        "WHERE factor_name='alpha_158_momentum_20' AND snapshot_at = ?",
        (today_str,),
    )
    psi_row = next(r for r in rows if r["metric_type"] == "psi")
    # 5 条历史 (0.05, 0.06, 0.07, 0.08, 0.09) 均值 ≈ 0.07
    assert psi_row["baseline_value"] is not None
    assert 0.06 < float(psi_row["baseline_value"]) < 0.08


def test_run_drift_check_skip_pipeline_gate_bypass(monkeypatch):
    """skip_pipeline_gate=True 测试旁路 — 即使无 pipeline run 也跑."""
    from backend.services import drift_monitor

    monkeypatch.setattr(
        "backend.services.notify_service.send_notification",
        lambda **kwargs: {"ok": True},
        raising=False,
    )

    result = drift_monitor.run_drift_check(
        snapshot_at="2026-07-29", skip_pipeline_gate=True,
    )

    assert result["events_written"] >= 8
    assert "skipped_reason" not in result

