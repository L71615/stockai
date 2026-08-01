"""盘中因子缓存 + 计算 — v5.0-alpha M2

设计:
  - 复用 services/factor_lab.FACTOR_REGISTRY (30 个可直接调用的因子)
  - 缓存层: SQLite 表 realtime_factor_cache, 5m TTL
  - 输入: 分钟级 bar 序列(从 historical_kline 取最近 N 根)
  - 输出: dict[factor_name, value]

性能目标:
  - 单只股票 × 30 因子: < 100ms (命中缓存) / < 500ms (重算)
  - watchlist 50 只 × 30 因子: < 5s (并行/异步)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np

from database import execute, query_all, query_one

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 300  # 5 分钟


# ── 公共 API ──────────────────────────────────────────


def get_cached_factor(code: str, factor_name: str) -> float | None:
    """取单个缓存因子(过期返回 None)"""
    row = query_one(
        "SELECT value, ts FROM realtime_factor_cache WHERE stock_code = ? AND factor_name = ?",
        (code, factor_name),
    )
    if row is None:
        return None
    if time.time() - row["ts"] > CACHE_TTL_SECONDS:
        return None  # 过期
    return row["value"]


def get_all_cached(code: str) -> dict[str, float]:
    """取某股票的所有未过期缓存因子"""
    rows = query_all(
        "SELECT factor_name, value, ts FROM realtime_factor_cache WHERE stock_code = ?",
        (code,),
    )
    now = time.time()
    return {
        r["factor_name"]: r["value"]
        for r in rows
        if r["value"] is not None and now - r["ts"] <= CACHE_TTL_SECONDS
    }


def set_cached_factor(code: str, factor_name: str, value: float | None) -> None:
    """写单个因子到缓存(value=None 不写 — 跳过空值)"""
    if value is None:
        return
    try:
        execute(
            """INSERT INTO realtime_factor_cache (stock_code, factor_name, value, ts)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(stock_code, factor_name) DO UPDATE
                   SET value = excluded.value, ts = excluded.ts""",
            (code, factor_name, float(value), time.time()),
        )
    except Exception as e:
        logger.warning("realtime_factor_cache.set failed: %s", e)


def invalidate(code: str) -> None:
    """清某股票的所有缓存(alpha 测试用)"""
    execute("DELETE FROM realtime_factor_cache WHERE stock_code = ?", (code,))


# ── 因子计算 ──────────────────────────────────────────


def compute_realtime_factors(
    *,
    code: str,
    closes: list[float],
    volumes: list[float] | None = None,
    factor_names: list[str] | None = None,
) -> dict[str, float | None]:
    """计算盘中分钟级因子

    Args:
        code: 股票代码(日志用)
        closes: 最近 N 根 bar 的收盘价序列(分钟级)
        volumes: 最近 N 根 bar 的成交量序列(可选)
        factor_names: 要算的因子名列表,None = 全部 30 个

    Returns:
        {factor_name: value or None}  None 表示计算失败或数据不足
    """
    from services.factor_lab import FACTOR_REGISTRY

    if len(closes) < 5:
        logger.debug("realtime_factor[%s]: 收盘序列不足 5 根, 跳过", code)
        return {}

    vols = volumes or [0.0] * len(closes)
    targets = factor_names or list(FACTOR_REGISTRY.keys())
    results: dict[str, float | None] = {}

    for name in targets:
        if name not in FACTOR_REGISTRY:
            results[name] = None
            continue
        fn, needs_volume = FACTOR_REGISTRY[name]
        try:
            raw = fn(closes, vols if needs_volume else None)
            scalar = _extract_scalar(raw, closes)
            results[name] = scalar
        except Exception as e:
            logger.debug("realtime_factor[%s.%s] 计算失败: %s", code, name, e)
            results[name] = None

    return results


def _extract_scalar(raw, closes: list[float]) -> float | None:
    """从因子函数的返回值中提取最近一个标量

    因子函数可能返回:
      - float (直接)
      - list/np.ndarray (取最后 1 个)
      - None / NaN (返回 None)
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    if isinstance(raw, (list, np.ndarray)):
        # 取最后一个非 None 值
        for v in reversed(raw):
            if v is None:
                continue
            try:
                vf = float(v)
                if not (np.isnan(vf) or np.isinf(vf)):
                    return vf
            except (TypeError, ValueError):
                continue
        return None
    return None


# ── 缓存包装 ──────────────────────────────────────────


def compute_factors_with_cache(
    *,
    code: str,
    closes: list[float],
    volumes: list[float] | None = None,
    factor_names: list[str] | None = None,
) -> dict[str, float | None]:
    """带缓存的因子计算

    1. 先查 cache — 已有的跳过
    2. 未命中 + 没缓存 → 重算全部
    3. 未命中 + 部分缓存 → 重算缺失的
    4. 写回 cache
    """
    cached = get_all_cached(code)

    targets = factor_names or list(_all_factor_names())
    if not cached or set(targets) - set(cached.keys()):
        new_factors = compute_realtime_factors(
            code=code, closes=closes, volumes=volumes, factor_names=targets,
        )
        for name, val in new_factors.items():
            set_cached_factor(code, name, val)
        cached.update({k: v for k, v in new_factors.items() if v is not None})

    # 返回结果(优先 cache + 加上 None 标记的未算因子)
    result: dict[str, float | None] = {}
    for name in targets:
        result[name] = cached.get(name)
    return result


def _all_factor_names() -> list[str]:
    from services.factor_lab import FACTOR_REGISTRY
    return list(FACTOR_REGISTRY.keys())


# ── 从 historical_kline 拉取分钟级数据(临时,beta 换 futu intraday) ─────


def fetch_recent_bars(code: str, limit: int = 240) -> tuple[list[float], list[float]]:
    """从 historical_kline 取最近 N 根 bar(临时 — 用日级 fallback)

    v5.0-alpha 阶段用日级数据 fallback(分钟级 K 线表 beta 阶段才有)
    真实盘中用 futu_raw_kline 表(M11 阶段)
    """
    rows = query_all(
        "SELECT close, volume FROM historical_kline WHERE stock_code = ? "
        "ORDER BY trade_date DESC LIMIT ?",
        (code, limit),
    )
    # 倒序 → 正序
    rows = list(reversed(rows))
    closes = [r["close"] for r in rows if r["close"] is not None]
    volumes = [r["volume"] for r in rows if r["volume"] is not None]
    return closes, volumes