"""盘中分钟级 55 因子计算 + 5m TTL 缓存 — v4.2 M2

复用:
  - services/factor_service.MINUTE_FACTOR_REGISTRY (55 因子, v4.2 M2 新增)
  - services/factor_service.compute_minute_factors() (55 因子计算入口)
  - services/realtime_factor_cache._extract_scalar (标量提取 — 已 v5.0-alpha 写过)

独立 cache 表:
  - minute_factor_cache (独立于 realtime_factor_cache, 5m TTL)
  - 后续 v5.0-rc 可能调 TTL(60s/300s/900s), 两个频段分开 cache 更灵活

数据源:
  - fetch_recent_bars() — 临时用 historical_kline 日级 fallback (60 根)
  - v5.0-rc M11 切 futu_raw_kline 分钟级 (1m / 5m)
"""
from __future__ import annotations

import logging
import os
import time

from database import execute, query_all, query_one

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 300  # 5 分钟


# ── 缓存 CRUD ────────────────────────────────────────


def get_cached_factor(code: str, factor_name: str) -> float | None:
    """取单个缓存因子(过期返回 None)"""
    row = query_one(
        "SELECT value, ts FROM minute_factor_cache WHERE stock_code = ? AND factor_name = ?",
        (code, factor_name),
    )
    if row is None:
        return None
    if time.time() - row["ts"] > CACHE_TTL_SECONDS:
        return None
    return row["value"]


def get_all_cached(code: str) -> dict[str, float]:
    """取某股票的所有未过期缓存因子"""
    rows = query_all(
        "SELECT factor_name, value, ts FROM minute_factor_cache WHERE stock_code = ?",
        (code,),
    )
    now = time.time()
    return {
        r["factor_name"]: r["value"]
        for r in rows
        if r["value"] is not None and now - r["ts"] <= CACHE_TTL_SECONDS
    }


def set_cached_factor(code: str, factor_name: str, value: float | None) -> None:
    """写单个因子到缓存(value=None 不写 — 跳过空值, 同 realtime_factor_cache)"""
    if value is None:
        return
    try:
        execute(
            """INSERT INTO minute_factor_cache (stock_code, factor_name, value, ts)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(stock_code, factor_name) DO UPDATE
                   SET value = excluded.value, ts = excluded.ts""",
            (code, factor_name, float(value), time.time()),
        )
    except Exception as e:
        logger.warning("minute_factor_cache.set failed: %s", e)


def invalidate(code: str) -> None:
    """清某股票的所有 minute 因子缓存(alpha 测试用)"""
    execute("DELETE FROM minute_factor_cache WHERE stock_code = ?", (code,))


# ── 数据获取(临时, v5.0-rc 切 futu_raw_kline) ─────


# ── 数据获取(v5.0-beta M6 — 灰度开关, 默认日级 fallback) ─────


def fetch_recent_bars(
    code: str,
    limit: int = 240,
) -> tuple[tuple[list[float], list[float], list[float], list[float], list[float]], str]:
    """从 minute 或 daily K 线表拉取最近 N 根 bar

    v5.0-beta M6: 灰度切换 — REALTIME_USE_MINUTE_BARS=true 走 1m 分钟级,
    Futu 查询空时自动 fallback 日级。

    Returns:
        ((closes, highs, lows, opens, volumes), data_source)
        data_source ∈ {"futu_1m", "historical_daily_fallback"}
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
    """读 futu_raw_kline(1m, qfq) 最近 N 根

    Returns: list[dict{bar_time, open, high, low, close, volume}]
             倒序（最新在前），调用方负责 reverse。
    """
    return query_all(
        """SELECT bar_time, open, high, low, close, volume
           FROM futu_raw_kline
           WHERE symbol = ? AND interval = '1m' AND adjust_type = 'qfq'
           ORDER BY bar_time DESC LIMIT ?""",
        (code, limit),
    )


def _fetch_daily_bars(code: str, limit: int) -> list[dict]:
    """读 historical_kline 最近 N 根（日级，alpha 既有逻辑）

    Returns: list[dict{bar_time, open, high, low, close, volume}]
             已按 bar_time 正序排列。
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


# ── 因子计算(带缓存) ─────────────────────────────────


def compute_minute_factors_with_cache(
    *,
    code: str,
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
    factor_names: list[str] | None = None,
) -> dict[str, float | None]:
    """带 minute_factor_cache 5m TTL 的因子计算

    流程:
      1. 读 cache 已有因子
      2. targets 中未命中 → 重算
      3. 写回 cache
      4. v4.2.3 patch: 注入 strategy 评估需要的辅助字段(close/open/high_20d 等)

    Args:
        同 factor_service.compute_minute_factors
    """
    from services.factor_service import compute_minute_factors

    cached = get_all_cached(code)

    if factor_names:
        targets = [n.lower() if isinstance(n, str) else n for n in factor_names]
    else:
        # targets 全集: 从 cache 缺失 + 显式指定
        from services.factor_service import MINUTE_FACTOR_REGISTRY
        targets = list(MINUTE_FACTOR_REGISTRY.keys())

    missing = [n for n in targets if n not in cached]
    extra_fields: dict[str, float | None] = {}  # v4.2.3: 衍生字段 (不入 cache)
    if missing:
        new_factors = compute_minute_factors(
            code=code,
            closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
            factor_names=missing,
        )
        for name, val in new_factors.items():
            # v4.2.3: 区分 cache-able factor (在 registry 内) vs 衍生字段
            from services.factor_service import MINUTE_FACTOR_REGISTRY
            if name in MINUTE_FACTOR_REGISTRY:
                set_cached_factor(code, name, val)
                if val is not None:
                    cached[name] = val
            else:
                # 衍生字段: 不写 cache (每次重新计算便宜, 也避免污染)
                extra_fields[name] = val

    # 返回: 优先 cache, 加上 None 标记的未算因子 + 衍生字段
    result: dict[str, float | None] = {}
    for name in targets:
        result[name] = cached.get(name)
    result.update(extra_fields)
    return result


def all_factor_names() -> list[str]:
    """返回 minute_factor_cache 支持的全部因子名(小写)"""
    from services.factor_service import MINUTE_FACTOR_REGISTRY
    return list(MINUTE_FACTOR_REGISTRY.keys())