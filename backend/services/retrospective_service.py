"""复盘服务 (v3.11+, T9) — 接受/拒绝 vs 实际前向表现

按 plan-ceo-review 2026-07-24 §Phase 6 设计:
  - 每个被决策的 proposal → 30 天后写入 outcome (前向表现)
  - 生成 retrospective (假设 vs 实际 + lesson)
  - 接受 vs 拒绝的 counterfactual 对比

公开 API:
  - record_outcome(proposal_id, decision, fwd_days, fwd_return,
                   fwd_shadow_return, fwd_baseline_diff, baseline_code) -> outcome_id
  - generate_retrospective(proposal_id, hypothesis, evidence_summary,
                            realized_summary, lesson, confidence) -> retro_id
  - list_outcomes(decision=...) -> list[dict]
  - list_retrospectives(experiment_id=...) -> list[dict]
  - counterfactual_summary(window_days=30) -> dict
       {
         'accepted': {count, avg_fwd_return, avg_baseline_diff},
         'rejected': {count, avg_fwd_return, avg_baseline_diff},
         'edge': avg_accepted - avg_rejected  (counterfactual edge)
       }

异常:
  - RetrospectiveError (基类)
  - OutcomeAlreadyRecordedError
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from database import execute, query_all, query_one

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  异常
# ════════════════════════════════════════════════════════════

class RetrospectiveError(Exception):
    http_status = 400


class OutcomeAlreadyRecordedError(RetrospectiveError):
    http_status = 409


# ════════════════════════════════════════════════════════════
#  时间
# ════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ════════════════════════════════════════════════════════════
#  Outcome 记录
# ════════════════════════════════════════════════════════════

VALID_LABELS = {"good", "bad", "neutral"}


def _classify_label(decision: str, fwd_baseline_diff: float) -> str:
    """根据决策 + baseline_diff 自动标 'good'/'bad'/'neutral'."""
    if decision == "rejected":
        # 拒绝后看: 如果实际涨了 → 'good' (拒绝是错的)
        if fwd_baseline_diff > 0.02:
            return "good"
        if fwd_baseline_diff < -0.02:
            return "bad"
        return "neutral"
    elif decision == "approved":
        # 接受后看: 如果实际跌了 → 'bad' (接受是错的)
        if fwd_baseline_diff < -0.02:
            return "bad"
        if fwd_baseline_diff > 0.02:
            return "good"
        return "neutral"
    return "neutral"


def record_outcome(
    *,
    proposal_id: int,
    decision: str,                   # 'approved' | 'rejected' | 'withdrawn'
    fwd_days: int,
    fwd_return: float,
    fwd_shadow_return: float = 0.0,
    fwd_baseline_diff: float = 0.0,
    baseline_code: str = "csi300",
    label: Optional[str] = None,
) -> int:
    """记录 proposal 的前向表现.

    一个 proposal 只能记一次 outcome (UNIQUE). 第二次抛 OutcomeAlreadyRecordedError.

    Args:
        proposal_id: 关联的 proposal
        decision: 当时的决策 (approved/rejected/withdrawn)
        fwd_days: 前向观察天数 (e.g., 30)
        fwd_return: proposal 对应的实验/策略的前向累计收益 (e.g., 0.05 = +5%)
        fwd_shadow_return: 影子组合的实际收益 (T4)
        fwd_baseline_diff: 相对 baseline (CSI300) 的超额收益
        baseline_code: 'csi300' | 'equal_weight_pool'
        label: 自动分类 (good/bad/neutral), 不传则按 fwd_baseline_diff 自动

    Returns:
        outcome_id
    """
    if decision not in ("approved", "rejected", "withdrawn"):
        raise RetrospectiveError(f"invalid decision: {decision}")

    if label is None:
        label = _classify_label(decision, fwd_baseline_diff)
    elif label not in VALID_LABELS:
        raise RetrospectiveError(f"invalid label: {label}")

    realized_at = _now()
    try:
        cur = execute(
            "INSERT INTO proposal_outcomes "
            "(proposal_id, decision, realized_at, fwd_days, fwd_return, "
            " fwd_shadow_return, fwd_baseline_diff, baseline_code, label, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (proposal_id, decision, realized_at, fwd_days, fwd_return,
             fwd_shadow_return, fwd_baseline_diff, baseline_code, label, realized_at),
        )
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg:
            raise OutcomeAlreadyRecordedError(
                f"outcome already recorded for proposal {proposal_id}"
            ) from e
        raise

    return int(cur["lastrowid"])


# ════════════════════════════════════════════════════════════
#  Retrospective 生成
# ════════════════════════════════════════════════════════════

def generate_retrospective(
    *,
    proposal_id: int,
    hypothesis: str = "",
    evidence_summary: str = "",
    realized_summary: str = "",
    lesson: str = "",
    confidence: float = 0.0,
) -> int:
    """生成复盘条目. 调用方需要提供 decision / fwd_*, 自动从 outcome 读."""
    outcome = query_one(
        "SELECT * FROM proposal_outcomes WHERE proposal_id = ?",
        (proposal_id,),
    )
    if not outcome:
        raise RetrospectiveError(
            f"no outcome for proposal {proposal_id}, 请先 record_outcome"
        )

    proposal = query_one(
        "SELECT experiment_id FROM approval_proposals WHERE proposal_id = ?",
        (proposal_id,),
    )
    if not proposal:
        raise RetrospectiveError(f"proposal {proposal_id} not found")

    cur = execute(
        "INSERT INTO proposal_retrospectives "
        "(proposal_id, experiment_id, decision, fwd_days, fwd_return, "
        " fwd_baseline_diff, hypothesis, evidence_summary, realized_summary, "
        " lesson, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            proposal_id, proposal["experiment_id"], outcome["decision"],
            outcome["fwd_days"], outcome["fwd_return"], outcome["fwd_baseline_diff"],
            hypothesis, evidence_summary, realized_summary, lesson,
            confidence, _now(),
        ),
    )
    return int(cur["lastrowid"])


# ════════════════════════════════════════════════════════════
#  查询 / Counterfactual
# ════════════════════════════════════════════════════════════

def list_outcomes(
    *,
    decision: Optional[str] = None,
    label: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    where = []
    params: list = []
    if decision:
        where.append("decision = ?")
        params.append(decision)
    if label:
        where.append("label = ?")
        params.append(label)
    if since:
        where.append("realized_at >= ?")
        params.append(since)
    sql = "SELECT * FROM proposal_outcomes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY realized_at DESC LIMIT ?"
    params.append(limit)
    return query_all(sql, tuple(params))


def list_retrospectives(
    *,
    experiment_id: Optional[str] = None,
    decision: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    where = []
    params: list = []
    if experiment_id:
        where.append("experiment_id = ?")
        params.append(experiment_id)
    if decision:
        where.append("decision = ?")
        params.append(decision)
    sql = "SELECT * FROM proposal_retrospectives"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return query_all(sql, tuple(params))


def counterfactual_summary(
    *,
    since: Optional[str] = None,
    baseline_code: str = "csi300",
) -> dict:
    """Counterfactual: 接受 vs 拒绝 proposal 的实际表现对比.

    Args:
        since: ISO 时间, 默认 30 天前
        baseline_code: 基准 (默认 csi300)

    Returns:
        {
          'window': {since, until},
          'baseline_code': str,
          'accepted': {count, avg_fwd_return, avg_baseline_diff, good_rate},
          'rejected': {count, avg_fwd_return, avg_baseline_diff, good_rate},
          'edge': float,                    # accepted.avg_baseline_diff - rejected.avg_baseline_diff
          'interpretation': str,            # 人话解读
        }

    edge > 0: 用户接受决策的方向对了 (接受的好于拒绝的, 即"接受"加了 alpha)
    edge < 0: 用户接受决策方向错了 (接受的反不如拒绝)
    """
    if since is None:
        since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    accepted = query_all(
        "SELECT fwd_return, fwd_baseline_diff, label FROM proposal_outcomes "
        "WHERE decision = 'approved' AND baseline_code = ? AND realized_at >= ?",
        (baseline_code, since),
    )
    rejected = query_all(
        "SELECT fwd_return, fwd_baseline_diff, label FROM proposal_outcomes "
        "WHERE decision = 'rejected' AND baseline_code = ? AND realized_at >= ?",
        (baseline_code, since),
    )

    def _agg(rows):
        if not rows:
            return {"count": 0, "avg_fwd_return": 0.0, "avg_baseline_diff": 0.0, "good_rate": 0.0}
        return {
            "count": len(rows),
            "avg_fwd_return": round(sum(r["fwd_return"] for r in rows) / len(rows), 4),
            "avg_baseline_diff": round(sum(r["fwd_baseline_diff"] for r in rows) / len(rows), 4),
            "good_rate": round(sum(1 for r in rows if r["label"] == "good") / len(rows), 2),
        }

    a, r = _agg(accepted), _agg(rejected)
    edge = round(a["avg_baseline_diff"] - r["avg_baseline_diff"], 4)
    if edge > 0.005:
        interp = "✓ 接受方向对了, 用户决策加了 alpha"
    elif edge < -0.005:
        interp = "✗ 接受方向错了, 用户决策反拖累"
    else:
        interp = "≈ 无显著差异"

    return {
        "window": {"since": since, "until": _now()[:10]},
        "baseline_code": baseline_code,
        "accepted": a,
        "rejected": r,
        "edge": edge,
        "interpretation": interp,
    }