-- ============================================================
-- StockAI v4.2 M1 Migration: T+1 watcher 事件溯源 + 状态升级
-- 发布日: 2026-08-02
-- 用途: 手动 apply 到 dev DB (database/stockai.db)
--   sqlite3 database/stockai.db < scripts/migrations/v4.2_m1_add_t1_order_events.sql
-- 注意:
--   1. 数据库新表 t1_order_events 已由 backend/database.py:init_db() 自动创建
--      此 migration 仅用于已经存在但版本陈旧的 dev DB 同步场景
--   2. 老 t1_pending_orders.status 数据保留字面量(pending_buy/bought/sold/cancelled)
--      新代码查询用双谓词兼容,无需 UPDATE 迁移
-- ============================================================

-- 1. t1_pending_orders 加 partial_filled 字段
ALTER TABLE t1_pending_orders ADD COLUMN filled_shares INTEGER NOT NULL DEFAULT 0;
ALTER TABLE t1_pending_orders ADD COLUMN pending_shares INTEGER;

-- 2. t1_order_events 表(若不存在)
CREATE TABLE IF NOT EXISTS t1_order_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       INTEGER NOT NULL REFERENCES t1_pending_orders(id) ON DELETE CASCADE,
    actor          TEXT    NOT NULL DEFAULT 'system',
    event_type     TEXT    NOT NULL,
    from_status    TEXT,
    to_status      TEXT,
    filled_shares  INTEGER,
    pending_shares INTEGER,
    reason         TEXT    NOT NULL DEFAULT '',
    metadata_json  TEXT    NOT NULL DEFAULT '{}',
    created_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 3. t1_order_events 索引(若不存在)
CREATE INDEX IF NOT EXISTS idx_t1_ev_order ON t1_order_events(order_id);
CREATE INDEX IF NOT EXISTS idx_t1_ev_time  ON t1_order_events(created_at);
CREATE INDEX IF NOT EXISTS idx_t1_ev_type  ON t1_order_events(event_type);

-- 验证
SELECT 'v4.2 M1 migration applied' AS status,
       (SELECT COUNT(*) FROM t1_order_events) AS events_count,
       (SELECT COUNT(*) FROM t1_pending_orders) AS orders_count;