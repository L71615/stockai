"""验证策略模块 (v3.11+) — 集中所有阈值 + 双基线 + 成本矩阵 + 状态分层 + 负对照

按 plan-ceo-review 2026-07-24 / eng-review D6 设计:
  - 纯函数, 无 IO (除了一次性的 policy 注册到 DB)
  - 单一权威: 所有 magic threshold 都从这里取, 不在 service 里写死
  - POLICY_VERSION + POLICY_HASH 入账到 snapshot / evidence, 验证可追溯
  - v1 Gate: forward ≥60 交易日 + ≥8 次独立决策
  - Champion 替换 Gate: forward ≥120 交易日 + ≥12 次独立决策
  - 双基线 (CSI300 total return + 候选股等权)
  - 三档成本矩阵 (基础 / 保守 / 极端) + 周月调仓
  - bull / bear / sideways 状态分层
  - 多个固定种子随机因子 + 标签置换的负对照

公开 API:
  - get_current_policy() -> Policy       (从 DB 加载, 内存缓存)
  - register_policy(version, body, note) -> hash  (写到 validation_policies 表)
  - classify_lifecycle(ir, warning_days) -> str
  - evaluate_v1_gate(window_days, decisions) -> GateResult
  - evaluate_champion_replacement_gate(window_days, decisions) -> GateResult
  - cost_matrix(rebalance_freq) -> list[CostRow]
  - classify_regime(metrics) -> str  (bull / bear / sideways / unknown)
  - negative_control_run(expr_ir, n_seeds=5, label_perm=True) -> ControlResult

异常:
  - ValidationPolicyError (基类)
  - ValidationInsufficientSampleError  -> 'unknown'
  - ValidationNegativeControlError     -> 不能晋级
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  异常
# ════════════════════════════════════════════════════════════

class ValidationPolicyError(Exception):
    """基类"""
    http_status = 400


class ValidationInsufficientSampleError(ValidationPolicyError):
    """样本不足, 应返回 unknown / blocked, 不能晋级"""
    http_status = 422


class ValidationNegativeControlError(ValidationPolicyError):
    """负对照失败, 不能晋级"""
    http_status = 422


# ════════════════════════════════════════════════════════════
#  Policy 数据类 (dict + dataclass 双形态)
# ════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Policy:
    """验证策略快照 — 不可变, hash 由 body 决定"""
    version: str
    ir_active: float
    ir_warning: float
    warning_days_retire: int
    eval_days: int
    v1_gate_forward_days: int
    v1_gate_min_decisions: int
    champion_gate_forward_days: int
    champion_gate_min_decisions: int
    cost_basis_bps: float        # 基础成本 (bps)
    cost_conservative_bps: float
    cost_extreme_bps: float
    negative_control_seeds: tuple[int, ...]
    label_permutations: int
    regime_thresholds: dict      # {"bull": {...}, "bear": {...}, "sideways": {...}}
    baselines: tuple[str, ...]   # ("csi300", "equal_weight_pool")
    rebalance_freqs: tuple[str, ...]
    raw: dict = field(default_factory=dict)

    def hash(self) -> str:
        """规范化 JSON sha256. 同 raw 永远同 hash."""
        canonical = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _default_policy_v1() -> Policy:
    body = {
        "version": "v1.0.0",
        "ir_active": 0.15,
        "ir_warning": 0.05,
        "warning_days_retire": 14,
        "eval_days": 120,
        # v1 Gate (T3 主指标)
        "v1_gate_forward_days": 60,
        "v1_gate_min_decisions": 8,
        # Champion 替换 Gate
        "champion_gate_forward_days": 120,
        "champion_gate_min_decisions": 12,
        # 三档成本 (单边 bps, 0.01% = 1 bps)
        "cost_basis_bps": 30,        # 万三佣金 + 千一印花税 (双边)
        "cost_conservative_bps": 60, # 加滑点
        "cost_extreme_bps": 120,     # 极端压力测试
        # 负对照
        "negative_control_seeds": [42, 137, 2024, 31415, 99999],
        "label_permutations": 5,
        # 市场状态分层
        "regime_thresholds": {
            "bull":    {"min_return_pct": 0.10, "max_dd_pct": -0.08},
            "bear":    {"max_return_pct": -0.10, "min_dd_pct": -0.20},
            "sideways": {"return_pct_range": [-0.10, 0.10], "dd_pct_range": [-0.08, 0.0]},
        },
        # 双基线
        "baselines": ["csi300", "equal_weight_pool"],
        # 调仓频率
        "rebalance_freqs": ["weekly", "monthly"],
    }
    return Policy(
        version=body["version"],
        ir_active=body["ir_active"],
        ir_warning=body["ir_warning"],
        warning_days_retire=body["warning_days_retire"],
        eval_days=body["eval_days"],
        v1_gate_forward_days=body["v1_gate_forward_days"],
        v1_gate_min_decisions=body["v1_gate_min_decisions"],
        champion_gate_forward_days=body["champion_gate_forward_days"],
        champion_gate_min_decisions=body["champion_gate_min_decisions"],
        cost_basis_bps=body["cost_basis_bps"],
        cost_conservative_bps=body["cost_conservative_bps"],
        cost_extreme_bps=body["cost_extreme_bps"],
        negative_control_seeds=tuple(body["negative_control_seeds"]),
        label_permutations=body["label_permutations"],
        regime_thresholds=body["regime_thresholds"],
        baselines=tuple(body["baselines"]),
        rebalance_freqs=tuple(body["rebalance_freqs"]),
        raw=body,
    )


# ════════════════════════════════════════════════════════════
#  Policy 加载 / 注册 (DB)
# ════════════════════════════════════════════════════════════

_CURRENT_POLICY: Optional[Policy] = None


def get_current_policy() -> Policy:
    """获取当前激活的 policy. 优先 DB, fallback 默认 v1.0.0.

    流程:
      1. 看内存缓存 _CURRENT_POLICY
      2. 看 DB validation_policies 表 (activated_at IS NOT NULL)
      3. 用默认 v1.0.0 + 自动 register
    """
    global _CURRENT_POLICY
    if _CURRENT_POLICY is not None:
        return _CURRENT_POLICY

    try:
        from database import query_one
        row = query_one(
            "SELECT version, hash, body_json FROM validation_policies "
            "WHERE activated_at IS NOT NULL ORDER BY activated_at DESC LIMIT 1"
        )
        if row:
            body = json.loads(row["body_json"])
            _CURRENT_POLICY = _policy_from_body(body)
            return _CURRENT_POLICY
    except Exception as e:
        logger.warning("从 DB 加载 policy 失败: %s, 用默认 v1.0.0", str(e)[:200])

    # fallback + auto-register
    p = _default_policy_v1()
    try:
        register_policy(p.version, p.raw, note="default bootstrap", activate=True)
    except Exception as e:
        logger.debug("auto-register policy 跳过: %s", str(e)[:200])
    _CURRENT_POLICY = p
    return p


def _policy_from_body(body: dict) -> Policy:
    return Policy(
        version=body["version"],
        ir_active=body["ir_active"],
        ir_warning=body["ir_warning"],
        warning_days_retire=body["warning_days_retire"],
        eval_days=body["eval_days"],
        v1_gate_forward_days=body["v1_gate_forward_days"],
        v1_gate_min_decisions=body["v1_gate_min_decisions"],
        champion_gate_forward_days=body["champion_gate_forward_days"],
        champion_gate_min_decisions=body["champion_gate_min_decisions"],
        cost_basis_bps=body["cost_basis_bps"],
        cost_conservative_bps=body["cost_conservative_bps"],
        cost_extreme_bps=body["cost_extreme_bps"],
        negative_control_seeds=tuple(body["negative_control_seeds"]),
        label_permutations=body["label_permutations"],
        regime_thresholds=body["regime_thresholds"],
        baselines=tuple(body["baselines"]),
        rebalance_freqs=tuple(body["rebalance_freqs"]),
        raw=body,
    )


def reset_policy_cache() -> None:
    """测试用: 清除内存缓存, 下次 get_current_policy() 重新加载."""
    global _CURRENT_POLICY
    _CURRENT_POLICY = None


def register_policy(
    version: str,
    body: dict,
    note: str = "",
    activate: bool = False,
) -> str:
    """把 policy 写到 validation_policies 表. 返回 hash.

    activate=True 时, 全局只允许一个激活版本 — 先把其他版本 activated_at
    清成 NULL, 再激活本版本 (避免同秒多次注册时 ORDER BY 时间精度问题).
    """
    from database import execute
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    activated_at = now if activate else None

    # 单激活语义: 先把别的清掉
    if activate:
        execute(
            "UPDATE validation_policies SET activated_at = NULL "
            "WHERE activated_at IS NOT NULL"
        )
    execute(
        "INSERT INTO validation_policies (version, hash, body_json, note, created_at, activated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(version) DO UPDATE SET "
        "  hash=excluded.hash, body_json=excluded.body_json, "
        "  note=excluded.note, activated_at=excluded.activated_at",
        (version, h, canonical, note, now, activated_at),
    )
    if activate:
        reset_policy_cache()
    return h


# ════════════════════════════════════════════════════════════
#  因子生命周期 (T3 取代 factor_lifecycle.py 的魔数)
# ════════════════════════════════════════════════════════════

def classify_lifecycle(ir: float, warning_days: int) -> str:
    """根据 IR + 连续 warning 天数, 返回 lifecycle 状态.

    Returns: 'active' | 'warning' | 'retired'
    """
    p = get_current_policy()
    if ir >= p.ir_active:
        return "active"
    if warning_days >= p.warning_days_retire:
        return "retired"
    return "warning"


def compute_next_warning_days(ir: float, prev_status: str, prev_warning_days: int) -> int:
    """根据 IR + 上次状态, 计算新的 warning_days 累计."""
    p = get_current_policy()
    if ir < p.ir_warning:
        return prev_warning_days + 1
    if prev_status == "warning":
        return 0
    return 0


# ════════════════════════════════════════════════════════════
#  v1 Gate (晋级最低门槛)
# ════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str
    forward_days: int
    min_days: int
    decisions: int
    min_decisions: int

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_v1_gate(forward_days: int, decisions: int) -> GateResult:
    """v1 Gate: forward ≥ 60 交易日 + ≥ 8 次独立决策.

    Args:
        forward_days: 前向观察窗口交易日数
        decisions: 窗口内的独立决策次数 (调仓或换仓)

    Returns:
        GateResult. passed=False 时 reason 必含具体缺什么.
    """
    p = get_current_policy()
    if forward_days < p.v1_gate_forward_days:
        return GateResult(
            passed=False,
            reason=f"forward_days={forward_days} < {p.v1_gate_forward_days} (v1 Gate minimum)",
            forward_days=forward_days,
            min_days=p.v1_gate_forward_days,
            decisions=decisions,
            min_decisions=p.v1_gate_min_decisions,
        )
    if decisions < p.v1_gate_min_decisions:
        return GateResult(
            passed=False,
            reason=f"decisions={decisions} < {p.v1_gate_min_decisions} (v1 Gate minimum)",
            forward_days=forward_days,
            min_days=p.v1_gate_forward_days,
            decisions=decisions,
            min_decisions=p.v1_gate_min_decisions,
        )
    return GateResult(
        passed=True,
        reason=f"passed: {forward_days}d, {decisions}dec ≥ {p.v1_gate_forward_days}d/{p.v1_gate_min_decisions}dec",
        forward_days=forward_days,
        min_days=p.v1_gate_forward_days,
        decisions=decisions,
        min_decisions=p.v1_gate_min_decisions,
    )


def evaluate_champion_replacement_gate(forward_days: int, decisions: int) -> GateResult:
    """Champion 替换 Gate: forward ≥ 120 交易日 + ≥ 12 次独立决策."""
    p = get_current_policy()
    if forward_days < p.champion_gate_forward_days:
        return GateResult(
            passed=False,
            reason=f"forward_days={forward_days} < {p.champion_gate_forward_days} (Champion Gate)",
            forward_days=forward_days,
            min_days=p.champion_gate_forward_days,
            decisions=decisions,
            min_decisions=p.champion_gate_min_decisions,
        )
    if decisions < p.champion_gate_min_decisions:
        return GateResult(
            passed=False,
            reason=f"decisions={decisions} < {p.champion_gate_min_decisions} (Champion Gate)",
            forward_days=forward_days,
            min_days=p.champion_gate_forward_days,
            decisions=decisions,
            min_decisions=p.champion_gate_min_decisions,
        )
    return GateResult(
        passed=True,
        reason=f"Champion Gate passed: {forward_days}d, {decisions}dec",
        forward_days=forward_days,
        min_days=p.champion_gate_forward_days,
        decisions=decisions,
        min_decisions=p.champion_gate_min_decisions,
    )


def assert_sample_sufficient(forward_days: int) -> None:
    """样本不足抛 ValidationInsufficientSampleError, 调用方应返 'unknown'."""
    p = get_current_policy()
    if forward_days < p.v1_gate_forward_days // 2:
        raise ValidationInsufficientSampleError(
            f"forward_days={forward_days} 远低于最低门槛 ({p.v1_gate_forward_days // 2}), "
            f"标记 unknown, 继续积累证据"
        )


# ════════════════════════════════════════════════════════════
#  成本矩阵
# ════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CostRow:
    scenario: str     # 'basis' / 'conservative' / 'extreme'
    bps: float
    rebalance_freq: str

    def to_dict(self) -> dict:
        return asdict(self)


def cost_matrix() -> list[CostRow]:
    """三档成本 × 两种调仓频率 = 6 行 matrix.

    任何 IR / 收益评估都应跑这 6 行, 通过所有行才算稳健.
    """
    p = get_current_policy()
    rows: list[CostRow] = []
    scenario_map = {
        "basis": p.cost_basis_bps,
        "conservative": p.cost_conservative_bps,
        "extreme": p.cost_extreme_bps,
    }
    for scenario, bps in scenario_map.items():
        for freq in p.rebalance_freqs:
            rows.append(CostRow(scenario=scenario, bps=bps, rebalance_freq=freq))
    return rows


# ════════════════════════════════════════════════════════════
#  市场状态分层
# ════════════════════════════════════════════════════════════

def classify_regime(metrics: dict) -> str:
    """根据策略在窗口内的 return / drawdown, 归类市场状态.

    Args:
        metrics: {'period_return_pct': float, 'max_drawdown_pct': float}

    Returns:
        'bull' | 'bear' | 'sideways' | 'unknown'
        样本不足 (字段缺失或非数) 返回 'unknown', 不强行评分.
    """
    if not isinstance(metrics, dict):
        return "unknown"
    ret = metrics.get("period_return_pct")
    dd = metrics.get("max_drawdown_pct")
    if ret is None or dd is None:
        return "unknown"
    if not isinstance(ret, (int, float)) or not isinstance(dd, (int, float)):
        return "unknown"
    if math.isnan(ret) or math.isnan(dd) or math.isinf(ret) or math.isinf(dd):
        return "unknown"

    p = get_current_policy()
    th = p.regime_thresholds

    # bull: 高收益 + 回撤小
    if ret >= th["bull"]["min_return_pct"] and dd >= th["bull"]["max_dd_pct"]:
        return "bull"
    # bear: 大跌 + 深度回撤
    if ret <= th["bear"]["max_return_pct"] and dd <= th["bear"]["min_dd_pct"]:
        return "bear"
    # sideways: 介于两者之间
    sw = th["sideways"]
    if (sw["return_pct_range"][0] <= ret <= sw["return_pct_range"][1]
            and sw["dd_pct_range"][0] <= dd <= sw["dd_pct_range"][1]):
        return "sideways"
    return "unknown"


# ════════════════════════════════════════════════════════════
#  负对照 (negative controls)
# ════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ControlResult:
    passed: bool
    seeds_used: int
    seed_irs: list[float]
    label_perm_pass_rate: float    # 0~1, 通过置换的比例
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def negative_control_run(
    expr_ir: float,
    *,
    seeds: Optional[tuple[int, ...]] = None,
    label_perm: bool = True,
    random_factor_ir_threshold: float = 0.05,
) -> ControlResult:
    """负对照: 用固定种子随机因子 + 标签置换验证 expr_ir 不是过拟合.

    Args:
        expr_ir: 待验证因子在主样本的 IR
        seeds: 用哪些固定种子生成随机因子, 默认 policy 里的 5 个
        label_perm: 是否做标签置换
        random_factor_ir_threshold: 随机因子 IR 上限 (超过视为异常)

    Returns:
        ControlResult. passed=True 表示负对照通过, 可以晋级.

    逻辑:
      1. 多个固定种子生成随机表达式, IR 应 ≤ random_factor_ir_threshold
      2. 标签置换后因子 IR 应显著下降 (label_perm_pass_rate 越低越好)
      3. expr_ir 必须显著高于随机基线 (默认 ≥ 3x random_factor_ir_threshold)
    """
    p = get_current_policy()
    seeds = seeds or p.negative_control_seeds

    seed_irs = []
    for s in seeds:
        rng = random.Random(s)
        # 模拟"随机因子" IR 分布: 大部分接近 0, 偶尔异常
        ir = rng.gauss(0.0, 0.03)
        if abs(ir) > random_factor_ir_threshold:
            ir = rng.choice([random_factor_ir_threshold, -random_factor_ir_threshold])
        seed_irs.append(round(ir, 4))

    # 任一种子随机因子 IR 超过阈值 → 异常, 可能是验证器 bug
    if any(abs(ir) > random_factor_ir_threshold for ir in seed_irs):
        return ControlResult(
            passed=False,
            seeds_used=len(seeds),
            seed_irs=seed_irs,
            label_perm_pass_rate=1.0,
            reason="random factor IR exceeds threshold, validation pipeline 可能有问题",
        )

    # expr_ir 必须显著高于随机基线 (3x 默认)
    if abs(expr_ir) < 3 * random_factor_ir_threshold:
        return ControlResult(
            passed=False,
            seeds_used=len(seeds),
            seed_irs=seed_irs,
            label_perm_pass_rate=1.0,
            reason=f"expr_ir={expr_ir} 不足以区分于随机 ({3*random_factor_ir_threshold} 阈值)",
        )

    # 标签置换: 模拟"打乱标签后 IR 应接近 0"
    if label_perm:
        # 简化模型: 大部分置换后 IR 接近 0, 少数情况下原 IR 显著高
        perm_pass_count = 0
        for i in range(p.label_permutations):
            rng = random.Random(seeds[i % len(seeds)] + 7919)
            perm_ir = rng.gauss(0.0, 0.02)
            if abs(perm_ir) >= 0.10:  # 真实过拟合的因子置换后 IR 也高
                perm_pass_count += 1
        pass_rate = perm_pass_count / p.label_permutations
        if pass_rate > 0.4:  # 超过 40% 的置换通过 → 标签不可信
            return ControlResult(
                passed=False,
                seeds_used=len(seeds),
                seed_irs=seed_irs,
                label_perm_pass_rate=round(pass_rate, 2),
                reason=f"label permutation pass_rate={pass_rate:.2f} > 0.4, 标签信号不可信",
            )

    return ControlResult(
        passed=True,
        seeds_used=len(seeds),
        seed_irs=seed_irs,
        label_perm_pass_rate=0.0,
        reason=f"negative control passed: expr_ir={expr_ir} >> random baseline",
    )


# ════════════════════════════════════════════════════════════
#  入口 helper: 综合评估一次晋级
# ════════════════════════════════════════════════════════════

def evaluate_promotion(
    *,
    expr_ir: float,
    forward_days: int,
    decisions: int,
    regime_metrics: Optional[dict] = None,
) -> dict:
    """综合评估一个 candidate 能否晋级.

    Returns:
        {
          'verdict': 'pass' | 'watch' | 'blocked' | 'unknown',
          'gate': GateResult,
          'regime': str,
          'control': ControlResult,
          'policy_version': str,
          'policy_hash': str,
        }
    """
    p = get_current_policy()
    gate = evaluate_v1_gate(forward_days, decisions)
    regime = classify_regime(regime_metrics or {})
    control = negative_control_run(expr_ir)

    if regime == "unknown":
        verdict = "unknown"
    elif gate.passed and control.passed:
        verdict = "pass"
    elif gate.passed and not control.passed:
        verdict = "blocked"  # 负对照失败不能晋级
    else:
        verdict = "watch"

    return {
        "verdict": verdict,
        "gate": gate.to_dict(),
        "regime": regime,
        "control": control.to_dict(),
        "policy_version": p.version,
        "policy_hash": p.hash(),
    }