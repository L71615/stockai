"""v5.1 — AI 解析交易 + 批量落库 测试

覆盖:
  1. parse_transactions_with_ai — 模板格式 CSV
  2. parse_transactions_with_ai — 自然语言混排
  3. parse_transactions_with_ai — 股票代码不存在 → 报错
  4. parse_transactions_with_ai — 卖出超持仓 → 报错
  5. add_transactions_bulk — 2 笔成功
  6. add_transactions_bulk — 部分失败回滚全部
"""
from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ── Fixtures ──


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """临时数据库 — 含 stocks / stock_info / holdings / transactions / users"""
    db_path = tmp_path / "test_ai_parse.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            phone TEXT, avatar_url TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            market TEXT,
            asset_type TEXT DEFAULT '',
            quantity INTEGER NOT NULL,
            cost_price REAL NOT NULL,
            shares REAL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            asset_type TEXT DEFAULT '',
            direction TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            amount REAL NOT NULL,
            fee REAL DEFAULT 0,
            traded_at TEXT NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE stock_info (
            stock_code TEXT PRIMARY KEY,
            name TEXT,
            industry TEXT,
            list_date TEXT
        );
        INSERT INTO users (id, username, email, password)
        VALUES (1, 'admin', 'admin@test.com', 'x');
        -- 已存在股票 (与 production 一致: 用 stock_info 表)
        INSERT INTO stock_info VALUES ('600519', '贵州茅台', '白酒', NULL);
        INSERT INTO stock_info VALUES ('000725', '京东方A', '面板', NULL);
        INSERT INTO stock_info VALUES ('000001', '平安银行', '银行', NULL);
        -- 用户已持有 000725 共 300 股
        INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price)
        VALUES (1, '000725', '京东方A', 'SZ', 'stock', 300, 4.0);
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr("database.DB_PATH", str(db_path))

    # 重置连接池
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


