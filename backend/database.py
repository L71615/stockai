"""StockAI — SQLite 数据库连接（连接池 + busy_timeout）"""

import sqlite3
import queue
from pathlib import Path
from config import DB_PATH

# 确保数据库目录存在
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# ── 连接池 ──
# v4.1 1A.2: 5 → 15 (5+ scheduler threads + 22:00 pipeline + 09:30 watcher + drift)
_POOL_SIZE = 15
_conn_pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=_POOL_SIZE)


def _new_connection() -> sqlite3.Connection:
    """创建新连接（含 PRAGMA 初始化）

    v4.1 1A.2: busy_timeout 5000 → 10000 (GP/ML 长写锁期间不阻塞调度读)
    """
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


class _PooledConnection:
    """sqlite3.Connection 包装器 — 拦截 close() 归还连接池"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def close(self) -> None:
        """归还连接到池中（而非真正关闭）"""
        try:
            self._conn.rollback()
            _conn_pool.put_nowait(self._conn)
        except (queue.Full, sqlite3.ProgrammingError):
            self._conn.close()


def get_db() -> sqlite3.Connection:
    """获取数据库连接（优先从连接池取，池空则新建）。

    返回 _PooledConnection 包装器，调用方仍可安全调用 conn.close()
    连接会被归还到池中而非真正关闭。
    """
    try:
        raw = _conn_pool.get_nowait()
    except queue.Empty:
        raw = _new_connection()
    return _PooledConnection(raw)


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

        # 内部时间辅助
        from datetime import datetime as _dt
        _now_iso = lambda: _dt.now().strftime("%Y-%m-%d %H:%M:%S")

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
        conn.execute("""CREATE TABLE IF NOT EXISTS quant_briefs (
            id           TEXT PRIMARY KEY,
            content_md   TEXT NOT NULL,
            summary_json TEXT,
            created_at   TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_quant_briefs_created ON quant_briefs(created_at)")

        # v4.0 (T+1/T+2) — 模拟成交订单表
        # 状态机: pending_buy → bought → pending_sell → sold (或 cancelled)
        conn.execute("""CREATE TABLE IF NOT EXISTS t1_pending_orders (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stock_code          TEXT    NOT NULL,
            stock_name          TEXT    NOT NULL DEFAULT '',
            brief_id            TEXT,
            shares              INTEGER NOT NULL DEFAULT 100,
            planned_entry_price REAL,
            planned_exit_price  REAL,
            executed_entry_price REAL,
            executed_exit_price  REAL,
            hold_days           INTEGER NOT NULL DEFAULT 1,
            status              TEXT    NOT NULL DEFAULT 'pending_buy',
            slippage_bps        REAL    NOT NULL DEFAULT 10.0,
            entry_date          TEXT,
            exit_date           TEXT,
            actual_entry_at     TEXT,
            actual_exit_at      TEXT,
            entry_fee           REAL,
            exit_fee            REAL,
            holding_risk_premium REAL,
            gross_pnl           REAL,
            net_pnl             REAL,
            net_return_pct      REAL,
            reason              TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_t1_orders_user      ON t1_pending_orders(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_t1_orders_status    ON t1_pending_orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_t1_orders_entry_dt  ON t1_pending_orders(entry_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_t1_orders_exit_dt   ON t1_pending_orders(exit_date)")

        # v4.1 1A.3: ALTER TABLE 加 source 字段 (pipeline_proposal / user_manual)
        # 用 try/except 处理"列已存在" (OperationalError)
        try:
            conn.execute(
                "ALTER TABLE t1_pending_orders ADD COLUMN source TEXT NOT NULL DEFAULT 'user_manual'"
            )
        except Exception:
            pass  # 列已存在, 跳过

        # v4.1 1A.1: watcher 健康检查表 (单行 UPSERT, 不需要索引)
        conn.execute("""CREATE TABLE IF NOT EXISTS watcher_health (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            last_run_at        TEXT NOT NULL,
            last_status        TEXT NOT NULL DEFAULT 'ok',
            last_run_proposals INTEGER NOT NULL DEFAULT 0,
            last_error         TEXT NOT NULL DEFAULT ''
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
            ("stop_loss_price", "REAL"),
            ("take_profit_price", "REAL"),
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
        for col, col_def in [
            ("stop_loss_price", "REAL"),
            ("stop_loss_triggered", "INTEGER DEFAULT 0"),
            ("stop_loss_triggered_at", "TEXT"),
            ("planned_exit_price", "REAL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {col_def}")
            except Exception:
                pass
        try:
            conn.execute("ALTER TABLE dca_plans ADD COLUMN last_reminded TEXT DEFAULT ''")
        except Exception:
            pass
        conn.execute("""CREATE TABLE IF NOT EXISTS trade_journal (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL DEFAULT 1,
            stock_code        TEXT NOT NULL,
            stock_name        TEXT DEFAULT '',
            direction         TEXT NOT NULL,
            entry_price       REAL,
            exit_price        REAL,
            quantity          INTEGER,
            pnl               REAL,
            pnl_pct           REAL,
            stop_loss_hit     INTEGER DEFAULT 0,
            planned           INTEGER DEFAULT 0,
            discipline_score  INTEGER,
            emotional_state   TEXT DEFAULT '',
            lessons_learned   TEXT DEFAULT '',
            entry_date        TEXT NOT NULL,
            exit_date         TEXT,
            created_at        TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_user ON trade_journal(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_date ON trade_journal(entry_date)")
        conn.execute("""CREATE TABLE IF NOT EXISTS trading_plans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL DEFAULT 1,
            plan_date       TEXT NOT NULL,
            plan_type       TEXT NOT NULL DEFAULT 'pre_market',
            status          TEXT NOT NULL DEFAULT 'draft',
            market_state    TEXT DEFAULT '',
            content         TEXT NOT NULL DEFAULT '{}',
            summary         TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, plan_date, plan_type)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS historical_kline (
            stock_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            volume     REAL,
            PRIMARY KEY (stock_code, trade_date)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hkline_date ON historical_kline(trade_date)")
        conn.execute("""CREATE TABLE IF NOT EXISTS futu_raw_quote (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL,
            market      TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            price       REAL,
            open_price  REAL,
            high_price  REAL,
            low_price   REAL,
            prev_close  REAL,
            change      REAL,
            change_pct  REAL,
            volume      REAL,
            turnover    REAL,
            quote_time  TEXT NOT NULL,
            source      TEXT NOT NULL DEFAULT 'futu',
            raw_payload TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_futu_raw_quote_symbol_time ON futu_raw_quote(symbol, quote_time DESC)"
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS futu_raw_kline (
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
        )""")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_futu_raw_kline_bar ON futu_raw_kline(symbol, interval, bar_time, adjust_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_futu_raw_kline_symbol_interval_time ON futu_raw_kline(symbol, interval, bar_time DESC)"
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS futu_sync_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type      TEXT NOT NULL,
            scope         TEXT NOT NULL,
            target_count  INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failed_count  INTEGER NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'skipped',
            started_at    TEXT NOT NULL,
            finished_at   TEXT,
            duration_ms   INTEGER DEFAULT 0,
            error_summary TEXT DEFAULT '',
            alert_sent    INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS futu_sync_run_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER NOT NULL REFERENCES futu_sync_runs(id) ON DELETE CASCADE,
            stock_code      TEXT NOT NULL,
            sync_type       TEXT NOT NULL,
            status          TEXT NOT NULL,
            error_message   TEXT DEFAULT '',
            source          TEXT DEFAULT 'futu',
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            duration_ms     INTEGER DEFAULT 0,
            from_watchlist  INTEGER NOT NULL DEFAULT 0,
            from_holdings   INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_futu_sync_runs_type_time ON futu_sync_runs(run_type, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_futu_sync_run_items_run ON futu_sync_run_items(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_futu_sync_run_items_code_type ON futu_sync_run_items(stock_code, sync_type)")
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

        # ── 实验账本 (T1: 三轴状态机) ──
        # 防御性补建：factor_candidates / factor_lifecycle_status 早期手工建过
        # 这里加 IF NOT EXISTS 防止新部署时缺失
        conn.execute("""CREATE TABLE IF NOT EXISTS factor_candidates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            expr_text       TEXT NOT NULL,
            ic_mean         REAL,
            ir              REAL,
            win_rate        REAL,
            valid_days      INTEGER,
            tree_depth      INTEGER,
            promoted        INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            UNIQUE(run_id, expr_text)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS factor_lifecycle_status (
            factor_name     TEXT PRIMARY KEY,
            status          TEXT NOT NULL DEFAULT 'candidate',
            ir              REAL,
            warning_days    INTEGER NOT NULL DEFAULT 0,
            last_updated    TEXT NOT NULL,
            note            TEXT DEFAULT ''
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS experiments (
            experiment_id       TEXT PRIMARY KEY,
            owner_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expr_text           TEXT NOT NULL,
            candidate_id        INTEGER REFERENCES factor_candidates(id) ON DELETE SET NULL,
            policy_version      TEXT NOT NULL DEFAULT 'v1.0.0',
            snapshot_hash       TEXT NOT NULL DEFAULT '',
            lifecycle_status    TEXT NOT NULL DEFAULT 'candidate',
            portfolio_role      TEXT NOT NULL DEFAULT 'none',
            proposal_status     TEXT NOT NULL DEFAULT 'pending',
            version             INTEGER NOT NULL DEFAULT 1,
            snapshot_json       TEXT NOT NULL DEFAULT '{}',
            note                TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_user ON experiments(owner_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_lifecycle ON experiments(lifecycle_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_role ON experiments(portfolio_role)")
        conn.execute("""CREATE TABLE IF NOT EXISTS experiment_runs (
            run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id       TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
            scope               TEXT NOT NULL DEFAULT 'pipeline',
            status              TEXT NOT NULL DEFAULT 'running',
            current_step        TEXT NOT NULL DEFAULT '',
            started_at          TEXT NOT NULL,
            finished_at         TEXT,
            error_json          TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_experiment_runs_exp ON experiment_runs(experiment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_experiment_runs_status ON experiment_runs(status)")
        conn.execute("""CREATE TABLE IF NOT EXISTS experiment_run_events (
            event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id       TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
            run_id              INTEGER REFERENCES experiment_runs(run_id) ON DELETE SET NULL,
            actor               TEXT NOT NULL DEFAULT 'system',
            event_type          TEXT NOT NULL,
            from_state          TEXT,
            to_state            TEXT,
            from_version        INTEGER,
            to_version          INTEGER,
            reason              TEXT NOT NULL DEFAULT '',
            evidence_version    TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_events_exp ON experiment_run_events(experiment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_events_time ON experiment_run_events(created_at)")
        # 单飞锁：同 scope 只允许一个 worker 跑
        conn.execute("""CREATE TABLE IF NOT EXISTS pipeline_lock (
            scope               TEXT PRIMARY KEY,
            holder_pid          TEXT NOT NULL,
            acquired_at         TEXT NOT NULL,
            expires_at          TEXT NOT NULL
        )""")
        # ── T2 实验快照 (point-in-time 输入冻结) ──
        conn.execute("""CREATE TABLE IF NOT EXISTS experiment_snapshots (
            snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id       TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
            version             INTEGER NOT NULL DEFAULT 1,
            policy_hash         TEXT NOT NULL DEFAULT '',
            input_version_hash  TEXT NOT NULL DEFAULT '',
            as_of_date          TEXT NOT NULL,
            snapshot_json       TEXT NOT NULL,
            note                TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL,
            UNIQUE(experiment_id, version)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_snapshots_exp ON experiment_snapshots(experiment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_snapshots_asof ON experiment_snapshots(as_of_date)")
        # ── T3 验证策略版本表 ──
        conn.execute("""CREATE TABLE IF NOT EXISTS validation_policies (
            version         TEXT PRIMARY KEY,
            hash            TEXT NOT NULL,
            body_json       TEXT NOT NULL,
            note            TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL,
            activated_at    TEXT
        )""")
        # ── T4 影子组合 ──
        conn.execute("""CREATE TABLE IF NOT EXISTS shadow_portfolios (
            portfolio_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            experiment_id       TEXT REFERENCES experiments(experiment_id) ON DELETE SET NULL,
            candidate_id        INTEGER REFERENCES factor_candidates(id) ON DELETE SET NULL,
            name                TEXT NOT NULL DEFAULT '',
            policy_version      TEXT NOT NULL DEFAULT 'v1.0.0',
            initial_cash        REAL NOT NULL DEFAULT 100000,
            target_weights_json TEXT NOT NULL DEFAULT '{}',
            scope               TEXT NOT NULL DEFAULT 'paper',
            status              TEXT NOT NULL DEFAULT 'active',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_pf_user ON shadow_portfolios(owner_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_pf_exp ON shadow_portfolios(experiment_id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS shadow_portfolio_snapshots (
            snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id        INTEGER NOT NULL REFERENCES shadow_portfolios(portfolio_id) ON DELETE CASCADE,
            observation_date    TEXT NOT NULL,
            nav                 REAL NOT NULL,
            cash                REAL NOT NULL,
            holdings_json       TEXT NOT NULL DEFAULT '{}',
            target_weights_json TEXT NOT NULL DEFAULT '{}',
            actual_weights_json TEXT NOT NULL DEFAULT '{}',
            turnover            REAL NOT NULL DEFAULT 0,
            costs               REAL NOT NULL DEFAULT 0,
            drawdown            REAL NOT NULL DEFAULT 0,
            baseline_diff_json  TEXT NOT NULL DEFAULT '{}',
            status              TEXT NOT NULL DEFAULT 'settled',
            reason              TEXT NOT NULL DEFAULT '',
            input_version       TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL,
            UNIQUE(portfolio_id, observation_date, input_version)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_snap_pf ON shadow_portfolio_snapshots(portfolio_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_snap_date ON shadow_portfolio_snapshots(observation_date)")

        # v4.1 1B.2: shadow 净值预聚合表 (1h / 4h / 1d buckets)
        # 避免每次页面查询 5530×30 = 166k 数据点
        conn.execute("""CREATE TABLE IF NOT EXISTS shadow_equity_aggregated (
            agg_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id        INTEGER NOT NULL REFERENCES shadow_portfolios(portfolio_id) ON DELETE CASCADE,
            bucket              TEXT NOT NULL,    -- '1h' / '4h' / '1d'
            observation_date    TEXT NOT NULL,
            nav                 REAL NOT NULL,
            drawdown            REAL NOT NULL DEFAULT 0,
            turnover            REAL NOT NULL DEFAULT 0,
            costs               REAL NOT NULL DEFAULT 0,
            UNIQUE(portfolio_id, bucket, observation_date)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_agg_pf ON shadow_equity_aggregated(portfolio_id, bucket)")
        # ── T5 审批 ──
        conn.execute("""CREATE TABLE IF NOT EXISTS approval_proposals (
            proposal_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id       TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
            candidate_id        INTEGER REFERENCES factor_candidates(id) ON DELETE SET NULL,
            owner_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            evidence_version    TEXT NOT NULL DEFAULT '',
            candidate_version   INTEGER NOT NULL DEFAULT 0,
            experiment_version  INTEGER NOT NULL DEFAULT 0,
            action              TEXT NOT NULL DEFAULT 'promote',
            target_lifecycle    TEXT,
            target_portfolio    TEXT,
            target_proposal     TEXT,
            policy_version      TEXT NOT NULL DEFAULT 'v1.0.0',
            policy_hash         TEXT NOT NULL DEFAULT '',
            snapshot_hash       TEXT NOT NULL DEFAULT '',
            lease_id            TEXT NOT NULL DEFAULT '',
            lease_expires_at    TEXT,
            status              TEXT NOT NULL DEFAULT 'pending',
            decided_at          TEXT,
            decided_by          TEXT,
            decision_reason     TEXT NOT NULL DEFAULT '',
            version             INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appr_prop_user ON approval_proposals(owner_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appr_prop_status ON approval_proposals(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appr_prop_exp ON approval_proposals(experiment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appr_prop_lease ON approval_proposals(lease_expires_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS approval_attempts (
            attempt_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id         INTEGER NOT NULL REFERENCES approval_proposals(proposal_id) ON DELETE CASCADE,
            lease_id            TEXT NOT NULL DEFAULT '',
            action              TEXT NOT NULL,
            actor               TEXT NOT NULL DEFAULT '',
            result              TEXT NOT NULL,
            error_json          TEXT NOT NULL DEFAULT '{}',
            expected_version    INTEGER NOT NULL DEFAULT 0,
            current_version     INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appr_att_prop ON approval_attempts(proposal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appr_att_lease ON approval_attempts(lease_id)")
        # ── T8 灰度开关 ──
        conn.execute("""CREATE TABLE IF NOT EXISTS feature_flags (
            flag_key            TEXT PRIMARY KEY,
            enabled             INTEGER NOT NULL DEFAULT 0,
            scope               TEXT NOT NULL DEFAULT 'global',
            description         TEXT NOT NULL DEFAULT '',
            updated_by          TEXT NOT NULL DEFAULT '',
            updated_at          TEXT NOT NULL
        )""")
        # ── T8 通知审计 (独立于研究状态) ──
        conn.execute("""CREATE TABLE IF NOT EXISTS notification_log (
            log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id              TEXT,
            channel             TEXT NOT NULL,
            target              TEXT NOT NULL DEFAULT '',
            success             INTEGER NOT NULL DEFAULT 0,
            error_json          TEXT NOT NULL DEFAULT '{}',
            created_at          TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_run ON notification_log(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_time ON notification_log(created_at)")
        # 默认全 OFF 的 flag
        for key, desc in [
            ("pipeline.shadow.enabled", "启用影子组合 (T4)"),
            ("pipeline.approval.enabled", "启用审批收件箱 (T5)"),
            ("pipeline.negative_control.enabled", "启用负对照 (T3)"),
            ("pipeline.champion_replacement.enabled", "启用 Champion/Challenger 替换建议 (Gate 2)"),
            ("pipeline.auto_promote.enabled", "自动晋级 (默认 OFF, 必须人工)"),
        ]:
            try:
                conn.execute(
                    "INSERT INTO feature_flags (flag_key, enabled, scope, description, updated_by, updated_at) "
                    "VALUES (?, 0, 'global', ?, 'bootstrap', ?)",
                    (key, desc, _now_iso()),
                )
            except Exception:
                pass  # IF NOT EXISTS implied (key PK), 重复运行 init_db 时跳过
        # ── T9 复盘 ──
        conn.execute("""CREATE TABLE IF NOT EXISTS proposal_outcomes (
            outcome_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id         INTEGER NOT NULL REFERENCES approval_proposals(proposal_id) ON DELETE CASCADE,
            decision            TEXT NOT NULL,    -- 'approved' | 'rejected' | 'withdrawn'
            realized_at         TEXT NOT NULL,
            fwd_days            INTEGER NOT NULL DEFAULT 0,
            fwd_return          REAL NOT NULL DEFAULT 0,
            fwd_shadow_return   REAL NOT NULL DEFAULT 0,
            fwd_baseline_diff   REAL NOT NULL DEFAULT 0,
            baseline_code       TEXT NOT NULL DEFAULT 'csi300',
            label               TEXT NOT NULL DEFAULT '',   -- 'good' | 'bad' | 'neutral'
            created_at          TEXT NOT NULL,
            UNIQUE(proposal_id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON proposal_outcomes(decision)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_realized ON proposal_outcomes(realized_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS proposal_retrospectives (
            retro_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id         INTEGER NOT NULL REFERENCES approval_proposals(proposal_id) ON DELETE CASCADE,
            experiment_id       TEXT NOT NULL,
            decision            TEXT NOT NULL,
            fwd_days            INTEGER NOT NULL,
            fwd_return          REAL NOT NULL,
            fwd_baseline_diff   REAL NOT NULL,
            hypothesis          TEXT NOT NULL DEFAULT '',
            evidence_summary    TEXT NOT NULL DEFAULT '',
            realized_summary    TEXT NOT NULL DEFAULT '',
            lesson              TEXT NOT NULL DEFAULT '',
            confidence          REAL NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_retro_exp ON proposal_retrospectives(experiment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_retro_decision ON proposal_retrospectives(decision)")

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
            # ── 本地数据缓存（Futu 定时同步落地）──
            "CREATE TABLE IF NOT EXISTS local_fundamentals ("
            "  stock_code TEXT NOT NULL, trade_date TEXT NOT NULL,"
            "  pe_ttm REAL, pb REAL, market_cap REAL, turnover_rate REAL,"
            "  eps REAL, roe REAL, dividend_yield REAL,"
            "  source TEXT DEFAULT 'futu',"
            "  PRIMARY KEY (stock_code, trade_date))",
            "CREATE TABLE IF NOT EXISTS local_plate_daily ("
            "  plate_code TEXT NOT NULL, trade_date TEXT NOT NULL,"
            "  avg_change REAL, up_count INTEGER, down_count INTEGER, total INTEGER,"
            "  PRIMARY KEY (plate_code, trade_date))",
            "CREATE INDEX IF NOT EXISTS idx_local_plate_daily_date ON local_plate_daily(trade_date)",
            "CREATE TABLE IF NOT EXISTS stock_info ("
            "  stock_code TEXT PRIMARY KEY, name TEXT, industry TEXT, list_date TEXT)",
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

