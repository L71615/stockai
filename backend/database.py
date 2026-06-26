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
        conn.execute("PRAGMA journal_mode=WAL")

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
            ("fee", "REAL DEFAULT 0"),
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

        # ── 选股系统表 ──
        conn.execute("""CREATE TABLE IF NOT EXISTS screener_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            total_stocks INTEGER DEFAULT 0,
            scanned INTEGER DEFAULT 0,
            candidates_json TEXT DEFAULT '[]',
            factor_weights_json TEXT DEFAULT '{}',
            market_state TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS screener_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            stock_code TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            market TEXT DEFAULT '',
            asset_type TEXT DEFAULT '',
            status TEXT DEFAULT 'watching',
            reason TEXT DEFAULT '',
            score REAL,
            backtest_strategy TEXT DEFAULT '',
            backtest_sharpe REAL,
            added_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, stock_code)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS screener_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            stock_code TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            alert_type TEXT DEFAULT '',
            severity TEXT DEFAULT 'low',
            message TEXT DEFAULT '',
            checked_at TEXT DEFAULT (datetime('now','localtime')),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        # ── 条件选股保存 ──
        conn.execute("""CREATE TABLE IF NOT EXISTS condition_screens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            conditions_json TEXT NOT NULL DEFAULT '{"logic":"AND","conditions":[]}',
            sort_by TEXT DEFAULT '',
            sort_order TEXT DEFAULT 'desc',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            stock_code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            total_return REAL,
            annual_return REAL,
            sharpe REAL,
            max_drawdown REAL,
            win_rate REAL,
            profit_factor REAL,
            num_trades INTEGER DEFAULT 0,
            initial_cash REAL DEFAULT 100000,
            final_value REAL,
            params_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")

        # ── 数据库索引（性能关键）──
        # 使用 IF NOT EXISTS 幂等，已有索引不重复创建
        indexes = [
            # 持仓
            "CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_holdings_user_code ON holdings(user_id, stock_code)",
            # 自选股
            "CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)",
            # 交易记录
            "CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(traded_at)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_stock ON transactions(stock_code)",
            # AI 消息 (会话内按时间查历史)
            "CREATE INDEX IF NOT EXISTS idx_ai_messages_conv ON ai_messages(conversation_id)",
            # 价格提醒
            "CREATE INDEX IF NOT EXISTS idx_alerts_user ON price_alerts(user_id)",
            # 复盘报告
            "CREATE INDEX IF NOT EXISTS idx_review_reports_user ON review_reports(user_id)",
            # 选股系统
            "CREATE INDEX IF NOT EXISTS idx_screener_results_user ON screener_results(user_id)",
            # 条件选股
            "CREATE INDEX IF NOT EXISTS idx_condition_screens_user ON condition_screens(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_screener_watchlist_user ON screener_watchlist(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_screener_alerts_user ON screener_alerts(user_id)",
            # 回测结果
            "CREATE INDEX IF NOT EXISTS idx_backtest_results_user ON backtest_results(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_backtest_results_code ON backtest_results(stock_code)",
            # 定投计划
            "CREATE INDEX IF NOT EXISTS idx_dca_plans_user ON dca_plans(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_dca_plans_holding ON dca_plans(holding_id)",
            # 分红
            "CREATE INDEX IF NOT EXISTS idx_dividends_user ON dividends(user_id, stock_code)",
        ]
        for sql in indexes:
            conn.execute(sql)

        conn.commit()
    finally:
        conn.close()


def ensure_admin_user():
    """启动时确保管理员账号存在（不开放注册，唯一用户）"""
    from config import ADMIN_EMAIL, ADMIN_PASSWORD
    import bcrypt as _bcrypt

    if not ADMIN_PASSWORD:
        raise ValueError("ADMIN_PASSWORD environment variable must be set — cannot use default or empty value")
    pwd = ADMIN_PASSWORD

    # bcrypt 限制 72 字节，超出截断并警告
    if len(pwd.encode('utf-8')) > 72:
        print(f"[WARNING] ADMIN_PASSWORD 超过 bcrypt 72 字节限制，将截断处理")
        pwd = pwd.encode('utf-8')[:72].decode('utf-8', errors='ignore')

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, password FROM users WHERE email = ?", (ADMIN_EMAIL,)
        ).fetchone()
        if row:
            # 用户已存在，检查密码是否与 .env 一致（不一致则更新）
            if _bcrypt.checkpw(pwd.encode("utf-8"), row["password"].encode("utf-8")):
                print(f"[AUTH] 管理员账号已存在: {ADMIN_EMAIL}")
            else:
                hashed = _bcrypt.hashpw(pwd.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
                conn.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, row["id"]))
                conn.commit()
                print(f"[AUTH] 管理员密码已更新: {ADMIN_EMAIL}")
        else:
            hashed = _bcrypt.hashpw(pwd.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
            conn.execute(
                "INSERT INTO users (id, username, email, password) VALUES (1, ?, ?, ?)",
                ("admin", ADMIN_EMAIL, hashed),
            )
            conn.commit()
            print(f"[AUTH] 管理员账号已创建: {ADMIN_EMAIL}")
    finally:
        conn.close()

