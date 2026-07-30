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

-- v3.10: 量化日报 (auto pipeline 输出)
CREATE TABLE IF NOT EXISTS quant_briefs (
    id           TEXT PRIMARY KEY,
    content_md   TEXT NOT NULL,
    summary_json TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quant_briefs_created ON quant_briefs(created_at);

-- ── v3.11: 实验账本 (三轴状态机) ──
-- 历史 gap 补建：factor_candidates / factor_lifecycle_status
CREATE TABLE IF NOT EXISTS factor_candidates (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    expr_text   TEXT NOT NULL,
    ic_mean     REAL,
    ir          REAL,
    win_rate    REAL,
    valid_days  INTEGER,
    tree_depth  INTEGER,
    promoted    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE(run_id, expr_text)
);
CREATE INDEX IF NOT EXISTS idx_factor_candidates_ir ON factor_candidates(ir DESC);

CREATE TABLE IF NOT EXISTS factor_lifecycle_status (
    factor_name  TEXT PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'candidate',
    ir           REAL,
    warning_days INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL,
    note         TEXT DEFAULT ''
);

-- 实验主表：三轴状态 (lifecycle_status / portfolio_role / proposal_status) + 版本 CAS
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id     TEXT PRIMARY KEY,
    owner_user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expr_text         TEXT NOT NULL,
    candidate_id      INT REFERENCES factor_candidates(id) ON DELETE SET NULL,
    policy_version    TEXT NOT NULL DEFAULT 'v1.0.0',
    snapshot_hash     TEXT NOT NULL DEFAULT '',
    lifecycle_status  TEXT NOT NULL DEFAULT 'candidate',
    portfolio_role    TEXT NOT NULL DEFAULT 'none',
    proposal_status   TEXT NOT NULL DEFAULT 'pending',
    version           INTEGER NOT NULL DEFAULT 1,
    snapshot_json     TEXT NOT NULL DEFAULT '{}',
    note              TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiments_user ON experiments(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_experiments_lifecycle ON experiments(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_experiments_role ON experiments(portfolio_role);

-- 运行历史
-- experiment_id 为 NOT NULL 但允许特殊值: daily pipeline 用 __pipeline_daily__ 占位
-- (避免 schema 漂移: experiment_id 仍然必填, daily pipeline 在代码层兜底)
CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id        SERIAL PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    scope         TEXT NOT NULL DEFAULT 'pipeline',
    status        TEXT NOT NULL DEFAULT 'running',
    current_step  TEXT NOT NULL DEFAULT '',
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    error_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_exp ON experiment_runs(experiment_id);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_status ON experiment_runs(status);

-- append-only 审计事件
CREATE TABLE IF NOT EXISTS experiment_run_events (
    event_id         SERIAL PRIMARY KEY,
    experiment_id    TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    run_id           INT REFERENCES experiment_runs(run_id) ON DELETE SET NULL,
    actor            TEXT NOT NULL DEFAULT 'system',
    event_type       TEXT NOT NULL,
    from_state       TEXT,
    to_state         TEXT,
    from_version     INT,
    to_version       INT,
    reason           TEXT NOT NULL DEFAULT '',
    evidence_version TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exp_events_exp ON experiment_run_events(experiment_id);
CREATE INDEX IF NOT EXISTS idx_exp_events_time ON experiment_run_events(created_at);

-- 单飞锁：同 scope 只允许一个 worker 跑
CREATE TABLE IF NOT EXISTS pipeline_lock (
    scope       TEXT PRIMARY KEY,
    holder_pid  TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

-- v3.11 (T2): 实验快照 — point-in-time 输入冻结, OOS replay 唯一数据源
CREATE TABLE IF NOT EXISTS experiment_snapshots (
    snapshot_id        SERIAL PRIMARY KEY,
    experiment_id      TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    version            INT  NOT NULL DEFAULT 1,
    policy_hash        TEXT NOT NULL DEFAULT '',
    input_version_hash TEXT NOT NULL DEFAULT '',
    as_of_date         TEXT NOT NULL,
    snapshot_json      TEXT NOT NULL,
    note               TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL,
    UNIQUE(experiment_id, version)
);
CREATE INDEX IF NOT EXISTS idx_exp_snapshots_exp ON experiment_snapshots(experiment_id);
CREATE INDEX IF NOT EXISTS idx_exp_snapshots_asof ON experiment_snapshots(as_of_date);

-- v3.11 (T3): 验证策略版本表 — 集中所有阈值 + 双基线 + 成本矩阵 + 状态分层
CREATE TABLE IF NOT EXISTS validation_policies (
    version      TEXT PRIMARY KEY,
    hash         TEXT NOT NULL,
    body_json    TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    activated_at TEXT
);

-- v3.11 (T4): 影子组合 + 每日结算快照
CREATE TABLE IF NOT EXISTS shadow_portfolios (
    portfolio_id        SERIAL PRIMARY KEY,
    owner_user_id       INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    experiment_id       TEXT REFERENCES experiments(experiment_id) ON DELETE SET NULL,
    candidate_id        INT  REFERENCES factor_candidates(id) ON DELETE SET NULL,
    name                TEXT NOT NULL DEFAULT '',
    policy_version      TEXT NOT NULL DEFAULT 'v1.0.0',
    initial_cash        REAL NOT NULL DEFAULT 100000,
    target_weights_json TEXT NOT NULL DEFAULT '{}',
    scope               TEXT NOT NULL DEFAULT 'paper',
    status              TEXT NOT NULL DEFAULT 'active',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_pf_user ON shadow_portfolios(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_shadow_pf_exp ON shadow_portfolios(experiment_id);

CREATE TABLE IF NOT EXISTS shadow_portfolio_snapshots (
    snapshot_id         SERIAL PRIMARY KEY,
    portfolio_id        INT  NOT NULL REFERENCES shadow_portfolios(portfolio_id) ON DELETE CASCADE,
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
);
CREATE INDEX IF NOT EXISTS idx_shadow_snap_pf ON shadow_portfolio_snapshots(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_shadow_snap_date ON shadow_portfolio_snapshots(observation_date);

-- v3.11 (T5): 审批提案 + 审计 (append-only)
CREATE TABLE IF NOT EXISTS approval_proposals (
    proposal_id        SERIAL PRIMARY KEY,
    experiment_id      TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    candidate_id       INT  REFERENCES factor_candidates(id) ON DELETE SET NULL,
    owner_user_id      INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    evidence_version   TEXT NOT NULL DEFAULT '',
    candidate_version  INT  NOT NULL DEFAULT 0,
    experiment_version INT  NOT NULL DEFAULT 0,
    action             TEXT NOT NULL DEFAULT 'promote',
    target_lifecycle   TEXT,
    target_portfolio   TEXT,
    target_proposal    TEXT,
    policy_version     TEXT NOT NULL DEFAULT 'v1.0.0',
    policy_hash        TEXT NOT NULL DEFAULT '',
    snapshot_hash      TEXT NOT NULL DEFAULT '',
    lease_id           TEXT NOT NULL DEFAULT '',
    lease_expires_at   TEXT,
    status             TEXT NOT NULL DEFAULT 'pending',
    decided_at         TEXT,
    decided_by         TEXT,
    decision_reason    TEXT NOT NULL DEFAULT '',
    version            INT  NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appr_prop_user ON approval_proposals(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_appr_prop_status ON approval_proposals(status);
CREATE INDEX IF NOT EXISTS idx_appr_prop_exp ON approval_proposals(experiment_id);
CREATE INDEX IF NOT EXISTS idx_appr_prop_lease ON approval_proposals(lease_expires_at);

CREATE TABLE IF NOT EXISTS approval_attempts (
    attempt_id         SERIAL PRIMARY KEY,
    proposal_id        INT  NOT NULL REFERENCES approval_proposals(proposal_id) ON DELETE CASCADE,
    lease_id           TEXT NOT NULL DEFAULT '',
    action             TEXT NOT NULL,
    actor              TEXT NOT NULL DEFAULT '',
    result             TEXT NOT NULL,
    error_json         TEXT NOT NULL DEFAULT '{}',
    expected_version   INT  NOT NULL DEFAULT 0,
    current_version    INT  NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appr_att_prop ON approval_attempts(proposal_id);
CREATE INDEX IF NOT EXISTS idx_appr_att_lease ON approval_attempts(lease_id);

-- v3.11 (T8): 灰度开关 (feature flags)
CREATE TABLE IF NOT EXISTS feature_flags (
    flag_key     TEXT PRIMARY KEY,
    enabled      INT  NOT NULL DEFAULT 0,
    scope        TEXT NOT NULL DEFAULT 'global',
    description  TEXT NOT NULL DEFAULT '',
    updated_by   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);

-- v3.11 (T8): 通知审计 (与研究状态独立, 不掩盖研究结论)
CREATE TABLE IF NOT EXISTS notification_log (
    log_id      SERIAL PRIMARY KEY,
    run_id      TEXT,
    channel     TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    success     INT  NOT NULL DEFAULT 0,
    error_json  TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_run ON notification_log(run_id);
CREATE INDEX IF NOT EXISTS idx_notif_time ON notification_log(created_at);

-- v3.11 (T9): 复盘 — proposal 前向表现 + 反思
CREATE TABLE IF NOT EXISTS proposal_outcomes (
    outcome_id        SERIAL PRIMARY KEY,
    proposal_id       INT  NOT NULL REFERENCES approval_proposals(proposal_id) ON DELETE CASCADE,
    decision          TEXT NOT NULL,            -- 'approved' | 'rejected' | 'withdrawn'
    realized_at       TEXT NOT NULL,
    fwd_days          INT  NOT NULL DEFAULT 0,
    fwd_return        REAL NOT NULL DEFAULT 0,
    fwd_shadow_return REAL NOT NULL DEFAULT 0,
    fwd_baseline_diff REAL NOT NULL DEFAULT 0,
    baseline_code     TEXT NOT NULL DEFAULT 'csi300',
    label             TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    UNIQUE(proposal_id)
);
CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON proposal_outcomes(decision);
CREATE INDEX IF NOT EXISTS idx_outcomes_realized ON proposal_outcomes(realized_at);

CREATE TABLE IF NOT EXISTS proposal_retrospectives (
    retro_id          SERIAL PRIMARY KEY,
    proposal_id       INT  NOT NULL REFERENCES approval_proposals(proposal_id) ON DELETE CASCADE,
    experiment_id     TEXT NOT NULL,
    decision          TEXT NOT NULL,
    fwd_days          INT  NOT NULL,
    fwd_return        REAL NOT NULL,
    fwd_baseline_diff REAL NOT NULL,
    hypothesis        TEXT NOT NULL DEFAULT '',
    evidence_summary  TEXT NOT NULL DEFAULT '',
    realized_summary  TEXT NOT NULL DEFAULT '',
    lesson            TEXT NOT NULL DEFAULT '',
    confidence        REAL NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retro_exp ON proposal_retrospectives(experiment_id);
CREATE INDEX IF NOT EXISTS idx_retro_decision ON proposal_retrospectives(decision);

-- ════════════════════════════════════════════════════════════
--  v4.1 Phase 2A: 指数 K 线 + ETF K 线 + Drift PSI/KL
-- ════════════════════════════════════════════════════════════

-- 指数 K 线
CREATE TABLE IF NOT EXISTS index_kline (
    symbol      TEXT    NOT NULL,
    name        TEXT,
    trade_date  TEXT    NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    source      TEXT    DEFAULT 'akshare',
    updated_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_index_kline_date      ON index_kline(trade_date);
CREATE INDEX IF NOT EXISTS idx_index_kline_sym_date  ON index_kline(symbol, trade_date);

-- ETF K 线
CREATE TABLE IF NOT EXISTS etf_kline (
    code        TEXT    NOT NULL,
    name        TEXT,
    trade_date  TEXT    NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    source      TEXT    DEFAULT 'akshare',
    updated_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_etf_kline_date      ON etf_kline(trade_date);
CREATE INDEX IF NOT EXISTS idx_etf_kline_code_date ON etf_kline(code, trade_date);

-- Index 同步审计
CREATE TABLE IF NOT EXISTS index_sync_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type      TEXT    NOT NULL,
    target_count  INTEGER NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count  INTEGER NOT NULL DEFAULT 0,
    status        TEXT    DEFAULT 'running',
    error_summary TEXT    DEFAULT '',
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_isync_runs_started ON index_sync_runs(started_at);

CREATE TABLE IF NOT EXISTS index_sync_run_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL,
    symbol        TEXT    NOT NULL,
    sync_type     TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    rows_upserted INTEGER NOT NULL DEFAULT 0,
    error_message TEXT    DEFAULT '',
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_isync_items_run ON index_sync_run_items(run_id);

-- ETF 同步审计
CREATE TABLE IF NOT EXISTS etf_sync_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type      TEXT    NOT NULL,
    target_count  INTEGER NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count  INTEGER NOT NULL DEFAULT 0,
    status        TEXT    DEFAULT 'running',
    error_summary TEXT    DEFAULT '',
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_esync_runs_started ON etf_sync_runs(started_at);

CREATE TABLE IF NOT EXISTS etf_sync_run_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL,
    code          TEXT    NOT NULL,
    sync_type     TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    rows_upserted INTEGER NOT NULL DEFAULT 0,
    error_message TEXT    DEFAULT '',
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_esync_items_run ON etf_sync_run_items(run_id);

-- 漂移事件 (PSI / KL)
CREATE TABLE IF NOT EXISTS drift_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_name     TEXT    NOT NULL,
    metric_type     TEXT    NOT NULL,
    value           REAL    NOT NULL,
    baseline_value  REAL,
    threshold_warn  REAL    NOT NULL,
    threshold_severe REAL   NOT NULL,
    severity        TEXT    NOT NULL,
    snapshot_at     TEXT    NOT NULL,
    baseline_as_of  TEXT    NOT NULL,
    n_baseline      INTEGER NOT NULL,
    n_current       INTEGER NOT NULL,
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_drift_factor_created  ON drift_events(factor_name, created_at);
CREATE INDEX IF NOT EXISTS idx_drift_severity_created ON drift_events(severity, created_at);

-- v4.1 Phase 2B: 阈值版本化
CREATE TABLE IF NOT EXISTS drift_policies (
    policy_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    version         TEXT    NOT NULL UNIQUE,
    psi_warn        REAL    NOT NULL,
    psi_severe      REAL    NOT NULL,
    kl_warn         REAL    NOT NULL,
    kl_severe       REAL    NOT NULL,
    bins            INTEGER NOT NULL DEFAULT 10,
    effective_from  TEXT    NOT NULL,
    effective_to    TEXT,
    created_by      TEXT    NOT NULL DEFAULT 'system',
    note            TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drift_policy_effective ON drift_policies(effective_from);
