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
-- v4.2 M1 状态机升级 (6 态, OSS OMS 风格):
--   open:           未成交(含买入/卖出挂单) — pending_buy / pending_sell 老字面量归一化到此
--   partial_filled: 部分成交
--   filled:         已成交(持仓中,未卖出) — bought 老字面量归一化到此
--   closed:         已卖出结算完成 — sold 老字面量归一化到此
--   cancelled:      用户取消
--   rejected:       broker/系统拒绝
-- 状态机白名单 + 转换守卫见 backend/services/t1_watcher.py:transition()
CREATE TABLE t1_pending_orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code          TEXT    NOT NULL,
    stock_name          TEXT    NOT NULL DEFAULT '',
    brief_id            INTEGER REFERENCES quant_briefs(id) ON DELETE SET NULL,  -- 关联的简报
    shares              INTEGER NOT NULL DEFAULT 100,         -- 模拟买入股数(原计划)
    planned_entry_price REAL,                                  -- 计划买入价(前晚收盘价)
    planned_exit_price  REAL,                                  -- 计划卖出价(预期)
    executed_entry_price REAL,                                 -- 实际模拟成交价(开盘 × 滑点)
    executed_exit_price  REAL,                                 -- 实际模拟成交价(开盘 × 滑点)
    hold_days           INTEGER NOT NULL DEFAULT 1,            -- 持仓天数 T+1=1
    status              TEXT    NOT NULL DEFAULT 'open',       -- v4.2 M1: 新字面量
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
    source              TEXT    NOT NULL DEFAULT 'user_manual', -- v4.1 1A.3: pipeline_proposal / user_manual
    proposal_id         INTEGER,                                -- v4.1 1A.3: 关联 approval_proposals.proposal_id
    filled_shares       INTEGER NOT NULL DEFAULT 0,             -- v4.2 M1: partial_filled 已成交股数
    pending_shares      INTEGER,                                -- v4.2 M1: partial_filled 挂单剩余股数
    created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_t1_orders_user      ON t1_pending_orders(user_id);
CREATE INDEX idx_t1_orders_status    ON t1_pending_orders(status);
CREATE INDEX idx_t1_orders_brief     ON t1_pending_orders(brief_id);
CREATE INDEX idx_t1_orders_entry_dt  ON t1_pending_orders(entry_date);
CREATE INDEX idx_t1_orders_exit_dt   ON t1_pending_orders(exit_date);

-- v4.2 M1 — T+1 watcher 事件溯源表(append-only 审计)
-- 每次状态转换 / 风控拦截 / 取消都写一条 event,order_id → 整条生命周期可回放
CREATE TABLE t1_order_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       INTEGER NOT NULL REFERENCES t1_pending_orders(id) ON DELETE CASCADE,
    actor          TEXT    NOT NULL DEFAULT 'system',
    event_type     TEXT    NOT NULL,                          -- 'transition' / 'risk_blocked' / 'cancel' / 'filled' / 'closed' / 'expired'
    from_status    TEXT,                                       -- 转换前状态(原样记录, 老字面量可追溯)
    to_status      TEXT,                                       -- 转换后状态
    filled_shares  INTEGER,                                    -- partial_filled 用
    pending_shares INTEGER,                                    -- partial_filled 用
    reason         TEXT    NOT NULL DEFAULT '',
    metadata_json  TEXT    NOT NULL DEFAULT '{}',              -- risk_blocked 时存 risk_result
    created_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_t1_ev_order ON t1_order_events(order_id);
CREATE INDEX idx_t1_ev_time  ON t1_order_events(created_at);
CREATE INDEX idx_t1_ev_type  ON t1_order_events(event_type);

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
