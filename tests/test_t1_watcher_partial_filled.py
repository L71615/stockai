"""t1_watcher partial_filled 完整处理测试 — v4.2.3 (patch 阶段)

覆盖:
  - _simulate_buy(partial_shares=N) 走 STATUS_PARTIAL_FILLED 状态
  - filled_shares/pending_shares 字段正确写入
  - process_pending_buys 扫 partial_filled 状态做补成交
  - 补成交后 filled_shares 累加 + pending_shares 归 0 → 推到 STATUS_FILLED
  - try_fill_pending_order() helper
  - get_user_orders / summarize_user_pnl 包含 partial_filled 状态
  - 风控/通知/审计 路径
"""
import pytest

from services.t1_watcher import (
    STATUS_OPEN, STATUS_PARTIAL_FILLED, STATUS_FILLED,
    STATUS_CLOSED, STATUS_CANCELLED, STATUS_REJECTED,
    create_pending_order, transition, get_user_orders, get_order_by_id,
    summarize_user_pnl, _simulate_buy, try_fill_pending_order,
    _ALLOWED_TRANSITIONS,
)


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def admin_id(db):
    row = db.execute("SELECT id FROM users LIMIT 1").fetchone()
    return dict(row)["id"]


@pytest.fixture
def make_order(db):
    """工厂: 创建一条 T+1 pending_buy 订单"""
    def _make(shares: int = 100, entry_date: str = "2026-08-04", hold_days: int = 1):
        admin_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        return create_pending_order(
            user_id=admin_id, stock_code="000001", stock_name="P",
            shares=shares, entry_date=entry_date, hold_days=hold_days,
        )
    return _make


# ═══════════════════════════════════════════════════════════════
#  _simulate_buy partial_shares → partial_filled 状态
# ═══════════════════════════════════════════════════════════════


class TestSimulateBuyPartial:
    def test_partial_filled_with_partial_shares(self, make_order):
        """_simulate_buy(partial_shares=30) → status=partial_filled, filled=30/pending=70"""
        order = make_order(shares=100)
        result = _simulate_buy(order, open_price=10.0, partial_shares=30)
        assert result["is_partial"] is True
        assert result["status"] == STATUS_PARTIAL_FILLED
        assert result["filled_shares"] == 30
        assert result["pending_shares"] == 70

        # 订单 DB 状态同步
        updated = get_order_by_id(order["id"])
        assert updated["status"] == STATUS_PARTIAL_FILLED
        assert updated["filled_shares"] == 30
        assert updated["pending_shares"] == 70

    def test_full_fill_no_partial_shares_arg(self, make_order):
        """_simulate_buy() 默认全部成交 → filled"""
        order = make_order(shares=100)
        result = _simulate_buy(order, open_price=10.0)
        assert result["is_partial"] is False
        assert result["status"] == STATUS_FILLED
        assert result["filled_shares"] == 100
        assert result["pending_shares"] == 0

    def test_partial_shares_zero_is_noop(self, make_order):
        """partial_shares=0 → 实际成交 0 股, 视为部分成交 (剩余 requested 全未成交)"""
        order = make_order(shares=100)
        # partial_shares=0 → actual_shares=0 → is_partial=True (剩余 100)
        result = _simulate_buy(order, open_price=10.0, partial_shares=0)
        assert result["filled_shares"] == 0
        assert result["status"] == STATUS_PARTIAL_FILLED
        assert result["pending_shares"] == 100

    def test_partial_shares_capped_at_requested(self, make_order):
        """partial_shares > requested_shares → 截断到 requested"""
        order = make_order(shares=100)
        result = _simulate_buy(order, open_price=10.0, partial_shares=150)
        # 实际成交 100 = 全部, 走 filled
        assert result["status"] == STATUS_FILLED
        assert result["filled_shares"] == 100
        assert result["is_partial"] is False

    def test_partial_filled_creates_holdings_with_actual_shares(self, make_order):
        """partial_filled 时 holdings.quantity 只加 actual_shares, 不是 requested_shares"""
        # 避免与其他测试的 holdings 残留冲突, 用唯一 stock_code
        from database import query_one, execute
        admin_id = query_one("SELECT id FROM users LIMIT 1")["id"]
        execute(
            "DELETE FROM holdings WHERE user_id = ? AND stock_code = ?",
            (admin_id, "888888"),
        )
        order = create_pending_order(
            user_id=admin_id, stock_code="888888", stock_name="P",
            shares=100,
        )
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        holding = query_one(
            "SELECT quantity, cost_price FROM holdings "
            "WHERE user_id = ? AND stock_code = ?",
            (order["user_id"], "888888"),
        )
        assert holding["quantity"] == 30.0
        assert abs(holding["cost_price"] - 10.0) < 0.01

    def test_partial_filled_creates_transaction_with_actual_shares(self, make_order):
        """partial_filled 时 transaction.quantity = actual_shares"""
        order = make_order(shares=100)
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        from database import query_one
        txn = query_one(
            "SELECT quantity, amount FROM transactions "
            "WHERE user_id = ? AND stock_code = ? AND direction = 'buy' "
            "ORDER BY id DESC LIMIT 1",
            (order["user_id"], "000001"),
        )
        assert txn["quantity"] == 30


