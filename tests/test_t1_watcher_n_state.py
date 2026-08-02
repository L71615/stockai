"""T+1 watcher N 态机 + 事件溯源测试 — v4.2 M1

覆盖:
  - 6 状态常量 + ALL_STATUSES + LEGACY_STATUS_MAP
  - 状态转换白名单 (allow / reject)
  - transition() 函数 CAS 校验
  - transition() 写 t1_order_events 审计
  - 老字面量兼容 (双谓词查询 + summarize_user_pnl)
  - partial_filled 状态字段读写
"""

import json
from datetime import datetime
import pytest

from services import t1_watcher
from services.t1_watcher import (
    STATUS_OPEN,
    STATUS_PARTIAL_FILLED,
    STATUS_FILLED,
    STATUS_CLOSED,
    STATUS_CANCELLED,
    STATUS_REJECTED,
    ALL_STATUSES,
    LEGACY_STATUS_MAP,
    _ALLOWED_TRANSITIONS,
    _expand_legacy_status,
    _legacy_status_to_new,
    transition,
    create_pending_order,
    get_user_orders,
    get_order_by_id,
    cancel_order,
    # 老 alias — 让现有调用方能继续 import
    STATUS_PENDING_BUY,
    STATUS_BOUGHT,
)


# ═══════════════════════════════════════════════════════════════
#  6 状态常量 + 兼容性
# ═══════════════════════════════════════════════════════════════


class TestStatusConstants:
    def test_six_statuses_defined(self):
        assert STATUS_OPEN == "open"
        assert STATUS_PARTIAL_FILLED == "partial_filled"
        assert STATUS_FILLED == "filled"
        assert STATUS_CLOSED == "closed"
        assert STATUS_CANCELLED == "cancelled"
        assert STATUS_REJECTED == "rejected"

    def test_all_statuses_set(self):
        assert ALL_STATUSES == {
            STATUS_OPEN, STATUS_PARTIAL_FILLED, STATUS_FILLED,
            STATUS_CLOSED, STATUS_CANCELLED, STATUS_REJECTED,
        }
        assert len(ALL_STATUSES) == 6

    def test_legacy_status_map(self):
        """老字面量 → 新名字映射完整"""
        assert LEGACY_STATUS_MAP["pending_buy"] == STATUS_OPEN
        assert LEGACY_STATUS_MAP["pending_sell"] == STATUS_OPEN
        assert LEGACY_STATUS_MAP["bought"] == STATUS_FILLED
        assert LEGACY_STATUS_MAP["sold"] == STATUS_CLOSED
        # 4 个老字面量 → 3 个新名字(pending_buy + pending_sell 合并到 open)
        assert len(LEGACY_STATUS_MAP) == 4
        assert len(set(LEGACY_STATUS_MAP.values())) == 3

    def test_legacy_alias_constants(self):
        """v4.0 时代的 5 状态常量仍可 import(向后兼容)"""
        assert STATUS_PENDING_BUY == "pending_buy"
        assert STATUS_BOUGHT == "bought"


# ═══════════════════════════════════════════════════════════════
#  状态转换白名单 — 允许的 from→to
# ═══════════════════════════════════════════════════════════════


class TestTransitionAllowed:
    """白名单允许的转换:每个核心路径都要跑通"""

    def _make_order(self, db, target_status=STATUS_OPEN):
        """helper: 创建 1 条订单, 强制设置 status"""
        from database import execute
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        oid = create_pending_order(
            user_id=admin_id,
            stock_code="000001",
            stock_name="测试",
            shares=100,
        )["id"]
        # 强制改 status(绕过 transition 以便 setup 测试状态)
        execute(
            "UPDATE t1_pending_orders SET status = ? WHERE id = ?",
            (target_status, oid),
        )
        return oid

    def test_open_to_filled(self, db):
        oid = self._make_order(db, STATUS_OPEN)
        result = transition(order_id=oid, target=STATUS_FILLED, actor="test")
        assert result["status"] == STATUS_FILLED

    def test_open_to_cancelled(self, db):
        oid = self._make_order(db, STATUS_OPEN)
        result = transition(order_id=oid, target=STATUS_CANCELLED, actor="test")
        assert result["status"] == STATUS_CANCELLED

    def test_open_to_rejected(self, db):
        oid = self._make_order(db, STATUS_OPEN)
        result = transition(order_id=oid, target=STATUS_REJECTED, actor="test")
        assert result["status"] == STATUS_REJECTED

    def test_open_to_partial_filled(self, db):
        oid = self._make_order(db, STATUS_OPEN)
        result = transition(
            order_id=oid, target=STATUS_PARTIAL_FILLED,
            actor="test", filled_shares=50, pending_shares=50,
        )
        assert result["status"] == STATUS_PARTIAL_FILLED
        assert result["filled_shares"] == 50
        assert result["pending_shares"] == 50

    def test_partial_to_filled(self, db):
        oid = self._make_order(db, STATUS_PARTIAL_FILLED)
        result = transition(order_id=oid, target=STATUS_FILLED, actor="test")
        assert result["status"] == STATUS_FILLED

    def test_partial_to_open(self, db):
        """撤单重挂"""
        oid = self._make_order(db, STATUS_PARTIAL_FILLED)
        result = transition(order_id=oid, target=STATUS_OPEN, actor="test")
        assert result["status"] == STATUS_OPEN

    def test_filled_to_closed(self, db):
        oid = self._make_order(db, STATUS_FILLED)
        result = transition(order_id=oid, target=STATUS_CLOSED, actor="test")
        assert result["status"] == STATUS_CLOSED

    def test_legacy_open_to_filled(self, db):
        """老字面量 pending_buy 也允许转新状态 filled"""
        oid = self._make_order(db, STATUS_PENDING_BUY)  # 老字面量
        result = transition(order_id=oid, target=STATUS_FILLED, actor="test")
        assert result["status"] == STATUS_FILLED


