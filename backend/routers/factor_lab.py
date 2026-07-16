"""因子实验室路由 — IC 分析 / 相关性矩阵 / 散点图 / GP 挖掘"""
import logging
from fastapi import APIRouter, HTTPException, Query

from services.factor_lab import (
    compute_factor_metrics,
    compute_correlation_matrix,
    compute_scatter_data,
    list_available_factors,
    get_supported_pools,
)
from services.factor_expr import gp_mine
from database import query_all

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
    """标记候选因子为'已采纳' (人工审核后调用)"""
    from database import execute
    cur = execute(
        "UPDATE factor_candidates SET promoted = 1 WHERE id = ?",
        (candidate_id,),
    )
    return {"promoted": candidate_id, "rows": cur.rowcount if hasattr(cur, "rowcount") else 0}