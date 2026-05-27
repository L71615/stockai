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