# ═══════════════════════════════════════════════════════════════
#  状态转换白名单 — 拒绝的非法转换
# ═══════════════════════════════════════════════════════════════


class TestTransitionRejected:
    def _make_order(self, db, target_status=STATUS_OPEN):
        from database import execute
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        oid = create_pending_order(
            user_id=admin_id,
            stock_code="000001",
            stock_name="测试",
            shares=100,
        )["id"]
        execute(
            "UPDATE t1_pending_orders SET status = ? WHERE id = ?",
            (target_status, oid),
        )
        return oid

    def test_open_to_closed_rejected(self, db):
        """open → closed 不能直跳(必须先 filled)"""
        oid = self._make_order(db, STATUS_OPEN)
        with pytest.raises(ValueError, match="不在白名单"):
            transition(order_id=oid, target=STATUS_CLOSED, actor="test")

    def test_closed_is_terminal(self, db):
        """closed 是终态,不能转出"""
        oid = self._make_order(db, STATUS_CLOSED)
        for target in [STATUS_OPEN, STATUS_FILLED, STATUS_CANCELLED, STATUS_REJECTED]:
            with pytest.raises(ValueError, match="不在白名单"):
                transition(order_id=oid, target=target, actor="test")

    def test_cancelled_is_terminal(self, db):
        """cancelled 是终态"""
        oid = self._make_order(db, STATUS_CANCELLED)
        for target in [STATUS_OPEN, STATUS_FILLED, STATUS_CLOSED, STATUS_REJECTED]:
            with pytest.raises(ValueError, match="不在白名单"):
                transition(order_id=oid, target=target, actor="test")

    def test_rejected_is_terminal(self, db):
        """rejected 是终态"""
        oid = self._make_order(db, STATUS_REJECTED)
        for target in [STATUS_OPEN, STATUS_FILLED, STATUS_CLOSED, STATUS_CANCELLED]:
            with pytest.raises(ValueError, match="不在白名单"):
                transition(order_id=oid, target=target, actor="test")

    def test_unknown_target_rejected(self, db):
        oid = self._make_order(db, STATUS_OPEN)
        with pytest.raises(ValueError, match="不在 ALL_STATUSES"):
            transition(order_id=oid, target="unknown_status", actor="test")

    def test_nonexistent_order_rejected(self, db):
        with pytest.raises(ValueError, match="不存在"):
            transition(order_id=999999, target=STATUS_FILLED, actor="test")


# ═══════════════════════════════════════════════════════════════
#  CAS 校验 (expected_status)
# ═══════════════════════════════════════════════════════════════


