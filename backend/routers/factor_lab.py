"""因子实验室路由 — IC 分析 / 相关性矩阵 / 散点图 / GP 挖掘 / 生命周期"""
import logging
from fastapi import APIRouter, HTTPException, Query

from services.factor_lab import (
    compute_factor_metrics,
    compute_factor_leaderboard,
    compute_factor_clustering,
    compute_factor_contribution,
    compute_quantile_returns,
    compute_correlation_matrix,
    compute_scatter_data,
    list_available_factors,
    get_supported_pools,
)
from services.factor_expr import gp_mine
from services.factor_ml import train_ml_factor
from services.factor_ml import train_ml_with_gp_factors
from services.factor_lifecycle import (
    update_all_factors,
    get_all_statuses,
    reset_factor,
)
from services.experiment_service import (
    create_experiment,
    get_experiment,
    transition,
    ExperimentNotFoundError,
    ExperimentConflictError,
    ExperimentTransitionError,
)
from dependencies import get_current_user_id
from database import query_all, query_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factor-lab", tags=["FactorLab"])


@router.get("/factors")
def get_factors():
    """列出可用因子"""
    return {"factors": list_available_factors()}


@router.get("/pools")
def get_pools():
    """列出支持的股票池"""
    return {"pools": get_supported_pools()}


