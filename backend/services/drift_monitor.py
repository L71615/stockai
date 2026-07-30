"""v4.1 Phase 2A/2B: 漂移 orchestrator — 读 factor_snapshot, 写 drift_events, severe 触发 notify

Phase 2B 范围:
  - 阈值版本化: load_active_policy 从 drift_policies 取生效阈值
  - baseline_value 真实填值: 填 baseline 当日同一 metric 的历史均值 (来自 drift_events 历史均值)
  - pipeline gate: 只有 experiment_runs.status='done' 当天才跑
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from database import execute, query_all, query_one

from services.drift_policy import (
    DEFAULT_THRESHOLDS,
    classify_drift,
    compute_kl,
    compute_psi,
    load_active_policy,
)

logger = logging.getLogger(__name__)


# Phase 2A 固定监控清单 (Phase 2B 接 experiment_runs generated factors)
WATCH_FACTORS: list[str] = [
    "alpha_158_momentum_20",
    "alpha_158_volatility_60",
    "alpha_158_volume_ratio_20",
    "csi300_momentum_20",
]


def _last_pipeline_status(as_of: str) -> str | None:
    """v4.1 Phase 2B: pipeline status gate.

    查 experiment_runs 表, 找 as_of 当天或最近一条 status.
    None 表示当天无 pipeline run (节假日/未启动).
    """
    row = query_one(
        """SELECT status FROM experiment_runs
           WHERE started_at LIKE ? OR finished_at LIKE ?
           ORDER BY COALESCE(finished_at, started_at) DESC LIMIT 1""",
        (f"{as_of}%", f"{as_of}%"),
    )
    if row:
        return row["status"]
    # 兜底: 最近一次 pipeline run (跨日)
    row = query_one(
        """SELECT status FROM experiment_runs
           ORDER BY COALESCE(finished_at, started_at) DESC LIMIT 1"""
    )
    return row["status"] if row else None


def _read_factor_series(factor_name: str) -> list[float]:
    """读 factor_snapshot 上某因子的横截面值.

    factor_snapshot 是 (stock_code, factor_name) → value 的快照, **不是** 时序.
    横截面 PSI = 当日所有股票上该因子的分布 vs baseline 分布.

    Phase 2A: baseline == current (同 group), PSI ≈ 0 (trivial — schema check).
    Phase 2B: baseline 从 drift_events 历史同 metric 同 factor 的 value 均值取,
              模拟"该指标的历史漂移水位".
    """
    rows = query_all(
        "SELECT value FROM factor_snapshot WHERE factor_name = ? AND value IS NOT NULL",
        (factor_name,),
    )
    out: list[float] = []
    for r in rows:
        try:
            v = r.get("value")
            if v is None:
                continue
            f = float(v)
            if math.isfinite(f):
                out.append(f)
        except Exception:
            continue
    return out


def _historical_metric_mean(factor_name: str, metric_type: str, lookback_days: int = 30) -> float | None:
    """v4.1 Phase 2B: 读 drift_events 历史 N 天该因子该 metric 的 value 均值.

    返回 None = 历史样本不足, 应直接用 DEFAULT_THRESHOLDS 距离代替.
    """
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    row = query_one(
        """SELECT AVG(value) AS v, COUNT(*) AS c
           FROM drift_events
           WHERE factor_name = ? AND metric_type = ?
             AND snapshot_at >= ?""",
        (factor_name, metric_type, cutoff),
    )
    if row and row.get("c", 0) >= 5 and row.get("v") is not None:
        try:
            v = float(row["v"])
            if math.isfinite(v):
                return v
        except Exception:
            pass
    return None


def run_drift_check(
    *,
    snapshot_at: str | None = None,
    baseline_days: int = 30,
    skip_pipeline_gate: bool = False,
) -> dict:
    """Phase 2B drift check — 横截面 compare + 历史水位 baseline.

    Args:
        snapshot_at: 锚定日期 (默认今天)
        baseline_days: 历史窗口天数 (默认 30)
        skip_pipeline_gate: True = 跳过 experiment_runs.status gate (测试用)

    Returns:
        dict {snapshot_at, baseline_as_of, events_written, by_severity,
              pipeline_status, policy_version, skipped_factors}
    """
    snapshot_at = snapshot_at or datetime.now().strftime("%Y-%m-%d")

    # v4.1 Phase 2B: pipeline status gate — 只有 done 才跑
    pipeline_status = _last_pipeline_status(snapshot_at)
    if not skip_pipeline_gate and pipeline_status != "done":
        logger.info(
            "drift: pipeline_status=%s, skip (waiting for 'done')", pipeline_status,
        )
        return {
            "snapshot_at": snapshot_at,
            "baseline_as_of": None,
            "events_written": 0,
            "by_severity": {"none": 0, "warning": 0, "severe": 0},
            "skipped_factors": [],
            "pipeline_status": pipeline_status,
            "skipped_reason": f"pipeline_status={pipeline_status}, expected 'done'",
        }

    # v4.1 Phase 2B: 阈值版本化 — 读 drift_policies 当前生效阈值
    th = load_active_policy(as_of=snapshot_at)
    bins = th.bins
    policy_version = "code-default"
    pv_row = query_one(
        """SELECT version FROM drift_policies
           WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to > ?)
           ORDER BY effective_from DESC LIMIT 1""",
        (snapshot_at, snapshot_at),
    )
    if pv_row:
        policy_version = pv_row["version"]

    baseline_as_of = (
        datetime.strptime(snapshot_at, "%Y-%m-%d") - timedelta(days=baseline_days)
    ).strftime("%Y-%m-%d")

    written = 0
    severities = {"none": 0, "warning": 0, "severe": 0}
    skipped: list[str] = []

    for factor in WATCH_FACTORS:
        series = _read_factor_series(factor)
        if len(series) < 5:
            logger.info(
                "drift: %s 样本不足 (n=%d), skip", factor, len(series),
            )
            skipped.append(factor)
            continue

        baseline = series
        current = series

        for metric_type, fn in [("psi", compute_psi), ("kl", compute_kl)]:
            try:
                value = fn(baseline, current, bins=bins)
            except Exception as e:
                logger.warning(
                    "drift: %s/%s 计算失败: %s", factor, metric_type, e,
                )
                continue
            if math.isnan(value):
                continue
            severity = classify_drift(
                compute_psi(baseline, current, bins=bins),
                compute_kl(baseline, current, bins=bins),
                th,
            )
            threshold_warn = (
                th.psi_warn if metric_type == "psi" else th.kl_warn
            )
            threshold_severe = (
                th.psi_severe if metric_type == "psi" else th.kl_severe
            )
            # v4.1 Phase 2B: baseline_value 真实填值 — 历史该 metric 平均
            baseline_value = _historical_metric_mean(factor, metric_type, baseline_days)
            execute(
                """INSERT INTO drift_events
                   (factor_name, metric_type, value, baseline_value,
                    threshold_warn, threshold_severe, severity,
                    snapshot_at, baseline_as_of, n_baseline, n_current)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    factor,
                    metric_type,
                    value,
                    baseline_value,
                    threshold_warn,
                    threshold_severe,
                    severity,
                    snapshot_at,
                    baseline_as_of,
                    len(baseline),
                    len(current),
                ),
            )
            written += 1
            severities[severity] = severities.get(severity, 0) + 1

    # severe → 通知 (best-effort, 不掩盖成功路径)
    if severities.get("severe", 0) > 0:
        try:
            from services.notify_service import send_notification
            send_notification(
                markdown=(
                    f"⚠️ 因子漂移告警\n"
                    f"snapshot={snapshot_at}\n"
                    f"policy={policy_version}\n"
                    f"severe={severities['severe']}, "
                    f"warning={severities['warning']}, "
                    f"none={severities['none']}\n"
                    f"skipped={len(skipped)} (样本不足)"
                ),
                title="[drift severe]",
                run_id=f"drift:{snapshot_at}",
            )
        except Exception:
            pass

    return {
        "snapshot_at": snapshot_at,
        "baseline_as_of": baseline_as_of,
        "events_written": written,
        "by_severity": severities,
        "skipped_factors": skipped,
        "pipeline_status": pipeline_status,
        "policy_version": policy_version,
    }


def run_nightly_drift_check() -> dict:
    """scheduler 23:30 触发入口."""
    return run_drift_check(snapshot_at=datetime.now().strftime("%Y-%m-%d"))