# ═══════════════════════════════════════════════════════════════
#  try_fill_pending_order 补成交
# ═══════════════════════════════════════════════════════════════


class TestTryFillPendingOrder:
    def test_partial_filled_can_fill_remainder(self, make_order):
        """try_fill_pending_order 把 partial_filled 补到 filled"""
        order = make_order(shares=100)
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        # 此时 order 是 partial_filled, pending=70
        partial_order = get_order_by_id(order["id"])
        assert partial_order["status"] == STATUS_PARTIAL_FILLED
        assert partial_order["pending_shares"] == 70

        # 补成交
        result = try_fill_pending_order(order["id"], open_price=10.5)
        assert result is not None
        assert result["status"] == STATUS_FILLED
        assert result["is_partial"] is False
        assert result["filled_shares"] == 70  # 本次补成交 70

        # 最终订单: filled=100, pending=0, status=filled
        final = get_order_by_id(order["id"])
        assert final["status"] == STATUS_FILLED
        assert final["filled_shares"] == 100
        assert final["pending_shares"] == 0

    def test_partial_filled_can_fill_partial_again(self, make_order):
        """partial_filled 补一半 → 仍是 partial_filled"""
        order = make_order(shares=100)
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        # 补 40 (pending 还剩 30)
        result = try_fill_pending_order(order["id"], open_price=10.5, partial_shares=40)
        assert result["status"] == STATUS_PARTIAL_FILLED
        assert result["is_partial"] is True
        assert result["filled_shares"] == 40  # 本次补成交 40
        assert result["pending_shares"] == 30  # 剩 30

        # 订单: filled=70, pending=30
        final = get_order_by_id(order["id"])
        assert final["status"] == STATUS_PARTIAL_FILLED
        assert final["filled_shares"] == 70
        assert final["pending_shares"] == 30

    def test_try_fill_on_open_status_returns_none(self, make_order):
        """open 状态的订单调 try_fill → None (应该走 process_pending_buys)"""
        order = make_order(shares=100)
        # 不 _simulate_buy, 订单还是 open
        result = try_fill_pending_order(order["id"], open_price=10.0)
        assert result is None

    def test_try_fill_nonexistent_returns_none(self):
        result = try_fill_pending_order(999999, open_price=10.0)
        assert result is None

    def test_try_fill_with_zero_partial_returns_none(self, make_order):
        """partial_shares=0 → None (无操作)"""
        order = make_order(shares=100)
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        result = try_fill_pending_order(order["id"], open_price=10.5, partial_shares=0)
        assert result is None


# ═══════════════════════════════════════════════════════════════
#  process_pending_buys 扫 partial_filled
# ═══════════════════════════════════════════════════════════════


