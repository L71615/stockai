-- ============================================================
-- StockAI 数据库表结构 (SQLite 3)
-- ============================================================

PRAGMA foreign_keys = ON;

-- 用户表
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    email       TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,                -- bcrypt hash
    phone       TEXT,
    avatar_url  TEXT,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- 持仓表
CREATE TABLE holdings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  TEXT NOT NULL,               -- e.g. 600519
    stock_name  TEXT,                        -- e.g. 贵州茅台
    market      TEXT,                        -- SH / SZ / BJ
    quantity    INTEGER NOT NULL,            -- 持有股数
    cost_price  REAL NOT NULL,              -- 成本价
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- 自选股表
CREATE TABLE watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  TEXT NOT NULL,
    stock_name  TEXT,
    market      TEXT,
    added_at    TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(user_id, stock_code)
);

-- 交易记录表
CREATE TABLE transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  TEXT NOT NULL,
    stock_name  TEXT,
    direction   TEXT NOT NULL,               -- buy / sell
    price       REAL NOT NULL,
    quantity    INTEGER NOT NULL,
    amount      REAL NOT NULL,              -- price * quantity
    fee         REAL DEFAULT 0,
    traded_at   TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- AI 对话历史表
CREATE TABLE ai_conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT,                        -- 会话标题
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE ai_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,           -- user / assistant
    content         TEXT NOT NULL,
    model           TEXT,                    -- e.g. claude-opus-4-7
    tokens_used     INTEGER,
    created_at      TEXT DEFAULT (datetime('now','localtime'))
);

-- Skills 安装记录表
CREATE TABLE installed_skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id    TEXT NOT NULL,               -- e.g. financial-report
    skill_name  TEXT,
    version     TEXT,
    enabled     INTEGER DEFAULT 1,           -- 1=true, 0=false
    config      TEXT DEFAULT '{}',           -- JSON stored as TEXT
    installed_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(user_id, skill_id)
);

-- v4.0 (T+1/T+2) — 模拟成交订单表
-- 状态机: pending_buy → bought → pending_sell → sold
--   pending_buy:  22:00 pipeline 生成,等待次日 09:30 模拟买入
--   bought:       已模拟买入(写 holdings + transactions),等待持仓期满
--   pending_sell: 持仓期满,等待次日 09:30 模拟卖出
--   sold:         已模拟卖出(写 transactions),记录收益统计
--   cancelled:    手动取消或异常退出
CREATE TABLE t1_pending_orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code          TEXT    NOT NULL,
    stock_name          TEXT    NOT NULL DEFAULT '',
    brief_id            INTEGER REFERENCES quant_briefs(id) ON DELETE SET NULL,  -- 关联的简报
    shares              INTEGER NOT NULL DEFAULT 100,         -- 模拟买入股数
    planned_entry_price REAL,                                  -- 计划买入价(前晚收盘价)
    planned_exit_price  REAL,                                  -- 计划卖出价(预期)
    executed_entry_price REAL,                                 -- 实际模拟成交价(开盘 × 滑点)
    executed_exit_price  REAL,                                 -- 实际模拟成交价(开盘 × 滑点)
    hold_days           INTEGER NOT NULL DEFAULT 1,            -- 持仓天数 T+1=1
    status              TEXT    NOT NULL DEFAULT 'pending_buy',
    slippage_bps        REAL    NOT NULL DEFAULT 10.0,         -- 滑点
    entry_date          TEXT,                                  -- 计划买入日(次日)
    exit_date           TEXT,                                  -- 计划卖出日(持仓期满次日)
    actual_entry_at     TEXT,                                  -- 实际买入时间戳
    actual_exit_at      TEXT,                                  -- 实际卖出时间戳
    entry_fee           REAL,                                  -- 买入手续费
    exit_fee            REAL,                                  -- 卖出手续费
    holding_risk_premium REAL,                                 -- 持仓风险溢价
    gross_pnl           REAL,                                  -- 税前盈亏
    net_pnl             REAL,                                  -- 净盈亏(扣费 + 溢价)
    net_return_pct      REAL,                                  -- 净收益率 %
    reason              TEXT    NOT NULL DEFAULT '',           -- 推荐理由 / 取消原因
    created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_t1_orders_user      ON t1_pending_orders(user_id);
CREATE INDEX idx_t1_orders_status    ON t1_pending_orders(status);
CREATE INDEX idx_t1_orders_brief     ON t1_pending_orders(brief_id);
CREATE INDEX idx_t1_orders_entry_dt  ON t1_pending_orders(entry_date);
CREATE INDEX idx_t1_orders_exit_dt   ON t1_pending_orders(exit_date);

-- 价格提醒表
CREATE TABLE price_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  TEXT NOT NULL,
    alert_type  TEXT NOT NULL,              -- above / below / pct_change
    target_value REAL NOT NULL,
    triggered   INTEGER DEFAULT 0,          -- 1=true, 0=false
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- 索引
CREATE INDEX idx_holdings_user       ON holdings(user_id);
CREATE INDEX idx_watchlist_user      ON watchlist(user_id);
CREATE INDEX idx_transactions_user   ON transactions(user_id);
CREATE INDEX idx_transactions_date   ON transactions(traded_at);
CREATE INDEX idx_ai_messages_conv    ON ai_messages(conversation_id);
CREATE INDEX idx_alerts_user         ON price_alerts(user_id);

-- ── v4.1 Phase 2A 占位 ──
-- index_kline / etf_kline / index_sync_runs / index_sync_run_items /
-- etf_sync_runs / etf_sync_run_items / drift_events 已在
-- backend/database.py:init_db() 第 832 行之后内嵌创建。
-- 完整 SQL 见 database/schema.sql（reference only，不被运行时加载）。
