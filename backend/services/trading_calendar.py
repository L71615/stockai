"""A 股交易日历工具 — 跨模块共享 (v3.11+, D4)

按 plan-ceo-review 2026-07-24 / eng-review D4 设计:
  把 routers/data_ops.py 里私有的 _get_a_share_calendar / _trading_days_lag
  提到 services 层, 让 validation_policy / pipeline / shadow 都可复用.

公开 API:
  - trading_days_lag(last_trade_date, today=None) -> int
  - get_a_share_calendar() -> set[str]   (lazy load + cache)
  - next_trading_day(date_str) -> str    (含节假日)
  - prev_trading_day(date_str) -> str
  - is_trading_day(date_str) -> bool

akshare 拉取失败时, 回退到"简单日历天数"策略 (可能误算, 但不会崩).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_A_SHARE_TRADING_DAYS: Optional[set[str]] = None


def get_a_share_calendar() -> set[str]:
    """从 akshare 拉官方 A 股交易日历 (含节假日剔除).

    Returns:
        set of 'YYYY-MM-DD' 字符串
        akshare 拉取失败返回空 set (调用方需用 fallback)
    """
    global _A_SHARE_TRADING_DAYS
    if _A_SHARE_TRADING_DAYS is None:
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            _A_SHARE_TRADING_DAYS = set(df["trade_date"].astype(str).tolist())
            logger.info("A 股交易日历加载: %d 天", len(_A_SHARE_TRADING_DAYS))
        except Exception as e:
            logger.warning("akshare 交易日历拉取失败, 回退到日历天数: %s", e)
            _A_SHARE_TRADING_DAYS = set()
    return _A_SHARE_TRADING_DAYS


def reset_calendar_cache() -> None:
    """测试用: 重置日历缓存, 下次调用会重新拉"""
    global _A_SHARE_TRADING_DAYS
    _A_SHARE_TRADING_DAYS = None


def trading_days_lag(last_trade_date: date, today: Optional[date] = None) -> int:
    """计算 A 股交易日差距 (不算 last_trade_date 本身)

    Args:
        last_trade_date: 最近一个交易日
        today: 比较日, 默认今天

    Returns:
        0 = 今天就是最新交易日
        1 = 滞后 1 个交易日
        N = 滞后 N 个交易日

    Fallback: akshare 拉不到时用日历天数 (周末也算)
    """
    if today is None:
        today = date.today()
    if last_trade_date >= today:
        return 0
    calendar = get_a_share_calendar()
    if not calendar:
        return (today - last_trade_date).days
    d = last_trade_date
    n = 0
    while d < today:
        d = d + timedelta(days=1)
        if d.isoformat() in calendar:
            n += 1
    return n


def trading_days_lag_str(last_trade_date_str: str, today_str: Optional[str] = None) -> int:
    """字符串版 trading_days_lag, ISO 'YYYY-MM-DD' 入参"""
    last = datetime.strptime(last_trade_date_str, "%Y-%m-%d").date()
    today = (
        datetime.strptime(today_str, "%Y-%m-%d").date()
        if today_str else date.today()
    )
    return trading_days_lag(last, today)


def is_trading_day(date_str: str) -> bool:
    """判断 date_str 是否是 A 股交易日.

    akshare 拉不到时回退到 weekday<5 (周末不算交易日).
    """
    calendar = get_a_share_calendar()
    if calendar:
        return date_str in calendar
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.weekday() < 5
    except ValueError:
        return False


def next_trading_day(date_str: str) -> str:
    """给定日期, 返回下一个 A 股交易日 (含节假日跳过).

    输入若本身就是交易日, 返回 +1 个交易日.
    输入非法日期抛 ValueError.
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"invalid date format: {date_str}") from e
    calendar = get_a_share_calendar()
    if not calendar:
        # fallback: +1 跳过周末
        cur = d + timedelta(days=1)
        while cur.weekday() >= 5:
            cur += timedelta(days=1)
        return cur.isoformat()
    cur = d
    for _ in range(365):  # 一年上限防死循环
        cur += timedelta(days=1)
        if cur.isoformat() in calendar:
            return cur.isoformat()
    raise ValueError(f"一年内找不到 {date_str} 的下一个交易日 (日历可能不全)")


def prev_trading_day(date_str: str) -> str:
    """给定日期, 返回上一个 A 股交易日 (含节假日跳过)."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"invalid date format: {date_str}") from e
    calendar = get_a_share_calendar()
    if not calendar:
        cur = d - timedelta(days=1)
        while cur.weekday() >= 5:
            cur -= timedelta(days=1)
        return cur.isoformat()
    cur = d
    for _ in range(365):
        cur -= timedelta(days=1)
        if cur.isoformat() in calendar:
            return cur.isoformat()
    raise ValueError(f"一年内找不到 {date_str} 的上一个交易日 (日历可能不全)")