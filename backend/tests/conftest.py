"""pytest 配置 + 共用 fixtures

v5.0-beta M6: 测试基础设施
"""
import os
import sys
import pytest

# 确保 backend/ 在 sys.path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(autouse=True)
def fresh_env(monkeypatch):
    """每个测试自动清空 REALTIME_USE_MINUTE_BARS 等 M6 相关环境变量"""
    for var in ("REALTIME_USE_MINUTE_BARS",):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """临时 SQLite 数据库,futu_raw_kline + historical_kline 两表

    Schema 与 production 对齐:
    - futu_raw_kline (含 created_at + uq_futu_raw_kline_bar 唯一索引 + 二级索引) — 见 backend/database.py:443-466
    - historical_kline (PK(stock_code, trade_date),无 id) — 见 database/schema.sql:109-118
    """
    import sqlite3
    db_path = tmp_path / "test_minute_bars.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        -- futu_raw_kline: 与 backend/database.py:443-466 production schema 对齐
        -- 含 created_at / updated_at / adjust_type 默认 'qfq' / source 默认 'futu' / raw_payload 默认 '{}'
        CREATE TABLE futu_raw_kline (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL,
            market      TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            interval    TEXT NOT NULL,
            bar_time    TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      REAL,
            turnover    REAL,
            adjust_type TEXT NOT NULL DEFAULT 'qfq',
            source      TEXT NOT NULL DEFAULT 'futu',
            raw_payload TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );
        -- 与 production 一致:uq 防止重复插入,二级索引加速按 symbol+interval+time 查询
        CREATE UNIQUE INDEX uq_futu_raw_kline_bar
            ON futu_raw_kline(symbol, interval, bar_time, adjust_type);
        CREATE INDEX idx_futu_raw_kline_symbol_interval_time
            ON futu_raw_kline(symbol, interval, bar_time DESC);

        -- historical_kline: 与 database/schema.sql:109-118 production schema 对齐
        -- 使用复合主键 (stock_code, trade_date),无 id 列
        CREATE TABLE historical_kline (
            stock_code  TEXT    NOT NULL,
            trade_date  TEXT    NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      REAL,
            PRIMARY KEY (stock_code, trade_date)
        );

        CREATE TABLE minute_factor_cache (
            stock_code TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            value REAL,
            ts REAL NOT NULL,
            PRIMARY KEY (stock_code, factor_name)
        );
    """)
    conn.commit()
    conn.close()

    # monkeypatch database.py 的 DB_PATH 指向临时 DB
    monkeypatch.setattr("database.DB_PATH", str(db_path))

    yield str(db_path)

    # Teardown: 清理连接池,防止 stale connection 跨测试泄漏
    # monkeypatch 在 fixture 之后才会还原 DB_PATH,因此必须在 yield 后显式清空 pool
    try:
        import database as _db
        # queue.Queue 没有 clear() 方法,用临时 queue 替换更安全
        old_pool = _db._conn_pool
        import queue as _q
        _db._conn_pool = _q.Queue(maxsize=_db._POOL_SIZE)
        # 主动关闭旧 pool 里残留的连接
        while not old_pool.empty():
            try:
                stale = old_pool.get_nowait()
                stale.close()
            except Exception:
                break
    except Exception:
        pass  # 静默失败,不影响测试结果