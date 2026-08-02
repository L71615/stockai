# StockAI v4.2 — T+1 watcher N 态机 + 事件溯源 (M1)

**发布日: 2026-08-02**
**代号: v4.2 M1**
**Commit: `abe2dec`**

> **v4.2 战略**: 在 v5.0-alpha(已完成)与 v5.0-beta 之间插入增量 — 补 T+1 watcher 状态机 N 态化 + 事件溯源 + 因子分钟级(M2 后续)。
> 触发条件来自 `v5.0-strategy.md §3.2`「若上面任意 2 项需要 ≥ 1 周,先开 v4.2」。

---

## 🎯 v4.2 M1 一句话

把 `t1_watcher` 的 5 态简化状态机升级到 **6 态 OSS OMS 风格**,加 **白名单 + 守卫函数 + 事件溯源表**,让每笔订单的生命周期可审计、可回放。

---

## ✨ 核心交付

### 1️⃣ 6 态状态机(OSS 风格)

| 新字面量 | 替代老字面量 | 含义 |
|---|---|---|
| `open` | `pending_buy` / `pending_sell` | 未成交(含买/卖挂单) |
| `partial_filled` | (新增) | 部分成交 |
| `filled` | `bought` | 已成交(持仓中) |
| `closed` | `sold` | 已卖出结算完成 |
| `cancelled` | (不变) | 用户取消 |
| `rejected` | (新增) | broker/系统拒绝 |

**白名单**(12 条合法转换):

```
open → partial_filled / filled / cancelled / rejected
partial_filled → filled / open (撤单重挂) / cancelled / rejected
filled → closed / cancelled (极端平仓)

closed / cancelled / rejected → 终态,不能转出
```

### 2️⃣ `transition()` 守卫函数

所有订单状态变更的**统一入口** — 确保:

1. `from → to` 在白名单(非法转换抛 `ValueError`)
2. CAS 校验 `expected_status`(防并发覆盖)
3. 写 `t1_order_events` 审计行(append-only)

```python
from services.t1_watcher import transition

# 同事务内调用(支持 caller 提供 cursor)
transition(
    order_id=123,
    target=STATUS_FILLED,
    actor="scheduler",
    event_type="filled",
    reason="模拟买入成交 @ 100.10",
    cur=cur,  # 可选
)
```

### 3️⃣ 事件溯源表 `t1_order_events`

```sql
CREATE TABLE t1_order_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       INTEGER NOT NULL REFERENCES t1_pending_orders(id) ON DELETE CASCADE,
    actor          TEXT    NOT NULL DEFAULT 'system',
    event_type     TEXT    NOT NULL,                    -- 'transition' / 'risk_blocked' / 'cancel' / 'filled' / 'closed' / 'partial_filled'
    from_status    TEXT,                                 -- 原样记录(老字面量可追溯)
    to_status      TEXT,
    filled_shares  INTEGER,
    pending_shares INTEGER,
    reason         TEXT    NOT NULL DEFAULT '',
    metadata_json  TEXT    NOT NULL DEFAULT '{}',       -- risk_blocked 存 risk_result
    created_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_t1_ev_order ON t1_order_events(order_id);
CREATE INDEX idx_t1_ev_time  ON t1_order_events(created_at);
CREATE INDEX idx_t1_ev_type  ON t1_order_events(event_type);
```

### 4️⃣ partial_filled 字段支持 bulk_approve 资金不足

`t1_pending_orders` 加 2 列:

- `filled_shares INTEGER NOT NULL DEFAULT 0` — 已成交股数
- `pending_shares INTEGER` — 挂单剩余股数

`bulk_approve` 资金不足场景真正支持 partial_filled / rejected(留 v4.2.x 实现,需 cash 表基建)。

### 5️⃣ 查询层双谓词兼容 — 老数据 0 迁移

```sql
-- 老字面量 pending_buy + 新字面量 open 都查到
SELECT * FROM t1_pending_orders
WHERE status IN ('open', 'pending_buy', 'pending_sell');
```

- `process_pending_buys` / `process_pending_sells` 双谓词
- `get_user_orders(status='open')` 自动展开老字面量
- `summarize_user_pnl` by_status 按新名字聚合 + 重新算 avg

**老记录字面量保留** — 跨 deployment 期间不丢数据。

---

## 📁 文件清单

### 改

