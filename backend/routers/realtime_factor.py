"""盘中因子 API — v5.0-alpha M2

REST 端点:
  GET /api/realtime/factor/{code}            — 单只股票所有因子
  GET /api/realtime/factor/{code}/?names=    — 指定子集因子
  POST /api/realtime/factor/{code}/invalidate — 清缓存(测试用)
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query

from services.realtime_factor_cache import (
    compute_factors_with_cache,
    fetch_recent_bars,
    invalidate as cache_invalidate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/realtime/factor", tags=["RealtimeFactor"])


@router.get("/{code}")
def get_realtime_factors(
    code: str,
    names: str = Query(default="", description="逗号分隔因子名, 留空 = 全部"),
):
    """取指定 code 的盘中因子

    Returns:
        {
            "code": str,
            "factors": {factor_name: value | null},
            "ts": float,
            "cached_count": int,  # 命中 cache 的因子数
            "fresh_count": int    # 本次重算的因子数
        }
    """
    try:
        closes, volumes = fetch_recent_bars(code, limit=240)
    except Exception as e:
        logger.exception("realtime_factor.fetch_bars(%s) 失败: %s", code, e)
        raise HTTPException(503, f"拉取 bar 失败: {e}")

    if not closes:
        raise HTTPException(404, f"无 K 线数据 for {code}")

    factor_list = [n.strip() for n in names.split(",") if n.strip()] if names else None
    factors = compute_factors_with_cache(
        code=code, closes=closes, volumes=volumes, factor_names=factor_list,
    )

    # 统计命中 / 重算
    from services.realtime_factor_cache import get_all_cached
    cached = get_all_cached(code)
    cached_count = sum(1 for n in (factor_list or list(cached.keys())) if n in cached)
    fresh_count = len(factors) - cached_count

    return {
        "code": code,
        "factors": factors,
        "ts": time.time(),
        "cached_count": cached_count,
        "fresh_count": fresh_count,
        "bar_count": len(closes),
    }


@router.post("/{code}/invalidate")
def invalidate_factor_cache(code: str):
    """清某股票的因子缓存(alpha 测试用)"""
    cache_invalidate(code)
    return {"code": code, "invalidated": True, "ts": time.time()}