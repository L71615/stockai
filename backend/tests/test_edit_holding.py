"""v5.2.2 — 编辑持仓测试(PUT endpoint)

覆盖:
  1. 修改数量 / 成本 — 持久化到 DB
  2. 修改组合 — 持久化
  3. 修改别人的 holding → 不动
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test_edit.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, username TEXT, email TEXT, password TEXT
        );
        CREATE TABLE holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL, stock_name TEXT,
            market TEXT, asset_type TEXT DEFAULT '',
            quantity INTEGER NOT NULL, cost_price REAL NOT NULL,
            shares REAL, portfolio_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'long',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO users VALUES (1, 'admin', 'admin@test.com', 'x');
        INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price)
        VALUES (1, '002747', '埃斯顿', 'SZ', 'stock', 500, 34.886);
        INSERT INTO portfolios (user_id, name) VALUES (1, '长线组合');
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr("database.DB_PATH", str(db_path))

    # reset pool
    try:
        import database as _db
        import queue as _q
        old_pool = _db._conn_pool
        _db._conn_pool = _q.Queue(maxsize=_db._POOL_SIZE)
        while not old_pool.empty():
            try:
                old_pool.get_nowait().close()
            except Exception:
                break
    except Exception:
        pass

    yield str(db_path)


def _build_body(**kwargs):
    """构造 HoldingBody 实例"""
    from routers.holdings import HoldingBody
    base = {
        "stock_code": "002747",
        "stock_name": "埃斯顿",
        "market": "SZ",
        "asset_type": "stock",
        "quantity": 500,
        "cost_price": 34.886,
        "shares": None,
        "portfolio_id": None,
        "fee": None,
    }
    base.update(kwargs)
    return HoldingBody(**base)


def test_update_quantity_and_cost(fresh_db, monkeypatch):
    """核心场景: 修改数量 + 成本价"""
    from routers.holdings import update_holding
    from database import query_one
    from dependencies import get_current_user_id

    monkeypatch.setattr("dependencies.get_current_user_id", lambda: 1)

    # 修改前
    h_before = query_one("SELECT * FROM holdings WHERE id = 1")
    assert h_before["quantity"] == 500
    assert h_before["cost_price"] == 34.886

    # 修改
    result = update_holding(1, _build_body(quantity=200, cost_price=34.61))
    assert result["message"] == "已更新"

    # 修改后
    h_after = query_one("SELECT * FROM holdings WHERE id = 1")
    assert h_after["quantity"] == 200
    assert abs(h_after["cost_price"] - 34.61) < 0.001


def test_update_portfolio(fresh_db, monkeypatch):
    """修改 portfolio_id"""
    from routers.holdings import update_holding
    from database import query_one
    from dependencies import get_current_user_id

    monkeypatch.setattr("dependencies.get_current_user_id", lambda: 1)

    result = update_holding(1, _build_body(portfolio_id=1))
    h_after = query_one("SELECT * FROM holdings WHERE id = 1")
    assert h_after["portfolio_id"] == 1


def test_update_other_users_holding_no_effect(fresh_db, monkeypatch):
    """不能改别人的持仓"""
    from routers.holdings import update_holding
    from database import query_all, query_one
    from dependencies import _current_user_id

    # 用 ContextVar 直接设当前用户为 99(不存在)
    token = _current_user_id.set(99)
    try:
        # 改之前
        h_before = query_one("SELECT * FROM holdings WHERE id = 1")
        assert h_before["quantity"] == 500

        # 用 user 99 改 → 应该不动(user_id 不匹配 WHERE)
        update_holding(1, _build_body(quantity=999))

        # 验证: 没改
        h_after = query_one("SELECT * FROM holdings WHERE id = 1")
        assert h_after["quantity"] == 500  # ← 没变
    finally:
        _current_user_id.reset(token)


def test_update_stock_name(fresh_db, monkeypatch):
    """改名称"""
    from routers.holdings import update_holding
    from database import query_one
    from dependencies import get_current_user_id

    monkeypatch.setattr("dependencies.get_current_user_id", lambda: 1)

    update_holding(1, _build_body(stock_name="埃斯顿(改名)"))
    h_after = query_one("SELECT * FROM holdings WHERE id = 1")
    assert h_after["stock_name"] == "埃斯顿(改名)"