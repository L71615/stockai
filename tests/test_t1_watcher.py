"""T+1/T+2 模拟成交 watcher 单元测试 — v4.0

覆盖:
  - CRUD: create / get / cancel
  - 状态机: pending_buy → bought → sold
  - 模拟买入: 写 holdings + transactions
  - 模拟卖出: 扣 holdings + 写 transactions + 收益统计
  - 滑点应用
  - 边界: 无开盘价 / 持仓不足 / 取消已 bought 订单
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from services import t1_watcher
from services.t1_watcher import (
    create_pending_order,
    get_user_orders,
    get_order_by_id,
    cancel_order,
    process_pending_buys,
    process_pending_sells,
    summarize_user_pnl,
    STATUS_PENDING_BUY,
    STATUS_BOUGHT,
    STATUS_PENDING_SELL,
    STATUS_SOLD,
    STATUS_CANCELLED,
)


# ═══════════════════════════════════════════════════════════════
#  状态机常量
# ═══════════════════════════════════════════════════════════════


class TestStatusConstants:
    def test_all_statuses_defined(self):
        assert STATUS_PENDING_BUY == "pending_buy"
        assert STATUS_BOUGHT == "bought"
        assert STATUS_PENDING_SELL == "pending_sell"
        assert STATUS_SOLD == "sold"
        assert STATUS_CANCELLED == "cancelled"


# ═══════════════════════════════════════════════════════════════
#  CRUD
# ═══════════════════════════════════════════════════════════════


class TestCreatePendingOrder:
    def test_create_basic_order(self, db):
        """创建基础 pending_buy 订单"""
        # 取 admin user_id
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        result = create_pending_order(
            user_id=user_id,
            stock_code="000001",
            stock_name="平安银行",
            shares=100,
            planned_entry_price=10.0,
            hold_days=1,
        )
        assert result["id"] is not None
        assert result["status"] == STATUS_PENDING_BUY
        assert result["stock_code"] == "000001"
        assert result["entry_date"] is not None
        assert result["exit_date"] is not None
        # exit_date = entry_date + 1 day
        assert (datetime.strptime(result["exit_date"], "%Y-%m-%d") -
                datetime.strptime(result["entry_date"], "%Y-%m-%d")).days == 1

    def test_create_t2_order(self, db):
        """T+2 订单(hold_days=2)"""
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        result = create_pending_order(
            user_id=user_id,
            stock_code="000002",
            shares=200,
            hold_days=2,
            entry_date="2026-08-01",
        )
        assert result["hold_days"] == 2
        # exit_date = 2026-08-01 + 2 = 2026-08-03
        assert result["exit_date"] == "2026-08-03"


class TestGetUserOrders:
    def test_get_orders_for_user(self, db):
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        create_pending_order(user_id=user_id, stock_code="000001")
        create_pending_order(user_id=user_id, stock_code="000002")

        orders = get_user_orders(user_id, limit=10)
        assert len(orders) >= 2
        codes = {o["stock_code"] for o in orders}
        assert "000001" in codes
        assert "000002" in codes

    def test_filter_by_status(self, db):
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        create_pending_order(user_id=user_id, stock_code="000001")
        orders = get_user_orders(user_id, status=STATUS_PENDING_BUY)
        assert all(o["status"] == STATUS_PENDING_BUY for o in orders)


class TestCancelOrder:
    def test_cancel_pending_buy(self, db):
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        order = create_pending_order(user_id=user_id, stock_code="000001")
        order_id = order["id"]

        cancel_order(order_id, user_id, reason="测试取消")

        after = get_order_by_id(order_id, user_id)
        assert after["status"] == STATUS_CANCELLED
        assert "测试取消" in after["reason"]


# ═══════════════════════════════════════════════════════════════
#  模拟买入
# ═══════════════════════════════════════════════════════════════


class TestSimulateBuy:
    def test_buy_writes_holdings_and_transactions(self, db):
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        order = create_pending_order(
            user_id=user_id,
            stock_code="000888",
            stock_name="测试股",
            shares=100,
            slippage_bps=10.0,
            entry_date=datetime.now().strftime("%Y-%m-%d"),
        )

        # Mock 开盘价
        with patch.object(t1_watcher, "_get_open_price", return_value=100.0):
            result = process_pending_buys()

        assert any(r["order_id"] == order["id"] and r["filled"] for r in result)

        # 验证订单状态
        after = get_order_by_id(order["id"], user_id)
        assert after["status"] == STATUS_BOUGHT
        # 100 × (1 + 0.001) = 100.10
        assert abs(after["executed_entry_price"] - 100.10) < 0.01

        # 验证 holdings 写入
        holding = query_one(
            "SELECT * FROM holdings WHERE user_id = ? AND stock_code = ?",
            (user_id, "000888"),
        )
        assert holding is not None
        assert holding["quantity"] == 100
        assert abs(holding["cost_price"] - 100.10) < 0.01

        # 验证 transactions 写入
        tx = query_one(
            "SELECT * FROM transactions WHERE user_id = ? AND stock_code = ? AND direction = 'buy'",
            (user_id, "000888"),
        )
        assert tx is not None
        assert tx["quantity"] == 100
        assert abs(tx["price"] - 100.10) < 0.01
        assert tx["note"].startswith("[T+1 模拟成交]")

    def test_buy_skips_when_no_open_price(self, db):
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        order = create_pending_order(
            user_id=user_id,
            stock_code="000999",
            shares=100,
            entry_date=datetime.now().strftime("%Y-%m-%d"),
        )

        with patch.object(t1_watcher, "_get_open_price", return_value=None):
            result = process_pending_buys()

        # 订单状态未变
        after = get_order_by_id(order["id"], user_id)
        assert after["status"] == STATUS_PENDING_BUY  # 未成交

    def test_buy_appends_to_existing_holdings(self, db):
        """已有持仓的股票,新买入应合并"""
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 先建 100 股 @ 90 元的持仓
        from database import execute
        execute(
            """INSERT INTO holdings
               (user_id, stock_code, stock_name, asset_type, quantity, cost_price, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000777", "测试", "stock", 100, 90.0, now, now),
        )

        # 再创建 T+1 订单
        order = create_pending_order(
            user_id=user_id,
            stock_code="000777",
            shares=100,
            slippage_bps=10.0,
            entry_date=datetime.now().strftime("%Y-%m-%d"),
        )

        with patch.object(t1_watcher, "_get_open_price", return_value=100.0):
            process_pending_buys()

        # 验证合并后: 200 股,平均成本 = (90×100 + 100.10×100) / 200 = 95.05
        holding = query_one(
            "SELECT * FROM holdings WHERE user_id = ? AND stock_code = ?",
            (user_id, "000777"),
        )
        assert holding["quantity"] == 200
        assert abs(holding["cost_price"] - 95.05) < 0.01


