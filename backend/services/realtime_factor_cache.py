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
import os
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
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
    factor_names: list[str] | None = None,
) -> dict[str, float | None]:
    """计算盘中因子 (v5.0-beta M7: 升级到 55 因子)

    转发到 services.factor_service.compute_minute_factors,
    该函数已实现 55 因子 MINUTE_FACTOR_REGISTRY 的 5 元组分发。
    """
    from services.factor_service import compute_minute_factors

    if len(closes) < 5:
        logger.debug("realtime_factor[%s]: 收盘序列不足 5 根, 跳过", code)
        return {}

    return compute_minute_factors(
        code=code,
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        volumes=volumes,
        factor_names=factor_names,
    )


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
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
    factor_names: list[str] | None = None,
) -> dict[str, float | None]:
    """带缓存的因子计算 (v5.0-beta M7: 支持 5 元组)"""
    cached = get_all_cached(code)

    targets = factor_names or list(_all_factor_names())
    if not cached or set(targets) - set(cached.keys()):
        new_factors = compute_realtime_factors(
            code=code,
            closes=closes,
            highs=highs,
            lows=lows,
            opens=opens,
            volumes=volumes,
            factor_names=targets,
        )
        for name, val in new_factors.items():
            set_cached_factor(code, name, val)
        cached.update({k: v for k, v in new_factors.items() if v is not None})

    result: dict[str, float | None] = {}
    for name in targets:
        result[name] = cached.get(name)
    return result


def _all_factor_names() -> list[str]:
    """v5.0-beta M7: 改读 MINUTE_FACTOR_REGISTRY (55 因子)"""
    from services.factor_service import MINUTE_FACTOR_REGISTRY
    return list(MINUTE_FACTOR_REGISTRY.keys())


# ── 从 K 线表拉取 bar(v5.0-beta M7: 5 元组分发, 灰度开关) ─────


def fetch_recent_bars(
    code: str,
    limit: int = 240,
) -> tuple[tuple[list[float], list[float], list[float], list[float], list[float]], str]:
    """从 minute 或 daily K 线表拉取最近 N 根 bar (M7: 返 5 元组 + data_source)

    v5.0-beta M7: 复用 M6 模式 — REALTIME_USE_MINUTE_BARS=true 走 1m 分钟级,
    Futu 查询空时自动 fallback 日级。独立实现,不跨模块依赖 realtime_factor_minute。
    """
    use_minute = os.getenv("REALTIME_USE_MINUTE_BARS", "false").strip().lower() == "true"

    if use_minute:
        rows = _fetch_minute_bars(code, limit)
        if not rows:
            logger.warning(
                "minute_bars_empty_for_code=%s fallback_to_daily minute_bars=0",
                code,
            )
            rows = _fetch_daily_bars(code, limit)
            return _to_series(rows), "historical_daily_fallback"
        return _to_series(rows), "futu_1m"

    rows = _fetch_daily_bars(code, limit)
    return _to_series(rows), "historical_daily_fallback"


def _fetch_minute_bars(code: str, limit: int) -> list[dict]:
    """读 futu_raw_kline (1m, qfq) 最近 N 根

    Returns: list[dict{bar_time, open, high, low, close, volume}] — 倒序（最新在前）
    """
    return query_all(
        """SELECT bar_time, open, high, low, close, volume
           FROM futu_raw_kline
           WHERE symbol = ? AND interval = '1m' AND adjust_type = 'qfq'
           ORDER BY bar_time DESC LIMIT ?""",
        (code, limit),
    )


def _fetch_daily_bars(code: str, limit: int) -> list[dict]:
    """读 historical_kline 最近 N 根 (日级 fallback)

    Returns: list[dict{bar_time, open, high, low, close, volume}] — 已按 bar_time 正序
    """
    rows = query_all(
        """SELECT trade_date as bar_time, open, high, low, close, volume
           FROM historical_kline
           WHERE stock_code = ?
           ORDER BY trade_date DESC LIMIT ?""",
        (code, limit),
    )
    return list(reversed(rows))


def _to_series(rows: list[dict]) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """统一转 (closes, highs, lows, opens, volumes) — None 值过滤"""
    closes = [r["close"] for r in rows if r["close"] is not None]
    highs = [r["high"] for r in rows if r.get("high") is not None]
    lows = [r["low"] for r in rows if r.get("low") is not None]
    opens = [r["open"] for r in rows if r.get("open") is not None]
    volumes = [r["volume"] for r in rows if r.get("volume") is not None]
    return closes, highs, lows, opens, volumes