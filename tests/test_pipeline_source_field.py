"""v4.1 1A.3: t1_pending_orders.source 字段 + proposal_id 字段

- 旧 schema 无 source 时, create_pending_order 自动 ALTER + 重试
- 新 schema 直接用 source='pipeline_proposal' / 'user_manual'
"""
import pytest

from services.t1_watcher import create_pending_order, cancel_order
from database import query_one


@pytest.fixture
def admin_user_id(_test_db_session):
    user = query_one("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    return user["id"]


def test_create_pending_order_default_source_is_user_manual(admin_user_id):
    """默认 source='user_manual'"""
    order = create_pending_order(user_id=admin_user_id, stock_code="600519")
    assert order["source"] == "user_manual"
    assert order["proposal_id"] is None
    # DB 中确实写了 source 列
    row = query_one("SELECT source, proposal_id FROM t1_pending_orders WHERE id = ?", (order["id"],))
    assert row["source"] == "user_manual"
    assert row["proposal_id"] is None


def test_create_pending_order_with_pipeline_source(admin_user_id):
    """source='pipeline_proposal' + proposal_id 关联"""
    order = create_pending_order(
        user_id=admin_user_id,
        stock_code="600519",
        stock_name="贵州茅台",
        shares=100,
        source="pipeline_proposal",
        proposal_id=42,
    )
    assert order["source"] == "pipeline_proposal"
    assert order["proposal_id"] == 42
    row = query_one("SELECT source, proposal_id FROM t1_pending_orders WHERE id = ?", (order["id"],))
    assert row["source"] == "pipeline_proposal"
    assert row["proposal_id"] == 42


def test_create_pending_order_with_manual_source(admin_user_id):
    """手动 source='user_manual' + proposal_id=None"""
    order = create_pending_order(
        user_id=admin_user_id,
        stock_code="000001",
        source="user_manual",
        proposal_id=None,
    )
    assert order["source"] == "user_manual"
    assert order["proposal_id"] is None


def test_cancel_pipeline_proposal_order(admin_user_id):
    """来自 pipeline_proposal 的订单也可以取消"""
    order = create_pending_order(
        user_id=admin_user_id,
        stock_code="600519",
        source="pipeline_proposal",
        proposal_id=1,
    )
    ok = cancel_order(order_id=order["id"], user_id=admin_user_id, reason="AI 撤回")
    assert ok is True
    row = query_one("SELECT status FROM t1_pending_orders WHERE id = ?", (order["id"],))
    assert row["status"] == "cancelled"