@router.post("/ic")
def get_ic_analysis(
    factors: list[str] = Query(..., description="因子名列表"),
    pool: str = Query("all", description="股票池: all / hs300 / csi500 / csi800"),
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
):
    """计算因子 IC 指标"""
    try:
        return compute_factor_metrics(factors, pool, start_date, end_date)
    except Exception as e:
        logger.error("ic analysis failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"IC 计算失败: {str(e)[:200]}")


@router.get("/leaderboard")
def get_leaderboard(
    pool: str = Query("all", description="股票池"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    """全因子排行榜 — 一张表聚合 IC / IR / Turnover / Decay Score"""
    try:
        return compute_factor_leaderboard(
            factors=None,  # 全因子
            stock_pool=pool,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.error("leaderboard failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"排行榜计算失败: {str(e)[:200]}")


@router.post("/contribution")
def get_contribution(
    stock_code: str = Query(..., description="股票代码 (e.g. 600519)"),
    factors: list[str] = Query(..., description="因子名列表"),
    pool: str = Query("hs300"),
    as_of_date: str | None = Query(None, description="截面日 YYYY-MM-DD"),
    lookback_days: int = Query(120, ge=30, le=365, description="IC mean 回看天数"),
):
    """因子瀑布图 — 单只股票的 alpha 因子归因(为什么 AI 选了这只)"""
    try:
        return compute_factor_contribution(
            stock_code=stock_code,
            factors=factors,
            stock_pool=pool,
            as_of_date=as_of_date,
            lookback_days=lookback_days,
        )
    except Exception as e:
        logger.error("contribution failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"瀑布图计算失败: {str(e)[:200]}")


@router.post("/quantile-returns")
def get_quantile_returns(
    factor: str = Query(..., description="因子名"),
    pool: str = Query("all"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    n_groups: int = Query(5, ge=2, le=10, description="分组数"),
):
    """分位数收益 — 教科书 quant 图:5 等分累计收益 + 多空对冲曲线"""
    try:
        return compute_quantile_returns(
            factor_name=factor,
            stock_pool=pool,
            start_date=start_date,
            end_date=end_date,
            n_groups=n_groups,
        )
    except Exception as e:
        logger.error("quantile returns failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"分位数收益计算失败: {str(e)[:200]}")


@router.post("/clustering")
def get_clustering(
    factors: list[str] = Query(..., description="因子名列表"),
    pool: str = Query("all"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    distance_threshold: float = Query(0.3, ge=0.1, le=0.9, description="聚类距离阈值"),
):
    """层次聚类树 — 把相似因子自动归组"""
    try:
        return compute_factor_clustering(
            factors=factors,
            stock_pool=pool,
            start_date=start_date,
            end_date=end_date,
            distance_threshold=distance_threshold,
        )
    except Exception as e:
        logger.error("clustering failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"聚类失败: {str(e)[:200]}")


@router.post("/correlation")
def get_correlation(
    factors: list[str] = Query(..., description="因子名列表"),
    pool: str = Query("all", description="股票池"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    """计算因子相关性矩阵"""
    try:
        return compute_correlation_matrix(factors, pool, start_date, end_date)
    except Exception as e:
        logger.error("correlation matrix failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"相关性矩阵计算失败: {str(e)[:200]}")


@router.post("/scatter")
def get_scatter(
    factor_a: str = Query(..., description="X 轴因子"),
    factor_b: str = Query(..., description="Y 轴因子 (实际是次 5 日收益)"),
    pool: str = Query("all"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    sample: int = Query(500, description="最大采样点数"),
):
    """散点图数据: factor_a vs 次 5 日累计收益"""
    try:
        return compute_scatter_data(factor_a, factor_b, pool, start_date, end_date, sample)
    except Exception as e:
        logger.error("scatter failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"散点图计算失败: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════
#  GP 因子挖掘
# ═══════════════════════════════════════════════════════════

@router.post("/mine/run")
def run_gp_mine(
    pool: str = Query("csi800"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    population: int = Query(30, description="种群大小"),
    generations: int = Query(3, description="迭代代数"),
    top_k: int = Query(10, description="每代保留 top_k"),
    seed: int = Query(42),
):
    """运行 GP 遗传编程挖掘新因子

    时间预估:
      30 pop × 3 代 × csi800 (800 只 × 9 个月) ≈ 1-2 分钟
      50 pop × 5 代 ≈ 5-10 分钟
    """
    try:
        return gp_mine(pool, start_date, end_date, population, generations, top_k, seed)
    except Exception as e:
        logger.error("gp mine failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"GP 挖掘失败: {str(e)[:200]}")


@router.get("/mine/candidates")
def list_candidates(
    min_ir: float = Query(0.0, description="最小 IR 过滤"),
    limit: int = Query(50),
):
    """列出 GP 挖掘出的候选因子 (按 IR 降序)"""
    try:
        rows = query_all(
            "SELECT id, run_id, expr_text, ic_mean, ir, win_rate, valid_days, tree_depth, promoted, created_at "
            "FROM factor_candidates WHERE ir >= ? ORDER BY ir DESC LIMIT ?",
            (min_ir, limit),
        )
        return {"candidates": rows, "count": len(rows)}
    except Exception as e:
        logger.error("list candidates failed: %s", str(e))
        raise HTTPException(500, f"查询失败: {str(e)[:200]}")


@router.get("/mine/candidate")
def get_candidate_detail(id: int = Query(..., description="候选因子 ID")):
    """获取单个候选因子详情"""
    rows = query_all("SELECT * FROM factor_candidates WHERE id = ?", (id,))
    if not rows:
        raise HTTPException(404, "候选因子不存在")
    return rows[0]


@router.post("/mine/candidate/{candidate_id}/promote")
def promote_candidate(candidate_id: int):
    """人工审核通过 → 创建实验 + 走三轴状态机 (T1).

    v3.11 行为变更:
      - 不再简单 UPDATE factor_candidates.promoted=1
      - 创建 experiments 行 (lifecycle_status=candidate, version=1)
      - 返回新 experiment_id, 后续验证走 transition()
    老的 promoted 字段保留兼容 (写 1, 不影响下游读取)
    """
    user_id = get_current_user_id()

    # 1. 查候选 (必须存在)
    cand = query_one(
        "SELECT id, expr_text, ir FROM factor_candidates WHERE id = ?",
        (candidate_id,),
    )
    if not cand:
        raise HTTPException(404, f"候选因子 {candidate_id} 不存在")

    # 2. 写老字段 (兼容)
    from database import execute
    execute(
        "UPDATE factor_candidates SET promoted = 1 WHERE id = ?",
        (candidate_id,),
    )

    # 3. 创建实验 (state machine 起点)
    exp_id = create_experiment(
        owner_user_id=user_id,
        expr_text=cand["expr_text"],
        candidate_id=candidate_id,
        policy_version="v1.0.0",
        note=f"promoted from factor_candidates id={candidate_id}, ir={cand['ir']}",
    )

    return {
        "candidate_id": candidate_id,
        "experiment_id": exp_id,
        "lifecycle_status": "candidate",
        "portfolio_role": "none",
        "proposal_status": "pending",
        "version": 1,
        "rows": 1,
    }


@router.post("/mine/candidate/{candidate_id}/reject")
def reject_candidate(candidate_id: int, reason: str = Query("manual reject")):
    """人工拒绝候选 → 创建实验后直接走 rejected 终态."""
    user_id = get_current_user_id()
    cand = query_one(
        "SELECT id, expr_text FROM factor_candidates WHERE id = ?",
        (candidate_id,),
    )
    if not cand:
        raise HTTPException(404, f"候选因子 {candidate_id} 不存在")

    exp_id = create_experiment(
        owner_user_id=user_id,
        expr_text=cand["expr_text"],
        candidate_id=candidate_id,
        note=f"rejected: {reason[:200]}",
    )
    # candidate → rejected 是一次合法迁移
    try:
        row = transition(
            experiment_id=exp_id,
            axis="lifecycle_status",
            target="rejected",
            expected_version=1,
            actor=f"user:{user_id}",
            reason=reason[:200],
        )
    except (ExperimentConflictError, ExperimentTransitionError) as e:
        raise HTTPException(e.http_status, str(e)[:200])
    return {
        "candidate_id": candidate_id,
        "experiment_id": exp_id,
        "lifecycle_status": row["lifecycle_status"],
        "version": row["version"],
    }


# ═══════════════════════════════════════════════════════════
#  Phase 3: LightGBM ML 因子生成
# ═══════════════════════════════════════════════════════════

@router.post("/mine/run-ml")
def run_ml_mine(
    pool: str = Query("csi800"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    n_estimators: int = Query(100, description="LightGBM 树数量"),
    max_depth: int = Query(4, description="单树最大深度"),
    learning_rate: float = Query(0.05),
):
    """运行 LightGBM ML 因子生成

    输出:
      - 特征重要性排序
      - 训练集/测试集 IC/IR (防过拟合)
      - 多空对冲 spread (top 10% vs bottom 10%)
      - 模型 .pkl 文件路径
    """
    try:
        return train_ml_factor(pool, start_date, end_date, n_estimators, max_depth, learning_rate)
    except Exception as e:
        logger.error("ml mine failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"ML 挖掘失败: {str(e)[:200]}")


@router.post("/mine/train-ml-with-gp")
def train_ml_with_gp(
    pool: str = Query("csi800"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    gp_top_k: int = Query(5, description="取 IR 最高的 N 个 GP 因子"),
    n_estimators: int = Query(80, description="LightGBM 树数量"),
    max_depth: int = Query(4),
    learning_rate: float = Query(0.05),
):
    """GP + ML 联合训练

    流程:
      1. 读 factor_candidates 表的 Top K GP 因子表达式
      2. 训练基线 LightGBM（只用 15 个内置因子）
      3. 训练增强 LightGBM（15 + GP 因子叠加）
      4. 返回 IR/spread 对比

    耗时: csi800 + 270 天约 1-3 分钟
    """
    try:
        return train_ml_with_gp_factors(
            stock_pool=pool, start_date=start_date, end_date=end_date,
            gp_top_k=gp_top_k, n_estimators=n_estimators,
            max_depth=max_depth, learning_rate=learning_rate,
        )
    except Exception as e:
        logger.error("gp+ml train failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"GP+ML 训练失败: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════
#  因子生命周期管理
# ═══════════════════════════════════════════════════════════

@router.post("/lifecycle/evaluate")
def lifecycle_evaluate():
    """评估所有 15 个内置因子的 IC/IR, 更新 lifecycle_status 表

    规则:
      IR >= 0.30           → active
      0.10 <= IR < 0.30    → warning
      IR <  0.10            → warning (warning_days +1)
      warning_days >= 14    → retired (自动退役)
    """
    try:
        result = update_all_factors()
        return result
    except Exception as e:
        logger.error("lifecycle evaluate failed: %s", str(e), exc_info=True)
        raise HTTPException(500, f"生命周期评估失败: {str(e)[:200]}")


@router.get("/lifecycle/status")
def lifecycle_status():
    """列出所有因子的当前状态 (active / warning / retired)"""
    try:
        rows = get_all_statuses()
        return {
            "factors": rows,
            "count": len(rows),
            "summary": {
                "active": sum(1 for r in rows if r["status"] == "active"),
                "warning": sum(1 for r in rows if r["status"] == "warning"),
                "retired": sum(1 for r in rows if r["status"] == "retired"),
            },
        }
    except Exception as e:
        logger.error("lifecycle status failed: %s", str(e))
        raise HTTPException(500, f"查询失败: {str(e)[:200]}")


@router.post("/lifecycle/reset/{factor_name}")
def lifecycle_reset(factor_name: str):
    """手动重置某个因子状态 (例如发现误判时)"""
    ok = reset_factor(factor_name)
    return {"reset": factor_name, "ok": ok}