class TestProcessPendingBuysPartialFill:
    def test_process_pending_buys_scans_partial_filled(self, make_order, monkeypatch):
        """process_pending_buys 应该扫到 partial_filled 状态做补成交"""
        # mock 风控绕过仓位检查 (避免前置 holdings 干扰)
        from services import t1_watcher
        monkeypatch.setattr(
            t1_watcher, "_evaluate_buy_risk",
            lambda uid, code, val: {"action": "allow", "reason": "mocked_ok"},
        )
        monkeypatch.setattr(
            t1_watcher, "_get_open_price",
            lambda code, date: 10.5,
        )
        monkeypatch.setattr(t1_watcher, "_apply_slippage", lambda price, side, bps: price)

        order = make_order(shares=100, entry_date="2026-08-04")
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        partial = get_order_by_id(order["id"])
        assert partial["status"] == STATUS_PARTIAL_FILLED

        from services.t1_watcher import process_pending_buys
        results = process_pending_buys(today="2026-08-04")

        matching = [r for r in results if r.get("order_id") == order["id"]]
        assert len(matching) == 1
        result = matching[0]
        assert result["filled"] is True
        # 这次补成交了 pending=70
        assert result["filled_shares"] == 70
        assert result["status"] == STATUS_FILLED

    def test_process_pending_buys_partial_with_zero_pending_finalizes(self, make_order, monkeypatch):
        """partial_filled 但 pending_shares=0 → 自动推到 filled"""
        from services import t1_watcher
        from database import execute
        monkeypatch.setattr(
            t1_watcher, "_evaluate_buy_risk",
            lambda uid, code, val: {"action": "allow", "reason": "mocked_ok"},
        )

        order = make_order(shares=100, entry_date="2026-08-04")
        # 手动把订单置成 partial_filled + pending_shares=0 (异常残留)
        execute(
            "UPDATE t1_pending_orders SET status = ?, filled_shares = ?, pending_shares = 0 WHERE id = ?",
            (STATUS_PARTIAL_FILLED, 100, order["id"]),
        )

        monkeypatch.setattr(
            t1_watcher, "_get_open_price",
            lambda code, date: 10.5,
        )

        from services.t1_watcher import process_pending_buys
        results = process_pending_buys(today="2026-08-04")

        matching = [r for r in results if r.get("order_id") == order["id"]]
        assert len(matching) == 1
        # 推到 filled
        final = get_order_by_id(order["id"])
        assert final["status"] == STATUS_FILLED


# ═══════════════════════════════════════════════════════════════
#  get_user_orders 包含 partial_filled
# ═══════════════════════════════════════════════════════════════


class TestGetUserOrdersPartialFilled:
    def test_status_partial_filled_filter_works(self, make_order):
        """status=partial_filled 查询应该返回该状态的订单"""
        order = make_order(shares=100)
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        orders = get_user_orders(order["user_id"], status=STATUS_PARTIAL_FILLED)
        codes = {o["stock_code"] for o in orders}
        assert "000001" in codes


# ═══════════════════════════════════════════════════════════════
#  summarize_user_pnl 包含 partial_filled
# ═══════════════════════════════════════════════════════════════


class TestSummarizeUserPnlPartialFilled:
    def test_partial_filled_appears_in_by_status(self, make_order):
        order = make_order(shares=100)
        _simulate_buy(order, open_price=10.0, partial_shares=30)

        summary = summarize_user_pnl(order["user_id"], days=7)
        assert "partial_filled" in summary["by_status"]
        assert summary["by_status"]["partial_filled"]["count"] >= 1


# ═══════════════════════════════════════════════════════════════
#  白名单: partial_filled 出度
# ═══════════════════════════════════════════════════════════════


class TestAllowedTransitionsPartialFilled:
    def test_partial_filled_can_go_to_filled(self):
        assert STATUS_FILLED in _ALLOWED_TRANSITIONS[STATUS_PARTIAL_FILLED]

    def test_partial_filled_can_go_to_open(self):
        """撤单重挂场景: partial_filled → open (剩余挂单撤单 + 重挂)"""
        assert STATUS_OPEN in _ALLOWED_TRANSITIONS[STATUS_PARTIAL_FILLED]

    def test_partial_filled_can_go_to_cancelled(self):
        assert STATUS_CANCELLED in _ALLOWED_TRANSITIONS[STATUS_PARTIAL_FILLED]

    def test_partial_filled_cannot_go_to_closed(self):
        """partial_filled 还没全部成交, 不能直接 close"""
        assert STATUS_CLOSED not in _ALLOWED_TRANSITIONS[STATUS_PARTIAL_FILLED]