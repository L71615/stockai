"""v4.1 Phase 2A: 漂移 orchestrator — 读 factor_snapshot, 写 drift_events, severe 触发 notify

Phase 2A 范围:
  - 横截面 PSI (同一日同一因子在 N 只股票上的分布, baseline = current)
    这是"平凡"实现, 验证 schema + write path. PSI 应近 0.
  - 真正的时序 PSI 等 Phase 2B:
    1) 接 experiment_runs.status='done' event binding
    2) 换 baseline 为 N 天前 IC 序列 (factor_candidates.ic_mean 历史 / 新表 factor_ic_history)
    3) 加 drift_policies 表版本化阈值
    → TODOS.md 已记录: 'P2/M — Factor / model drift monitoring (PSI / KL)'
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from database import execute, query_all

from services.drift_policy import (
    DEFAULT_THRESHOLDS,
    classify_drift,
    compute_kl,
    compute_psi,
)

logger = logging.getLogger(__name__)


# Phase 2A 固定监控清单 (Phase 2B 接 experiment_runs generated factors)
WATCH_FACTORS: list[str] = [
    "alpha_158_momentum_20",
    "alpha_158_volatility_60",
    "alpha_158_volume_ratio_20",
    "csi300_momentum_20",
]


def _read_factor_series(factor_name: str) -> list[float]:
    """读 factor_snapshot 上某因子的横截面值.

    factor_snapshot 是 (stock_code, factor_name) → value 的快照, **不是** 时序.
    横截面 PSI = 当日所有股票上该因子的分布 vs baseline 分布.

    Phase 2A: baseline == current (同 group), PSI ≈ 0 (trivial — schema check).
    Phase 2B: baseline 从 N 天前 snapshot 取, current 取今日 → 真时序 PSI.
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


def run_drift_check(
    *,
    snapshot_at: str | None = None,
    baseline_days: int = 30,
) -> dict:
    """Phase 2A 横截面 compare.

    Args:
        snapshot_at: 锚定日期 (默认今天)
        baseline_days: 占位参数 (Phase 2B 用于 baseline 窗口).

    Returns:
        dict {snapshot_at, baseline_as_of, events_written, by_severity}
    """
    snapshot_at = snapshot_at or datetime.now().strftime("%Y-%m-%d")
    baseline_as_of = (
        datetime.now() - timedelta(days=baseline_days * 2)
    ).strftime("%Y-%m-%d")

    written = 0
    severities = {"none": 0, "warning": 0, "severe": 0}
    th = DEFAULT_THRESHOLDS
    bins = th.bins
    skipped: list[str] = []

    for factor in WATCH_FACTORS:
        # Phase 2A: 同一组值当 baseline+current, PSI 应为 ~0 (sanity)
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
                    None,  # baseline_value: Phase 2B 填
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
    }


def run_nightly_drift_check() -> dict:
    """scheduler 23:30 触发入口."""
    return run_drift_check(snapshot_at=datetime.now().strftime("%Y-%m-%d"))
