"""StockAI — SQLite 数据库连接"""

import sqlite3
from pathlib import Path
from config import DB_PATH

# 确保数据库目录存在
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    """查询多行"""
    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """查询单行"""
    conn = get_db()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> dict:
    """执行写操作，返回 {changes, lastrowid}"""
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return {"changes": cur.rowcount, "lastrowid": cur.lastrowid}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_many(statements: list[tuple[str, tuple]]) -> None:
    """原子批量写入：多条 SQL 在同一事务中执行，失败则全部回滚"""
    conn = get_db()
    try:
        cur = conn.cursor()
        for sql, params in statements:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表（幂等）"""
    conn = get_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")

        # 核心表
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL UNIQUE,
            email       TEXT NOT NULL UNIQUE,
            password    TEXT NOT NULL,
            phone       TEXT,
            avatar_url  TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code  TEXT NOT NULL,
            stock_name  TEXT,
            market      TEXT,
            asset_type  TEXT DEFAULT '',
            quantity    INTEGER NOT NULL,
            cost_price  REAL NOT NULL,
            shares      REAL,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS watchlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code  TEXT NOT NULL,
            stock_name  TEXT,
            market      TEXT,
            asset_type  TEXT DEFAULT '',
            added_at    TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, stock_code)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code  TEXT NOT NULL,
            stock_name  TEXT,
            asset_type  TEXT DEFAULT '',
            direction   TEXT NOT NULL,
            price       REAL NOT NULL,
            quantity    INTEGER NOT NULL,
            amount      REAL NOT NULL,
            fee         REAL DEFAULT 0,
            traded_at   TEXT NOT NULL,
            note        TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_conversations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            model           TEXT,
            tokens_used     INTEGER,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS agents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            description     TEXT DEFAULT '',
            system_prompt   TEXT DEFAULT '',
            tools           TEXT DEFAULT '[]',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS installed_skills (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            skill_id    TEXT NOT NULL,
            skill_name  TEXT,
            version     TEXT,
            enabled     INTEGER DEFAULT 1,
            config      TEXT DEFAULT '{}',
            installed_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, skill_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS price_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code  TEXT NOT NULL,
            alert_type  TEXT NOT NULL,
            target_value REAL NOT NULL,
            triggered   INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS dca_plans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            holding_id      INTEGER REFERENCES holdings(id) ON DELETE CASCADE,
            stock_code      TEXT NOT NULL,
            stock_name      TEXT,
            cycle           TEXT NOT NULL,
            cycle_day       INTEGER,
            amount          REAL NOT NULL,
            next_deduction  TEXT,
            active          INTEGER DEFAULT 1,
            memo            TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS dividends (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code      TEXT NOT NULL,
            stock_name      TEXT,
            amount_per_share REAL NOT NULL,
            ex_date         TEXT NOT NULL,
            total_amount    REAL NOT NULL,
            note            TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS portfolios (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            type            TEXT NOT NULL DEFAULT 'long',
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key             TEXT PRIMARY KEY,
            value           TEXT NOT NULL
        )""")
        # 向后兼容：为已有数据库添加缺失字段
        for col, col_def in [
            ("asset_type", "TEXT DEFAULT ''"),
            ("shares", "REAL"),
            ("portfolio_id", "INTEGER REFERENCES portfolios(id) ON DELETE SET NULL"),
            ("journal", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE holdings ADD COLUMN {col} {col_def}")
            except Exception:
                pass
        for col, col_def in [
            ("asset_type", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE watchlist ADD COLUMN {col} {col_def}")
            except Exception:
                pass
        for col, col_def in [
            ("asset_type", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {col_def}")
            except Exception:
                pass
        try:
            conn.execute("ALTER TABLE dca_plans ADD COLUMN last_reminded TEXT DEFAULT ''")
        except Exception:
            pass
        conn.execute("""CREATE TABLE IF NOT EXISTS review_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            report_type TEXT NOT NULL DEFAULT 'daily',
            period_start TEXT,
            period_end TEXT,
            transactions_count INTEGER DEFAULT 0,
            dimensions TEXT NOT NULL DEFAULT '[]',
            ai_response TEXT,
            summary TEXT,
            score_data TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        # AI 策略对抗 — 对战回合 + 选股记录
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_duel_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_days INTEGER NOT NULL DEFAULT 7,
            initial_capital REAL NOT NULL DEFAULT 100000,
            started_at TEXT DEFAULT (datetime('now','localtime')),
            ended_at TEXT,
            status TEXT DEFAULT 'active'
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_duel_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL REFERENCES ai_duel_rounds(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            buy_price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            invested REAL NOT NULL,
            reason TEXT DEFAULT '',
            style TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.commit()
    finally:
        conn.close()

