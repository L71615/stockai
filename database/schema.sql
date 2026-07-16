-- ============================================================
-- StockAI 数据库表结构 (PostgreSQL / MySQL 8.0+)
-- ============================================================

-- 用户表
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(50)  NOT NULL UNIQUE,
    email       VARCHAR(100) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,           -- bcrypt hash
    phone       VARCHAR(20),
    avatar_url  VARCHAR(500),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 持仓表
CREATE TABLE holdings (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  VARCHAR(20)  NOT NULL,            -- e.g. 600519
    stock_name  VARCHAR(100),                     -- e.g. 贵州茅台
    market      VARCHAR(10),                      -- SH / SZ / BJ
    quantity    INT NOT NULL,                     -- 持有股数
    cost_price  DECIMAL(10,3) NOT NULL,           -- 成本价
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 自选股表
CREATE TABLE watchlist (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  VARCHAR(20) NOT NULL,
    stock_name  VARCHAR(100),
    market      VARCHAR(10),
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, stock_code)
);

-- 交易记录表
CREATE TABLE transactions (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  VARCHAR(20) NOT NULL,
    stock_name  VARCHAR(100),
    direction   VARCHAR(10) NOT NULL,              -- buy / sell
    price       DECIMAL(10,3) NOT NULL,
    quantity    INT NOT NULL,
    amount      DECIMAL(12,2) NOT NULL,            -- price * quantity
    fee         DECIMAL(10,2) DEFAULT 0,
    traded_at   TIMESTAMP NOT NULL,
    note        TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI 对话历史表
CREATE TABLE ai_conversations (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(200),                      -- 会话标题
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ai_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role            VARCHAR(10) NOT NULL,          -- user / assistant
    content         TEXT NOT NULL,
    model           VARCHAR(50),                   -- e.g. claude-opus-4-7
    tokens_used     INT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Skills 安装记录表
CREATE TABLE installed_skills (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id    VARCHAR(50) NOT NULL,              -- e.g. financial-report
    skill_name  VARCHAR(100),
    version     VARCHAR(20),
    enabled     BOOLEAN DEFAULT TRUE,
    config      JSONB DEFAULT '{}',                -- 自定义配置
    installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, skill_id)
);

-- 价格提醒表
CREATE TABLE price_alerts (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_code  VARCHAR(20) NOT NULL,
    alert_type  VARCHAR(10) NOT NULL,              -- above / below / pct_change
    target_value DECIMAL(10,3) NOT NULL,
    triggered   BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_holdings_user       ON holdings(user_id);
CREATE INDEX idx_watchlist_user      ON watchlist(user_id);
CREATE INDEX idx_transactions_user   ON transactions(user_id);
CREATE INDEX idx_transactions_date   ON transactions(traded_at);
CREATE INDEX idx_ai_messages_conv    ON ai_messages(conversation_id);
CREATE INDEX idx_alerts_user         ON price_alerts(user_id);


-- 历史 K 线表 (screener / quant / 回测主数据源)
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
CREATE INDEX idx_hkline_date         ON historical_kline(trade_date);
CREATE INDEX idx_hkline_code_date    ON historical_kline(stock_code, trade_date);


-- 55 因子预计算快照表 (screener 直接读, 跳过每次重算)
CREATE TABLE factor_snapshot (
    stock_code  TEXT    NOT NULL,
    factor_name TEXT    NOT NULL,
    value       REAL,
    updated_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_code, factor_name)
);
CREATE INDEX idx_factor_snap_code ON factor_snapshot(stock_code);
CREATE INDEX idx_factor_snap_name ON factor_snapshot(factor_name);

-- 北向资金日级缓存 (akshare 批量调用一次拉全市场, screener 不再每只股票调)
CREATE TABLE daily_north_flow (
    stock_code  TEXT    NOT NULL,
    trade_date  TEXT    NOT NULL,
    net_flow    REAL,           -- 净流入 (亿元)
    change_qty  REAL,           -- 持股数量变化 (股)
    rank        INTEGER,        -- 当日净流入排名 (1=最高)
    updated_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_code, trade_date)
);
CREATE INDEX idx_north_flow_date ON daily_north_flow(trade_date);

-- 机构持仓日级缓存
CREATE TABLE daily_inst_holding (
    stock_code   TEXT    NOT NULL,
    trade_date   TEXT    NOT NULL,
    hold_pct     REAL,
    change_pct   REAL,
    updated_at   TEXT    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_code, trade_date)
);
CREATE INDEX idx_inst_holding_date ON daily_inst_holding(trade_date);