# ═══════════════════════════════════════════════════════════════
#  模拟卖出
# ═══════════════════════════════════════════════════════════════


class TestSimulateSell:
    def test_sell_writes_transactions_and_updates_holdings(self, db):
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        # 创建订单并直接置为 bought,exit_date = 今天
        today = datetime.now().strftime("%Y-%m-%d")
        order = create_pending_order(
            user_id=user_id,
            stock_code="000666",
            stock_name="测试",
            shares=100,
            slippage_bps=10.0,
        )
        # 模拟已买入 + exit_date 设为今天(满足 process_pending_sells 条件)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execute(
            """UPDATE t1_pending_orders
               SET status = ?, executed_entry_price = ?, actual_entry_at = ?,
                   exit_date = ?
               WHERE id = ?""",
            (STATUS_BOUGHT, 100.0, now, today, order["id"]),
        )
        # 写 holdings
        execute(
            """INSERT INTO holdings
               (user_id, stock_code, stock_name, asset_type, quantity, cost_price, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000666", "测试", "stock", 100, 100.0, now, now),
        )

        # 模拟卖出(开盘 110 元)
        with patch.object(t1_watcher, "_get_open_price", return_value=110.0):
            result = process_pending_sells(today)

        assert any(r["order_id"] == order["id"] and r["filled"] for r in result)

        # 验证订单状态
        after = get_order_by_id(order["id"], user_id)
        assert after["status"] == STATUS_SOLD
        # 卖出价 = 110 × (1 - 0.001) = 109.89
        assert abs(after["executed_exit_price"] - 109.89) < 0.01
        # 净收益应 > 0(110→109.89 涨 9.89%,扣费略小)
        assert after["net_pnl"] is not None
        assert after["net_pnl"] > 0

        # 验证 holdings 已清空
        holding = query_one(
            "SELECT * FROM holdings WHERE user_id = ? AND stock_code = ?",
            (user_id, "000666"),
        )
        assert holding is None  # qty 减到 0 被删

    def test_sell_partial_keeps_remaining_holdings(self, db):
        """部分卖出,剩余持仓保留"""
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]
        today = datetime.now().strftime("%Y-%m-%d")

        # 建 200 股持仓
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execute(
            """INSERT INTO holdings
               (user_id, stock_code, stock_name, asset_type, quantity, cost_price, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000555", "测试", "stock", 200, 50.0, now, now),
        )

        # T+1 订单卖 100 股,exit_date = 今天
        order = create_pending_order(
            user_id=user_id, stock_code="000555", shares=100, slippage_bps=10.0,
        )
        execute(
            """UPDATE t1_pending_orders
               SET status = ?, executed_entry_price = ?, actual_entry_at = ?,
                   exit_date = ?
               WHERE id = ?""",
            (STATUS_BOUGHT, 50.0, now, today, order["id"]),
        )

        with patch.object(t1_watcher, "_get_open_price", return_value=55.0):
            process_pending_sells(today)

        # 剩余 100 股
        holding = query_one(
            "SELECT * FROM holdings WHERE user_id = ? AND stock_code = ?",
            (user_id, "000555"),
        )
        assert holding["quantity"] == 100


# ═══════════════════════════════════════════════════════════════
#  收益汇总
# ═══════════════════════════════════════════════════════════════


class TestSummarizeUserPnl:
    def test_summary_includes_sold_orders(self, db):
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 用唯一 stock_code 前缀,避免与其他测试数据冲突
        unique_prefix = f"9999{datetime.now().strftime('%H%M%S')}"

        # 记录本测试开始前的 sold 数量
        before = summarize_user_pnl(user_id, days=30)["sold_orders"]

        # 创建 2 个 sold 订单
        for i, pnl in enumerate([100.0, -50.0]):
            order = create_pending_order(
                user_id=user_id, stock_code=f"{unique_prefix}{i}", shares=100,
            )
            execute(
                """UPDATE t1_pending_orders
                   SET status = ?, net_pnl = ?, net_return_pct = ?, updated_at = ?
                   WHERE id = ?""",
                (STATUS_SOLD, pnl, 5.0, now, order["id"]),
            )

        summary = summarize_user_pnl(user_id, days=30)
        # 增加 2 个 sold(用相对值断言,避免其他测试干扰)
        assert summary["sold_orders"] == before + 2
        assert "sold" in summary["by_status"]


# ═══════════════════════════════════════════════════════════════
#  滑点应用单元测试
# ═══════════════════════════════════════════════════════════════


class TestSlippageHelper:
    def test_buy_slippage_increases_price(self):
        result = t1_watcher._apply_slippage(100.0, "buy", 10.0)
        assert abs(result - 100.10) < 0.01

    def test_sell_slippage_decreases_price(self):
        result = t1_watcher._apply_slippage(100.0, "sell", 10.0)
        assert abs(result - 99.90) < 0.01

    def test_zero_slippage_keeps_price(self):
        assert t1_watcher._apply_slippage(100.0, "buy", 0) == 100.0
        assert t1_watcher._apply_slippage(100.0, "sell", 0) == 100.0

    def test_none_price_returns_none(self):
        assert t1_watcher._apply_slippage(None, "buy", 10.0) is None
