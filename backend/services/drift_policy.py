"""v4.1 Phase 2A: 因子分布漂移检测 — 纯函数模块

零 IO. 任何统计计算都无副作用, 便于单元测试 + 复用.

指标:
  - PSI (Population Stability Index)
    PSI = sum_i (p_i - q_i) * ln(p_i / q_i)
    标准阈值: PSI < 0.1  无漂移; 0.1-0.25 警告; >= 0.25 严重漂移.

  - KL  (Kullback-Leibler divergence)
    KL(P || Q) = sum_i p_i * ln(p_i / q_i)
    非对称, baseline 当 reference distribution.

约定:
  - bins=10 (业界默认)
  - 边界: 用 baseline 的 1/bins 2/bins ... 9/9 分位数切分
  - 样本不足 (<5) 返回 nan
  - 极小比例 (0 bin) 加 eps=1e-6 防止 log(0)
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DriftThresholds:
    """默认阈值 — 三档分类."""
    psi_warn: float = 0.10
    psi_severe: float = 0.25
    kl_warn: float = 0.10
    kl_severe: float = 0.50
    bins: int = 10


DEFAULT_THRESHOLDS = DriftThresholds()


def _quantile_edges(values: list[float], bins: int) -> list[float]:
    """用 baseline 的分位数切分 [edge_1..edge_{bins-1}]."""
    if len(values) < bins:
        # 样本 < bins, 用排序后等距位置
        s = sorted(values)
    else:
        s = sorted(values)
    n = len(s)
    edges: list[float] = []
    for i in range(1, bins):
        # q = i / bins 位置
        idx = max(0, min(n - 1, int(n * i / bins)))
        edges.append(float(s[idx]))
    return edges


def _histogram_proportions(
    values: list[float], edges: list[float], eps: float
) -> list[float]:
    """落入 bins/bin-edge 的比例, 加 eps 防除零.

    bins = len(edges) + 1.
    """
    bins = len(edges) + 1
    counts = [0] * bins
    for v in values:
        placed = False
        for i, e in enumerate(edges):
            if v <= e:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    total = sum(counts) + eps * bins
    return [(c + eps) / total for c in counts]


def compute_psi(
    baseline: list[float],
    current: list[float],
    bins: int = 10,
    eps: float = 1e-6,
) -> float:
    """Population Stability Index.

    baseline, current: 1D 数值列表
        (e.g. 因子 IC 序列 / 同一因子在 N 只股票上的横截面值).

    Returns:
        float (>= 0). 样本不足返回 nan.
    """
    if len(baseline) < 5 or len(current) < 5:
        return float("nan")
    try:
        edges = _quantile_edges(baseline, bins)
        p = _histogram_proportions(baseline, edges, eps)
        q = _histogram_proportions(current, edges, eps)
        psi = sum((p[i] - q[i]) * math.log(p[i] / q[i]) for i in range(bins))
        return float(psi)
    except Exception:
        return float("nan")


def compute_kl(
    baseline: list[float],
    current: list[float],
    bins: int = 10,
    eps: float = 1e-6,
) -> float:
    """Kullback-Leibler divergence KL(P || Q) — baseline 当 reference.

    Returns:
        float (>= 0). 样本不足返回 nan.
    """
    if len(baseline) < 5 or len(current) < 5:
        return float("nan")
    try:
        edges = _quantile_edges(baseline, bins)
        p = _histogram_proportions(baseline, edges, eps)
        q = _histogram_proportions(current, edges, eps)
        kl = sum(p[i] * math.log(p[i] / q[i]) for i in range(bins))
        return float(kl)
    except Exception:
        return float("nan")


def classify_drift(
    psi: float,
    kl: float,
    thresholds: DriftThresholds = DEFAULT_THRESHOLDS,
) -> str:
    """三档分类.

    | severity   | criterion                                     |
    |------------|-----------------------------------------------|
    | 'severe'   | psi >= psi_severe OR kl >= kl_severe           |
    | 'warning'  | psi >= psi_warn   OR kl >= kl_warn             |
    | 'none'     | 其它 (含 psi=nan)                             |
    """
    if math.isnan(psi) or math.isnan(kl):
        return "none"
    if psi >= thresholds.psi_severe or kl >= thresholds.kl_severe:
        return "severe"
    if psi >= thresholds.psi_warn or kl >= thresholds.kl_warn:
        return "warning"
    return "none"
