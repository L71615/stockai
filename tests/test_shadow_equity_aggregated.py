"""v4.1 1B.2: shadow_equity_aggregated + get_shadow_equity_curve 测试"""
import json

import pytest

from database import query_one, execute
from services.shadow_portfolio_service import (
    _insert_snapshot,
    get_shadow_equity_curve,
)


@pytest.fixture
def admin_user_id(_test_db_session):
    user = query_one("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    return user["id"]


def _make_portfolio(admin_user_id: int) -> int:
    now = "2026-07-01 09:30:00"
    cur = execute(
        "INSERT INTO shadow_portfolios (owner_user_id, name, status, target_weights_json, created_at, updated_at) "
        "VALUES (?, 'test_portfolio', 'active', '{}', ?, ?)",
        (admin_user_id, now, now),
    )
    return int(cur["lastrowid"])


def _write_one_snapshot(portfolio_id: int, date: str, nav: float = 1.0, drawdown: float = 0.0):
    _insert_snapshot(
        portfolio_id=portfolio_id,
        observation_date=date,
        nav=nav,
        cash=10000.0,
        holdings={},
        target_weights={},
        actual_weights={},
        turnover=0.0,
        costs=0.0,
        drawdown=drawdown,
        baseline_diff={"csi300": 0.0},
        status="settled",
        reason="",
        input_version="v1.0.0",
    )


def test_snapshot_writes_to_aggregated(admin_user_id):
    """write_shadow_snapshot 应该同步写 1d bucket"""
    pid = _make_portfolio(admin_user_id)
    _write_one_snapshot(pid, "2026-07-15", nav=1.05, drawdown=-0.02)

    rows = execute(
        "SELECT * FROM shadow_equity_aggregated WHERE portfolio_id = ? AND bucket = '1d'",
        (pid,),
    )
    # execute 不返回 list, 重新查
    from database import query_all
    agg = query_all(
        "SELECT * FROM shadow_equity_aggregated WHERE portfolio_id = ? AND bucket = '1d'",
        (pid,),
    )
    assert len(agg) == 1
    assert agg[0]["observation_date"] == "2026-07-15"
    assert agg[0]["nav"] == 1.05
    assert agg[0]["drawdown"] == -0.02


def test_get_curve_returns_points(admin_user_id):
    """get_shadow_equity_curve 返回预聚合数据"""
    pid = _make_portfolio(admin_user_id)
    for d, nav in [
        ("2026-07-01", 1.000),
        ("2026-07-02", 1.010),
        ("2026-07-03", 1.005),
    ]:
        _write_one_snapshot(pid, d, nav=nav)

    points = get_shadow_equity_curve(portfolio_id=pid, bucket="1d", days=30)
    assert len(points) == 3
    assert points[0]["date"] == "2026-07-01"
    assert points[-1]["nav"] == 1.005


def test_curve_respects_days_filter(admin_user_id):
    """days 参数过滤掉太老的点"""
    pid = _make_portfolio(admin_user_id)
    _write_one_snapshot(pid, "2025-01-01", nav=1.0)            # 远在 30 天之前
    _write_one_snapshot(pid, "2026-07-29", nav=1.05)

    points = get_shadow_equity_curve(portfolio_id=pid, bucket="1d", days=30)
    # '2025-01-01' 应该被过滤
    assert len(points) == 1
    assert points[0]["date"] == "2026-07-29"


def test_snapshot_upsert_overwrites_existing(admin_user_id):
    """同一天不同 input_version 写 snapshot 应该覆盖聚合表的同一条 (upsert)"""
    from services.shadow_portfolio_service import _insert_snapshot
    pid = _make_portfolio(admin_user_id)
    _insert_snapshot(
        portfolio_id=pid, observation_date="2026-07-15",
        nav=1.05, cash=10000.0, holdings={}, target_weights={},
        actual_weights={}, turnover=0.0, costs=0.0, drawdown=-0.02,
        baseline_diff={"csi300": 0.0}, status="settled", reason="",
        input_version="v1.0.0",
    )
    # 不同 input_version → 触发真正的 upsert
    _insert_snapshot(
        portfolio_id=pid, observation_date="2026-07-15",
        nav=1.10, cash=10000.0, holdings={}, target_weights={},
        actual_weights={}, turnover=0.0, costs=0.0, drawdown=-0.05,
        baseline_diff={"csi300": 0.0}, status="settled", reason="",
        input_version="v1.0.1",
    )

    from database import query_all
    agg = query_all(
        "SELECT nav, drawdown FROM shadow_equity_aggregated "
        "WHERE portfolio_id = ? AND bucket = '1d' AND observation_date = '2026-07-15'",
        (pid,),
    )
    assert len(agg) == 1
    assert agg[0]["nav"] == 1.10
    assert agg[0]["drawdown"] == -0.05