class TestTransitionCAS:
    def _make_order(self, db, target_status=STATUS_OPEN):
        from database import execute
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        oid = create_pending_order(
            user_id=admin_id, stock_code="000001", stock_name="测试",
            shares=100,
        )["id"]
        execute(
            "UPDATE t1_pending_orders SET status = ? WHERE id = ?",
            (target_status, oid),
        )
        return oid

    def test_cas_match_passes(self, db):
        oid = self._make_order(db, STATUS_OPEN)
        # expected_status 与当前一致 → 允许
        result = transition(
            order_id=oid, target=STATUS_FILLED, actor="test",
            expected_status=STATUS_OPEN,
        )
        assert result["status"] == STATUS_FILLED

    def test_cas_mismatch_rejected(self, db):
        oid = self._make_order(db, STATUS_OPEN)
        # 当前是 open, 期望 filled → CAS 失败
        with pytest.raises(ValueError, match="CAS 失败"):
            transition(
                order_id=oid, target=STATUS_FILLED, actor="test",
                expected_status=STATUS_FILLED,  # 不匹配
            )

    def test_cas_accepts_legacy_status(self, db):
        """expected_status 可以传老字面量(兼容老调用方)"""
        oid = self._make_order(db, STATUS_PENDING_BUY)
        result = transition(
            order_id=oid, target=STATUS_FILLED, actor="test",
            expected_status=STATUS_PENDING_BUY,
        )
        assert result["status"] == STATUS_FILLED


# ═══════════════════════════════════════════════════════════════
#  transition 写 t1_order_events 审计
# ═══════════════════════════════════════════════════════════════


class TestTransitionWritesEvent:
    def _make_order(self, db, target_status=STATUS_OPEN):
        from database import execute
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        oid = create_pending_order(
            user_id=admin_id, stock_code="000001", stock_name="测试",
            shares=100,
        )["id"]
        execute(
            "UPDATE t1_pending_orders SET status = ? WHERE id = ?",
            (target_status, oid),
        )
        return oid

    def test_event_written(self, db):
        from database import query_all
        oid = self._make_order(db, STATUS_OPEN)
        transition(
            order_id=oid, target=STATUS_FILLED,
            actor="scheduler", event_type="filled",
            reason="测试成交",
        )
        events = query_all(
            "SELECT * FROM t1_order_events WHERE order_id = ?", (oid,)
        )
        assert len(events) == 1
        e = events[0]
        assert e["from_status"] == "open"  # 原样记录老字面量("open" 是新的)
        assert e["to_status"] == "filled"
        assert e["actor"] == "scheduler"
        assert e["event_type"] == "filled"
        assert e["reason"] == "测试成交"

    def test_event_metadata_serialized(self, db):
        from database import query_all
        oid = self._make_order(db, STATUS_OPEN)
        metadata = {"risk_action": "block_buy", "max_position_pct": 0.45}
        transition(
            order_id=oid, target=STATUS_CANCELLED,
            actor="risk_guard", event_type="risk_blocked",
            reason="单仓位超 30%",
            metadata=metadata,
        )
        events = query_all(
            "SELECT * FROM t1_order_events WHERE order_id = ?", (oid,)
        )
        assert len(events) == 1
        assert json.loads(events[0]["metadata_json"]) == metadata

    def test_legacy_status_in_event(self, db):
        """老字面量作为 from_status 原样记录(可追溯)"""
        from database import query_all
        oid = self._make_order(db, STATUS_PENDING_BUY)  # 老字面量
        transition(
            order_id=oid, target=STATUS_FILLED,
            actor="scheduler", event_type="filled",
        )
        events = query_all(
            "SELECT * FROM t1_order_events WHERE order_id = ?", (oid,)
        )
        assert len(events) == 1
        # 老字面量原样记录(关键:可追溯!)
        assert events[0]["from_status"] == "pending_buy"
        assert events[0]["to_status"] == "filled"


# ═══════════════════════════════════════════════════════════════
#  老字面量兼容 (双谓词查询)
# ═══════════════════════════════════════════════════════════════


