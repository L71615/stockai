"""盘中分钟级 55 因子 REST API — v4.2 M2

新增路径(不动 v5.0-alpha M2 的 /api/realtime/factor/{code} 30 因子):
  GET /api/realtime/factor/{code}/minute           — 单只股票所有 55 因子
  GET /api/realtime/factor/{code}/minute?names=    — 指定子集因子
  POST /api/realtime/factor/{code}/minute/invalidate — 清 minute_factor_cache(测试用)
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query

from services.realtime_factor_minute import (
    compute_minute_factors_with_cache,
    fetch_recent_bars,
    invalidate as cache_invalidate,
    all_factor_names,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/realtime/factor", tags=["RealtimeFactorMinute"])


@router.get("/{code}/minute")
def get_minute_factors(
    code: str,
    names: str = Query(default="", description="逗号分隔因子名, 留空 = 全部 55"),
):
    """取指定 code 的分钟级 55 因子

    Returns:
        {
            "code": str,
            "factors": {factor_name: value | null},
            "ts": float,
            "bar_count": int,
            "cached_count": int,
            "fresh_count": int,
            "data_source": "historical_daily_fallback" | "futu_1m"(M11 切)
        }
    """
    try:
        (closes, highs, lows, opens, volumes), data_source = fetch_recent_bars(code, limit=240)
    except Exception as e:
        logger.exception("realtime_factor_minute.fetch_bars(%s) 失败: %s", code, e)
        raise HTTPException(503, f"拉取 bar 失败: {e}")

    if not closes or len(closes) < 5:
        raise HTTPException(404, f"无足够 K 线数据 for {code} (bar_count={len(closes)})")

    factor_list = [n.strip() for n in names.split(",") if n.strip()] if names else None

    factors = compute_minute_factors_with_cache(
        code=code, closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
        factor_names=factor_list,
    )

    from services.realtime_factor_minute import get_all_cached
    cached = get_all_cached(code)
    cached_count = sum(1 for n in (factor_list or list(cached.keys())) if n in cached)
    fresh_count = len(factors) - cached_count

    return {
        "code": code,
        "factors": factors,
        "ts": time.time(),
        "bar_count": len(closes),
        "cached_count": cached_count,
        "fresh_count": fresh_count,
        "data_source": data_source,  # 来自 fetch_recent_bars 返回 ("futu_1m" | "historical_daily_fallback")
    }


@router.post("/{code}/minute/invalidate")
def invalidate_minute_cache(code: str):
    """清某股票的 minute_factor_cache(alpha 测试用)"""
    cache_invalidate(code)
    return {"code": code, "invalidated": True, "ts": time.time()}


# 兼容 frontend 类型声明 — 导出因子名列表
@router.get("/{code}/minute/factor-names")
def list_factor_names():
    """返回 minute_factor 支持的全部因子名(小写)"""
    return {"factor_names": all_factor_names()}