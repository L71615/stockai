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
    """临时 SQLite 数据库,futu_raw_kline + historical_kline 两表"""
    import sqlite3
    db_path = tmp_path / "test_minute_bars.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE futu_raw_kline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            market TEXT,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, turnover REAL,
            adjust_type TEXT NOT NULL,
            source TEXT,
            raw_payload TEXT,
            updated_at TEXT
        );
        CREATE TABLE historical_kline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            UNIQUE(stock_code, trade_date)
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