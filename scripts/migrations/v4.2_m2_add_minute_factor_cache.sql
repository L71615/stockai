-- ============================================================
-- StockAI v4.2 M2 Migration: 分钟级 55 因子缓存
-- 发布日: 2026-08-03
-- 用途: 手动 apply 到 dev DB (database/stockai.db)
--   sqlite3 database/stockai.db < scripts/migrations/v4.2_m2_add_minute_factor_cache.sql
-- 注意:
--   minute_factor_cache 表已由 backend/database.py:init_db() 自动创建
--   此 migration 仅用于已经存在但版本陈旧的 dev DB 同步场景
-- ============================================================

-- minute_factor_cache(若不存在)
CREATE TABLE IF NOT EXISTS minute_factor_cache (
    stock_code  TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    value       REAL,
    ts          REAL NOT NULL,
    PRIMARY KEY (stock_code, factor_name)
);

-- 索引(若不存在)
CREATE INDEX IF NOT EXISTS idx_mfc_code ON minute_factor_cache(stock_code);
CREATE INDEX IF NOT EXISTS idx_mfc_ts ON minute_factor_cache(ts);

-- 验证
SELECT 'v4.2 M2 migration applied' AS status,
       (SELECT COUNT(*) FROM minute_factor_cache) AS minute_factors_count;