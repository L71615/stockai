"""v5.2.2 — delete holding 同时删除 transactions 测试

覆盖:
  1. 删除 holding → transactions 也被清空
  2. 删除后 AI 录入不会和历史合并
"""
from __future__ import annotations

import os
import sys
import sqlite3
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """临时 DB — 模拟'之前有 500 股 + 现在加 200 股'场景"""
    db_path = tmp_path / "test_delete.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT, email TEXT, password TEXT
        );
        CREATE TABLE holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT, market TEXT,
            asset_type TEXT DEFAULT '',
            quantity INTEGER NOT NULL, cost_price REAL NOT NULL,
            shares REAL,
            portfolio_id INTEGER,
            journal TEXT DEFAULT '',
            stop_loss_price REAL, take_profit_price REAL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL, stock_name TEXT,
            asset_type TEXT DEFAULT '',
            direction TEXT NOT NULL,
            price REAL NOT NULL, quantity INTEGER NOT NULL,
            amount REAL NOT NULL, fee REAL DEFAULT 0,
            traded_at TEXT NOT NULL, note TEXT,
            stop_loss_price REAL, stop_loss_triggered INTEGER DEFAULT 0,
            stop_loss_triggered_at TEXT, planned_exit_price REAL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO users VALUES (1, 'admin', 'admin@test.com', 'x');
        INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price)
        VALUES (1, '002747', '埃斯顿', 'SZ', 'stock', 500, 34.886);
        INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction,
                                   price, quantity, amount, fee, traded_at)
        VALUES (1, '002747', '埃斯顿', 'stock', 'buy', 34.886, 500, 17443, 13, '2026-08-05');
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


def test_delete_holding_removes_transactions(fresh_db, monkeypatch):
    """核心场景: 删 holding → transactions 也清空"""
    from routers.holdings import delete_holding
    from database import query_all
    from dependencies import get_current_user_id

    monkeypatch.setattr("dependencies.get_current_user_id", lambda: 1)

    # 验证前置状态: holdings 有 1 行, transactions 有 1 行
    holdings_before = query_all("SELECT * FROM holdings WHERE stock_code = '002747'")
    tx_before = query_all("SELECT * FROM transactions WHERE stock_code = '002747'")
    assert len(holdings_before) == 1
    assert len(tx_before) == 1

    # 删除 holding (id=1)
    result = delete_holding(1)
    assert result["message"] == "已删除"
    assert result["stock_code"] == "002747"

    # 验证后置状态: 都没了
    holdings_after = query_all("SELECT * FROM holdings WHERE stock_code = '002747'")
    tx_after = query_all("SELECT * FROM transactions WHERE stock_code = '002747'")
    assert len(holdings_after) == 0
    assert len(tx_after) == 0


def test_delete_then_ai_record_no_merge(fresh_db, monkeypatch):
    """场景: 删完 → AI 录入 200 股 → 应该是 200 不是 700"""
    from routers.holdings import delete_holding
    from routers.transactions import add_transactions_bulk, BulkTransactionRequest
    from database import query_all
    from dependencies import get_current_user_id

    monkeypatch.setattr("dependencies.get_current_user_id", lambda: 1)

    # 1. 删 002747
    delete_holding(1)

    # 2. AI 录入 200 股 002747
    req = BulkTransactionRequest(**{
        "transactions": [
            {"stock_code": "002747", "direction": "buy",
             "quantity": 200, "price": 34.61, "traded_at": "2026-08-06"},
        ],
    })
    add_transactions_bulk(req)

    # 3. 验证: quantity 应该是 200(不是 500 + 200 = 700)
    h = query_all("SELECT * FROM holdings WHERE stock_code = '002747'")
    assert len(h) == 1, f"应该有 1 行 holding, 实际 {len(h)}"
    assert h[0]["quantity"] == 200, f"quantity 应该是 200, 实际 {h[0]['quantity']}"

    # transactions 也只有 1 行(新的)
    txs = query_all("SELECT * FROM transactions WHERE stock_code = '002747'")
    assert len(txs) == 1
    assert txs[0]["quantity"] == 200


def test_delete_404_if_not_owned(fresh_db, monkeypatch):
    """不属于自己的 holding → 404"""
    from routers.holdings import delete_holding
    from fastapi import HTTPException

    monkeypatch.setattr("dependencies.get_current_user_id", lambda: 1)

    with pytest.raises(HTTPException) as exc:
        delete_holding(999)
    assert exc.value.status_code == 404


def test_delete_only_affects_target_stock(fresh_db, monkeypatch):
    """删除 002747 时不影响其他股票的交易"""
    from routers.holdings import delete_holding
    from database import query_one, execute
    from dependencies import get_current_user_id

    monkeypatch.setattr("dependencies.get_current_user_id", lambda: 1)

    # 加一只别的股票的交易
    execute(
        "INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, fee, traded_at) "
        "VALUES (1, '600519', '贵州茅台', 'stock', 'buy', 1680, 100, 168000, 42, '2026-08-01')"
    )

    # 删除 002747
    delete_holding(1)

    # 002747 全清, 600519 不动
    assert query_one("SELECT COUNT(*) AS n FROM holdings WHERE stock_code = '002747'")["n"] == 0
    assert query_one("SELECT COUNT(*) AS n FROM transactions WHERE stock_code = '002747'")["n"] == 0
    assert query_one("SELECT COUNT(*) AS n FROM transactions WHERE stock_code = '600519'")["n"] == 1