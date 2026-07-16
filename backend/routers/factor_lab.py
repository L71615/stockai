"""因子实验室路由 — IC 分析 / 相关性矩阵 / 散点图"""
import logging
from fastapi import APIRouter, HTTPException, Query

from services.factor_lab import (
    compute_factor_metrics,
    compute_correlation_matrix,
    compute_scatter_data,
    list_available_factors,
    get_supported_pools,
)

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
    """计算因子 IC 指标

    支持因子:
      价格: ma5/ma10/ma20/ma60
      动量: ret_5d/ret_10d/ret_20d/ret_60d
      技术: rsi_14, macd_signal, price_pos, ma_disposition
      波动: volatility, amplitude
      量能: vol_ratio
    """
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