@pytest.fixture
def mock_ai_parser(monkeypatch):
    """mock AI 解析 — 默认返 [{...成功}, {...成功}]"""
    async def _mock(text, system):
        # 简单 CSV 解析(测试用, 不调真实 AI)
        results = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("代码"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            code, direction, qty, price, date = parts[:5]
            # 方向归一化
            d = "buy" if direction in ("买入", "buy", "Buy", "BUY", "买了") else "sell"
            results.append({
                "code": code,
                "direction": d,
                "quantity": int(qty),
                "price": float(price),
                "date": date,
            })
        return results

    monkeypatch.setattr(
        "services.ai_parse_transactions._call_ai_parse",
        _mock,
    )
    return _mock


# ── 测试 ──


@pytest.mark.asyncio
async def test_parse_template_csv(fresh_db, mock_ai_parser):
    """测试 1: 模板格式 CSV → 解析成功"""
    from services.ai_parse_transactions import parse_transactions_with_ai

    text = """代码,方向,数量,价格,日期
600519,买入,100,1680.00,2026-08-06
000725,卖出,200,4.20,2026-08-06"""

    result = await parse_transactions_with_ai(text, user_id=1)

    assert len(result["transactions"]) == 2
    assert result["summary"]["parsed_ok"] == 2
    assert result["summary"]["validation_failed"] == 0

    tx0 = result["transactions"][0]
    assert tx0["code"] == "600519"
    assert tx0["direction"] == "buy"
    assert tx0["quantity"] == 100
    assert tx0["price"] == 1680.0


@pytest.mark.asyncio
async def test_parse_template_with_mixed_lines(fresh_db, mock_ai_parser):
    """测试 2: CSV 模板 + 注释行 + 空行 混合 → mock AI 解析出有效行"""
    from services.ai_parse_transactions import parse_transactions_with_ai

    text = """# 8 月 6 日交易记录
# 注释行自动跳过

600519,买入,100,1680.00,2026-08-06

000725,卖出,200,4.20,2026-08-06
# 另一行注释
000001,买入,500,12.50,2026-08-06"""

    result = await parse_transactions_with_ai(text, user_id=1)

    # 3 笔有效 (空行/注释/表头已过滤)
    assert len(result["transactions"]) == 3
    assert result["summary"]["parsed_ok"] == 3
    # 第二笔是卖出 000725 200股, 当前持仓 300, 不超 → OK
    codes = [t["code"] for t in result["transactions"]]
    assert codes == ["600519", "000725", "000001"]


@pytest.mark.asyncio
async def test_parse_invalid_stock_code(fresh_db, mock_ai_parser):
    """测试 3: 股票代码不存在 → 报错"""
    from services.ai_parse_transactions import parse_transactions_with_ai

    text = """999999,买入,100,10.00,2026-08-06"""

    result = await parse_transactions_with_ai(text, user_id=1)

    assert len(result["transactions"]) == 0
    assert len(result["errors"]) == 1
    assert "999999" in result["errors"][0]["raw"]
    assert "不存在" in result["errors"][0]["reason"]


@pytest.mark.asyncio
async def test_parse_sell_exceeds_holding(fresh_db, mock_ai_parser):
    """测试 4: 卖出超过持仓(300) → 报错"""
    from services.ai_parse_transactions import parse_transactions_with_ai

    text = """000725,卖出,500,4.20,2026-08-06"""

    result = await parse_transactions_with_ai(text, user_id=1)

    assert len(result["transactions"]) == 0
    assert len(result["errors"]) == 1
    assert "000725" in result["errors"][0]["raw"]
    assert "超过当前持仓" in result["errors"][0]["reason"]
    assert "300" in result["errors"][0]["reason"]


def test_bulk_two_transactions(fresh_db):
    """测试 5: 批量落库 2 笔 → 全部成功 + 自动创建 holdings"""
    from routers.transactions import add_transactions_bulk, BulkTransactionRequest

    monkey = pytest.MonkeyPatch()
    monkey.setattr("dependencies.get_current_user_id", lambda: 1)

    body = BulkTransactionRequest(**{
        "transactions": [
            {"stock_code": "600519", "direction": "buy",
             "quantity": 100, "price": 1680.0, "traded_at": "2026-08-06"},
            {"stock_code": "000001", "direction": "buy",
             "quantity": 500, "price": 12.5, "traded_at": "2026-08-06"},
        ],
    })

    result = add_transactions_bulk(body)
    monkey.undo()

    assert result["message"] == "成功入库 2 笔"
    assert len(result["inserted"]) == 2
    assert "600519" in result["holding_updates"]
    assert "000001" in result["holding_updates"]


def test_bulk_partial_failure_rollback(fresh_db):
    """测试 6: 部分失败(卖出超持仓) → 全部回滚"""
    from routers.transactions import add_transactions_bulk, BulkTransactionRequest
    from dependencies import get_current_user_id

    monkey = pytest.MonkeyPatch()
    monkey.setattr("dependencies.get_current_user_id", lambda: 1)

    # 第一笔合法, 第二笔卖出 000725 1000 股 (持仓只有 300)
    body = BulkTransactionRequest(**{
        "transactions": [
            {"stock_code": "600519", "direction": "buy",
             "quantity": 100, "price": 1680.0, "traded_at": "2026-08-06"},
            {"stock_code": "000725", "direction": "sell",
             "quantity": 1000, "price": 4.20, "traded_at": "2026-08-06"},
        ],
    })

    with pytest.raises(Exception) as exc_info:
        add_transactions_bulk(body)
    assert "超过" in str(exc_info.value) or "1000" in str(exc_info.value)

    monkey.undo()

    # 验证 transactions 表为空(全部回滚)
    from database import query_all
    txs = query_all("SELECT * FROM transactions WHERE user_id = 1")
    assert len(txs) == 0, f"应全部回滚, 但仍有 {len(txs)} 笔"