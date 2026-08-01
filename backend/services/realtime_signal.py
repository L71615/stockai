"""盘中信号触发 — v5.0-alpha M3

复用现有:
  - condition_engine.evaluate(stock_data, condition_tree)
  - strategy_registry.get_registry()
  - strategy_backtest_service._load_strategy_conditions()
  - realtime_factor_cache.compute_factors_with_cache (M2 缓存层)

策略:对 watchlist + 持仓每只股票跑一次所有启用的策略 → 命中返回 Signal
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from database import query_all
from services.condition_engine import evaluate as ce_evaluate
from services.strategy_registry import get_registry
from services.strategy_backtest_service import _load_strategy_conditions

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────


@dataclass
class RealtimeSignal:
    strategy_id: str
    strategy_name: str
    stock_code: str
    direction: str  # 'buy' / 'sell'
    score: float    # alpha 阶段固定 0.7
    triggered_at: float
    reason: str
    snapshot_factors: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── 公共 API ──────────────────────────────────────────


def scan_signals(
    *,
    enabled_strategies: list[str],
    candidate_codes: list[str],
    minutes_window: int = 60,
) -> list[RealtimeSignal]:
    """扫一遍 candidate_codes, 返回触发的信号列表

    Args:
        enabled_strategies: 用户启用的策略 id 列表, e.g. ['turtle_s1', 'boll_mean']
        candidate_codes: watchlist + 持仓的股票代码列表
        minutes_window: 评估用的最近 bar 数(alpha 阶段用日级 fallback, 60 = 60 个交易日)

    Returns:
        触发的 RealtimeSignal 列表(可能为空)
    """
    if not enabled_strategies or not candidate_codes:
        return []

    signals: list[RealtimeSignal] = []
    registry = get_registry()

    # 一次加载所有策略的条件树 (alpha: 简化处理, 后续可优化成 per-strategy 加载)
    try:
        condition_tree = _load_strategy_conditions(enabled_strategies)
    except Exception as e:
        logger.exception("realtime_signal: _load_strategy_conditions 失败: %s", e)
        return []

    if not condition_tree:
        logger.warning("realtime_signal: 启用的策略没有加载到条件树")
        return []

    for sid in enabled_strategies:
        info = registry.get(sid)
        strategy_name = info.name if info else sid

        for code in candidate_codes:
            try:
                stock_data = _evaluate_code(code, minutes_window)
            except Exception as e:
                logger.debug("realtime_signal[%s]: _evaluate_code 失败: %s", code, e)
                continue

            if stock_data is None:
                continue  # 数据不足

            try:
                triggered = ce_evaluate(stock_data, condition_tree)
            except Exception as e:
                logger.warning("realtime_signal[%s.%s]: evaluate 异常: %s", code, sid, e)
                continue

            if triggered:
                signals.append(RealtimeSignal(
                    strategy_id=sid,
                    strategy_name=strategy_name,
                    stock_code=code,
                    direction="buy",
                    score=0.7,
                    triggered_at=time.time(),
                    reason=f"{strategy_name} 命中条件",
                    snapshot_factors=stock_data,
                ))

    return signals


# ── 内部:评估单只股票 ──────────────────────────────────


def _evaluate_code(code: str, window: int) -> dict | None:
    """评估单只股票是否可触发 — 构造 stock_data 喂给 condition_engine

    Returns:
        None: 数据不足(无法计算因子)
        dict: 包含所有 YAML 策略需要的字段(close/ma5/rsi_14/boll_position 等)
    """
    rows = query_all(
        "SELECT trade_date, open, high, low, close, volume "
        "FROM historical_kline WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?",
        (code, window),
    )
    if len(rows) < max(window // 2, 20):
        return None  # 数据不足, 跳过

    bars = list(reversed(rows))  # 倒序 → 正序
    # historical_kline.amount 可能不存在, 暂用 volume * close 估算
    closes = [r["close"] for r in bars if r["close"] is not None]
    volumes = [r["volume"] for r in bars if r["volume"] is not None]
    if len(closes) < 20:
        return None

    # 复用 M2 因子缓存(避免每次重算)
    from services.realtime_factor_cache import compute_factors_with_cache
    factors = compute_factors_with_cache(
        code=code, closes=closes, volumes=volumes,
    )

    # 补算 M2 没覆盖的字段(YAML 策略需要的)
    avg_amount_20d = _avg_amount_n(bars, 20)
    high_20d = max((r["high"] for r in bars[-20:] if r["high"] is not None), default=None)
    high_55d = (
        max((r["high"] for r in bars[-55:] if r["high"] is not None), default=None)
        if len(bars) >= 55 else None
    )
    atr_pct = _atr_pct(bars, 14)
    last_close = closes[-1]

    return {
        # 基础行情
        "close": last_close,
        "price": last_close,
        # 因子(M2 已覆盖)
        "ma5": factors.get("ma5"),
        "ma10": factors.get("ma10"),
        "ma20": factors.get("ma20"),
        "ma60": factors.get("ma60"),
        "rsi_14": factors.get("rsi_14"),
        "macd_signal": factors.get("macd_signal"),
        "vol_ratio": factors.get("vol_ratio"),
        "volatility": factors.get("volatility"),
        "amplitude": factors.get("amplitude"),
        "ret_5d": factors.get("ret_5d"),
        "ret_20d": factors.get("ret_20d"),
        # 补算字段
        "avg_amount_20d": avg_amount_20d,
        "high_20d": high_20d,
        "high_55d": high_55d,
        "close_vs_high_20d": (
            (last_close - high_20d) / high_20d if high_20d and high_20d > 0 else None
        ),
        "close_vs_high_55d": (
            (last_close - high_55d) / high_55d if high_55d and high_55d > 0 else None
        ),
        "atr_pct": atr_pct,
    }


def _avg_amount_n(bars: list[dict], n: int) -> float | None:
    """最近 n 日均成交额(估算)

    historical_kline 有 volume 但不一定有 amount; 用 volume * close 估算.
    """
    vols = [r["volume"] * r["close"] for r in bars[-n:]
            if r.get("volume") is not None and r.get("close") is not None]
    if not vols:
        return None
    return sum(vols) / len(vols)


def _atr_pct(bars: list[dict], n: int = 14) -> float | None:
    """ATR (n) / close — 波动率百分比"""
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev_close = bars[i - 1]["close"] if i - 1 < 0 else bars[i]["open"]
        if high is None or low is None or prev_close is None:
            continue
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if not trs:
        return None
    atr = sum(trs) / len(trs)
    last_close = bars[-1]["close"]
    if not last_close or last_close <= 0:
        return None
    return atr / last_close