class TestLegacyCompatQuery:
    def test_expand_legacy_status_helper(self):
        """_expand_legacy_status 把新名字展开为 [新, 老...]"""
        from services.t1_watcher import _expand_legacy_status
        assert set(_expand_legacy_status("open")) == {"open", "pending_buy", "pending_sell"}
        assert set(_expand_legacy_status("filled")) == {"filled", "bought"}
        assert set(_expand_legacy_status("closed")) == {"closed", "sold"}
        # 终态(没老字面量)
        assert _expand_legacy_status("cancelled") == ["cancelled"]
        assert _expand_legacy_status("rejected") == ["rejected"]
        assert _expand_legacy_status("partial_filled") == ["partial_filled"]

    def test_legacy_status_to_new_helper(self):
        """_legacy_status_to_new 把任意字面量归一化"""
        from services.t1_watcher import _legacy_status_to_new
        assert _legacy_status_to_new("pending_buy") == "open"
        assert _legacy_status_to_new("pending_sell") == "open"
        assert _legacy_status_to_new("bought") == "filled"
        assert _legacy_status_to_new("sold") == "closed"
        # 新名字原样返回
        assert _legacy_status_to_new("open") == "open"
        assert _legacy_status_to_new("filled") == "filled"
        assert _legacy_status_to_new("closed") == "closed"
        # 终态
        assert _legacy_status_to_new("cancelled") == "cancelled"
        assert _legacy_status_to_new("rejected") == "rejected"

    def test_get_user_orders_filter_open_returns_legacy(self, db):
        """status='open' 查询返回老字面量 pending_buy/pending_sell"""
        from database import execute, query_all
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]

        # 用唯一 stock_code 前缀避免与其他测试冲突
        unique_prefix = f"9999{datetime.now().strftime('%H%M%S%f')}"

        # 创建 1 条老字面量 pending_buy 订单
        oid1 = create_pending_order(
            user_id=admin_id, stock_code=f"{unique_prefix}A", stock_name="A", shares=100,
        )["id"]
        execute(
            "UPDATE t1_pending_orders SET status = ? WHERE id = ?",
            ("pending_buy", oid1),
        )
        # 创建 1 条老字面量 pending_sell
        oid2 = create_pending_order(
            user_id=admin_id, stock_code=f"{unique_prefix}B", stock_name="B", shares=100,
        )["id"]
        execute(
            "UPDATE t1_pending_orders SET status = ? WHERE id = ?",
            ("pending_sell", oid2),
        )
        # 创建 1 条新字面量 open
        oid3 = create_pending_order(
            user_id=admin_id, stock_code=f"{unique_prefix}C", stock_name="C", shares=100,
        )["id"]
        # status='open' 查询应包含这 3 条(老字面量被兼容)
        all_open = query_all(
            "SELECT id, stock_code FROM t1_pending_orders WHERE user_id = ? AND status IN ('open', 'pending_buy', 'pending_sell')",
            (admin_id,),
        )
        open_ids = {o["id"] for o in all_open}
        assert oid1 in open_ids
        assert oid2 in open_ids
        assert oid3 in open_ids
        # 用 get_user_orders 也应返回
        orders = get_user_orders(admin_id, status="open")
        returned_ids = {o["id"] for o in orders}
        assert oid1 in returned_ids
        assert oid2 in returned_ids
        assert oid3 in returned_ids

    def test_summarize_pnl_groups_legacy(self, db):
        """summarize_user_pnl 把老字面量聚合到新名字 by_status key"""
        from database import execute
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        # 创建 2 条老字面量 pending_buy + 1 条新字面量 open
        for code in ["000010", "000011"]:
            oid = create_pending_order(
                user_id=admin_id, stock_code=code, stock_name="X", shares=100,
            )["id"]
            execute(
                "UPDATE t1_pending_orders SET status = ? WHERE id = ?",
                ("pending_buy", oid),
            )
        oid = create_pending_order(
            user_id=admin_id, stock_code="000012", stock_name="X", shares=100,
        )["id"]
        # 默认就是 open
        summary = t1_watcher.summarize_user_pnl(admin_id, days=7)
        # by_status 应只有 'open' 一个 key(老字面量被归一化)
        assert "open" in summary["by_status"]
        # 老字面量 'pending_buy' 不应独立成 key(核心: 归一化生效)
        assert "pending_buy" not in summary["by_status"]
        assert "pending_sell" not in summary["by_status"]
        assert "bought" not in summary["by_status"]
        # count >= 3(测试 DB 可能有残留订单, 用 >= 检查)
        assert summary["by_status"]["open"]["count"] >= 3


# ═══════════════════════════════════════════════════════════════
#  partial_filled 字段读写
# ═══════════════════════════════════════════════════════════════


class TestPartialFilledFields:
    def _make_order(self, db):
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        return create_pending_order(
            user_id=admin_id, stock_code="000001", stock_name="P", shares=100,
        )["id"]

    def test_partial_filled_persisted(self, db):
        """partial_filled 状态 filled_shares / pending_shares 字段持久化"""
        oid = self._make_order(db)
        transition(
            order_id=oid, target=STATUS_PARTIAL_FILLED,
            actor="bulk_approve", event_type="partial_filled",
            filled_shares=60, pending_shares=40,
            metadata={"available_cash": 6000.0, "requested_total": 10000.0},
        )
        # 重新查
        order = get_order_by_id(oid)
        assert order["status"] == STATUS_PARTIAL_FILLED
        assert order["filled_shares"] == 60
        assert order["pending_shares"] == 40

    def test_default_filled_shares_zero(self, db):
        """未 partial_filled 时 filled_shares = 0(default)"""
        oid = self._make_order(db)
        order = get_order_by_id(oid)
        assert order["filled_shares"] == 0
        assert order["pending_shares"] is None  # 没设过 = NULL