| 文件 | 改动 |
|---|---|
| `backend/database.py` | 新表 `t1_order_events` DDL + 3 索引 + `filled_shares` / `pending_shares` ALTER 兜底 |
| `backend/services/t1_watcher.py` | 6 态常量 + 白名单 + `transition()` + 4 处状态变更点 + 8 处查询双谓词 + 老 alias 常量保留 |
| `database/schema.sql` | PG/MySQL 兼容的新表 + 新列 DDL |
| `database/schema.sqlite.sql` | SQLite 新表 + 新列 DDL + 状态机升级注释 |
| `tests/test_t1_watcher.py` | 5 处断言更新到新字面量 + import 加 alias |
| `stockai-project-docs/CHANGELOG.md` | v4.2 M1 章节(顶部) |

### 新

| 文件 | 改动 |
|---|---|
| `tests/test_t1_watcher_n_state.py` | **30 个测试** — N 态机核心 + audit + 双谓词兼容 |
| `scripts/migrations/v4.2_m1_add_t1_order_events.sql` | dev DB 手动 apply migration |

---

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `tests/test_t1_watcher_n_state.py` (新) | **30/30** | N 态机核心 + audit + 双谓词兼容 |
| `tests/test_t1_watcher.py` (现有回归) | 16/16 | 老字面量 alias + 5 处断言更新 |
| `tests/test_t1_watcher_risk.py` (现有回归) | 10/10 | 风控集成零回归 |
| `tests/test_pipeline_source_field.py` (现有回归) | 4/4 | source/proposal_id 兼容零回归 |
| **总计 v4.2 M1** | **60/60** | |

**E2E 验证**: 脚本检查老字面量 pending_buy → 合法迁移到 filled → audit event 写库 + closed 终态保护 OK + partial_filled 字段持久化正确。

---

## 📐 关键设计要点

### transition 与 execute_transaction 协调

`_simulate_buy` 事务内做 4 步(写 transactions + 更新 holdings + UPDATE order + notify)。N 态后 `transition` 需要写 audit,**必须和 order UPDATE 同事务**:

```python
def transition(*, order_id, target, ..., cur=None) -> dict:
    """cur 可选 — 若提供,在 caller 事务内执行;否则自己 execute_transaction"""
```

### audit 失败不阻塞主流程

`append_event` 内部异常 `try/except` 兜底,log warning 不抛(防御性)。

### 老字面量 alias

```python
# v4.2 M1: 老字面量 alias (deprecated, 让现有 from-import 不破坏)
STATUS_PENDING_BUY  = "pending_buy"   # deprecated: 用 STATUS_OPEN
STATUS_BOUGHT       = "bought"        # deprecated: 用 STATUS_FILLED
STATUS_PENDING_SELL = "pending_sell"  # deprecated: 用 STATUS_OPEN
STATUS_SOLD         = "sold"          # deprecated: 用 STATUS_CLOSED
# STATUS_CANCELLED 不变(终态语义保持)
```

### summary by_status 归一化

```python
LEGACY_STATUS_MAP = {
    "pending_buy": "open", "pending_sell": "open",
    "bought": "filled", "sold": "closed",
}

# by_status 自动按新名字聚合, 老字面量不独立成 key
```

---

## 🚧 已知限制 / 不在本 M1 范围

| 项 | 现状 | 后续 |
|---|---|---|
| Cash 表 + 真正可用现金跟踪 | ❌ 未做(用 settings 表占位) | v4.2.x |
| Partial_filled 状态的 ticker 检测补成交 | ❌ 未做 | v4.2.x |
| OSS OMS 的 timeout + retry 撤单 | ❌ 未移植 | v4.2.x |
| 前端 status badge 显示新状态字面量 | ❌ 未做 | v5.0-beta M8 |
| Pipeline 反事实报告按策略切分(§3.2 第 4 项) | ❌ 跳过 | v4.3+ |

---

## 🛣 下一步

- **v4.2 M2**: 因子分钟级(`factor_service` 55 因子完整对齐 + `compute_minute_factors()` + `minute_factor_cache` 缓存层,~1.5 周 / ~15 测试)
- **v4.2.x**: bulk_approve partial_filled 真正实现 + cash 表基建
- **v5.0-beta**: M5 WS 推送 / M6 分钟级 K 线 / M7 55 因子接入 / M8 多用户 / M9 通知集成

---

## 📚 相关文档

- [`CHANGELOG.md`](CHANGELOG.md) — 完整日志(含历史 v4.0/v4.1/v5.0-alpha)
- [`2026-08-01-v5.0-strategy.md`](2026-08-01-v5.0-strategy.md) — v5.0 战略 + v4.2 触发条件
- [`RELEASE-NOTES-v5.0.md`](RELEASE-NOTES-v5.0.md) — v5.0-alpha release notes
- [`INDEX.md`](../INDEX.md) — 项目入口

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**