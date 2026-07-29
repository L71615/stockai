"""v4.1 1A.1: scheduler t1_watcher 注册测试

只测 _t1_watcher_cycle 的辅助函数 (trading day / partial pipeline / health upsert),
不直接启 daemon thread (pytest 会 hang).
"""
from datetime import datetime, timedelta

import pytest

from database import query_one, execute
from services.scheduler import (
    _is_a_share_trading_day,
    _last_pipeline_status,
    _update_watcher_health,
    _check_watcher_health_3day_alert,
)


@pytest.fixture
def clean_watcher_health(_test_db_session):
    """测试前清空 watcher_health"""
    execute("DELETE FROM watcher_health")
    return _test_db_session


def test_is_trading_day_weekday(_test_db_session):
    """周三应该是交易日"""
    wed = datetime(2026, 7, 29)  # 实际是 2026-07-29 Wednesday
    assert _is_a_share_trading_day(wed) is True


def test_is_not_trading_day_weekend(_test_db_session):
    """周六不是交易日"""
    sat = datetime(2026, 8, 1)  # Saturday
    assert _is_a_share_trading_day(sat) is False


def test_last_pipeline_status_empty(_test_db_session):
    """空表返回 None"""
    execute("DELETE FROM experiment_runs WHERE scope = 'pipeline'")
    assert _last_pipeline_status() is None


def test_last_pipeline_status_returns_done(_test_db_session):
    """experiment_runs 最新 done 状态被返回"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute(
        "INSERT INTO experiments (experiment_id, owner_user_id, expr_text, snapshot_json, created_at, updated_at) "
        "VALUES ('test_pipeline_1', 1, 'test', '{}', ?, ?)",
        (now, now),
    )
    execute(
        "INSERT INTO experiment_runs (experiment_id, scope, status, started_at, finished_at) "
        "VALUES ('test_pipeline_1', 'pipeline', 'done', ?, ?)",
        (now, now),
    )
    assert _last_pipeline_status() == "done"


def test_watcher_health_insert_then_update(clean_watcher_health):
    """先 insert 一行, 再 update 同一条"""
    _update_watcher_health(status="ok", proposals_processed=5)
    row = query_one("SELECT last_status, last_run_proposals FROM watcher_health")
    assert row["last_status"] == "ok"
    assert row["last_run_proposals"] == 5

    _update_watcher_health(status="failed", proposals_processed=0, error="boom")
    row = query_one("SELECT last_status, last_run_proposals, last_error FROM watcher_health")
    assert row["last_status"] == "failed"
    assert row["last_error"] == "boom"
    # 仍是单行 (UPSERT)
    rows = query_one("SELECT COUNT(*) as cnt FROM watcher_health")
    assert rows["cnt"] == 1


def test_watcher_health_3day_alert_no_fire_when_fresh(clean_watcher_health):
    """今天刚跑过 → 不告警"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute(
        "INSERT INTO watcher_health (last_run_at, last_status, last_run_proposals) VALUES (?, 'ok', 3)",
        (now_str,),
    )
    # 调用应该不抛异常 (无 notify 渠道, 不会真的发出去)
    _check_watcher_health_3day_alert()
    # health 表不变
    row = query_one("SELECT last_status FROM watcher_health")
    assert row["last_status"] == "ok"


def test_watcher_health_3day_alert_no_fire_when_empty(clean_watcher_health):
    """从未跑过 (冷启动) → 不告警 (避免噪音)"""
    _check_watcher_health_3day_alert()
    # 表仍空
    rows = query_one("SELECT COUNT(*) as cnt FROM watcher_health")
    assert rows["cnt"] == 0