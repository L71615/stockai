"""v5.2.4 — K 线重复日期聚合测试

背景: /api/stocks/kline/{code}?period=1m 走分钟线路径,Futu 偶尔返回
  陈旧分钟线(全部落在同一天 2025-08-07),前端 lightweight-charts
  收到 32 个相同 timestamp 的 bar 会崩溃:
  'Assertion failed: data must be asc ordered by time'

修复: 后端检测到重复日期时,按 date 聚合(open=首个, high=max,
  low=min, close=最后, volume=sum),同时前端 toChartBars 也加了 dedup 兜底。

覆盖:
  1. 32 根分钟线全部同日 → 聚合成 1 根 daily bar
  2. 多日混合 → 按日期聚合
  3. 唯一日期 → 不变
  4. _aggregate_bars 输出如果重复 → 也被去重
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_aggregate_same_date_minute_bars():
    """核心场景: 32 根分钟线同日期 → 1 根 daily bar"""
    from routers.stocks import _aggregate_minute_bars_by_date

    dates = ["2025-08-07"] * 32
    opens = [23.63 + i * 0.01 for i in range(32)]
    highs = [23.65 + i * 0.01 for i in range(32)]
    lows = [23.60 + i * 0.01 for i in range(32)]
    closes = [23.62 + i * 0.01 for i in range(32)]
    volumes = [200000.0] * 32

    d, o, h, l, c, v = _aggregate_minute_bars_by_date(dates, opens, highs, lows, closes, volumes)

    assert d == ["2025-08-07"]
    assert o == [opens[0]]
    assert h == [max(highs)]
    assert l == [min(lows)]
    assert c == [closes[-1]]
    assert v == [sum(volumes)]


def test_aggregate_multi_date():
    """多日混合 → 按日期聚合 + 排序"""
    from routers.stocks import _aggregate_minute_bars_by_date

    dates = ["2025-08-07", "2025-08-06", "2025-08-07", "2025-08-05", "2025-08-06"]
    opens = [10.0, 20.0, 11.0, 30.0, 21.0]
    highs = [11.0, 22.0, 13.0, 33.0, 25.0]
    lows = [9.0, 19.0, 10.5, 29.0, 20.5]
    closes = [10.5, 21.0, 12.0, 32.0, 24.0]
    volumes = [100.0, 200.0, 150.0, 300.0, 250.0]

    d, o, h, l, c, v = _aggregate_minute_bars_by_date(dates, opens, highs, lows, closes, volumes)

    assert d == ["2025-08-05", "2025-08-06", "2025-08-07"]
    # 8-05: 30.0 / 33.0 / 29.0 / 32.0 / 300.0
    assert o[0] == 30.0 and h[0] == 33.0 and l[0] == 29.0 and c[0] == 32.0 and v[0] == 300.0
    # 8-06: open=20, high=max(22,25)=25, low=min(19,20.5)=19, close=24, vol=200+250=450
    assert o[1] == 20.0 and h[1] == 25.0 and l[1] == 19.0 and c[1] == 24.0 and v[1] == 450.0
    # 8-07: open=10, high=max(11,13)=13, low=min(9,10.5)=9, close=12, vol=100+150=250
    assert o[2] == 10.0 and h[2] == 13.0 and l[2] == 9.0 and c[2] == 12.0 and v[2] == 250.0


def test_aggregate_unique_dates_no_op():
    """唯一日期 → 保持原样(已经是 unique)"""
    from routers.stocks import _aggregate_minute_bars_by_date

    dates = ["2025-08-05", "2025-08-06", "2025-08-07"]
    opens = [10.0, 20.0, 30.0]
    highs = [11.0, 22.0, 33.0]
    lows = [9.0, 19.0, 29.0]
    closes = [10.5, 21.0, 32.0]
    volumes = [100.0, 200.0, 300.0]

    d, o, h, l, c, v = _aggregate_minute_bars_by_date(dates, opens, highs, lows, closes, volumes)

    assert d == dates
    assert o == opens
    assert h == highs
    assert l == lows
    assert c == closes
    assert v == volumes


def test_aggregate_empty():
    """空数据 → 空输出"""
    from routers.stocks import _aggregate_minute_bars_by_date

    d, o, h, l, c, v = _aggregate_minute_bars_by_date([], [], [], [], [], [])

    assert d == [] and o == [] and h == [] and l == [] and c == [] and v == []


def test_aggregate_called_in_get_kline(monkeypatch):
    """get_kline_data 端到端: 分钟线 mock 全部同日 → 聚合后 1 根"""
    from routers.stocks import get_kline_data

    # Mock 替代 get_minute_kline_with_fallback
    def mock_minute_kline(code, count, fallback, client=None):
        # 32 根分钟线,全部 2025-08-07(模拟 Futu 陈旧数据)
        dates = ["2025-08-07"] * 32
        return {
            "code": code,
            "dates": dates,
            "opens": [23.63 + i * 0.01 for i in range(32)],
            "highs": [23.65 + i * 0.01 for i in range(32)],
            "lows": [23.60 + i * 0.01 for i in range(32)],
            "closes": [23.62 + i * 0.01 for i in range(32)],
            "volumes": [200000.0] * 32,
        }

    monkeypatch.setattr("routers.stocks.get_minute_kline_with_fallback", mock_minute_kline)
    # 跳过市场判定,直接 mock
    monkeypatch.setattr("routers.stocks.get_market", lambda code: "SZ")

    result = get_kline_data("002747", period="1m")
    assert len(result["dates"]) == 1, f"应该聚合成 1 根,实际 {len(result['dates'])} 根"
    assert result["dates"][0] == "2025-08-07"
    assert result["closes"][0] == 23.62 + 31 * 0.01  # 最后一天的最后一个 close