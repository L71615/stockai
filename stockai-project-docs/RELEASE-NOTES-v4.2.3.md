# StockAI v4.2.3 — partial_filled 完整处理骨架 (patch)

**发布日: 2026-08-03**
**代码基线: d4c3d44**
**代号: v4.2.3-patch**

> ⚠️ **纯 patch** — 不引入新功能/新表/新接口,只补全 `partial_filled` 状态的代码路径(之前 v4.2 M1 已加状态字段/白名单/审计,这次把 `_simulate_buy` 真正接上)。

---

## 🎯 v4.2.3 一句话

把 `partial_filled` 状态从"有字段 + 有白名单 + 有审计,但没代码用"升级为"可调用的 API + 完整测试覆盖"。bulk_approve 真正接资金校验仍留 v5.0-beta M8(需 cash 表基建)。

---

## ✨ Feat

### partial_filled 完整处理骨架 — commit `d4c3d44`

| API | 修改前 | 修改后 |
|---|---|---|
| `_simulate_buy(order, price)` | 总是全成交 → STATUS_FILLED | 接受 `partial_shares=None/N` 参数,N < requested 时走 STATUS_PARTIAL_FILLED + 写 filled_shares/pending_shares |
| `try_fill_pending_order(order_id, *, open_price, partial_shares)` | **不存在** | 新增 helper:给 partial_filled 订单补成交的外部入口(测试 + broker 回调可用),自动按 pending_shares 全量补或指定补部分 |
| `process_pending_buys(today)` | 不扫 partial_filled | SQL 增加 partial_filled 扫描,补成交时只成交 pending_shares(非 requested_shares) |
| `_ALLOWED_TRANSITIONS` | `partial_filled` 出度不含自身 | 加 `partial_filled → partial_filled`(补成交合法状态不变,审计照常) |
| 风控 `proposed_value` | 始终按 requested_shares | partial_filled 时按补成交金额算,避免重复计 |

### 关键设计

- **不引入 cash 表**:沿用 P3 最小改动原则,partial_filled 是"有 API 可调",但 bulk_approve 路径仍默认全成交
- **补成交原子性**:复用现有 `_simulate_buy` 单事务封装(holdings + transactions + transition 同事务)
- **审计完整性**:补成交事件走 `event_type="partial_filled"` 写入 `t1_order_events`,与第一次 partial_filled 同 `event_type`
- **白名单开放**:`partial_filled → partial_filled` 显式列入 `_ALLOWED_TRANSITIONS`,让 transition 守卫不抛

### 已知局限

| 项 | 状态 |
|---|---|
| `bulk_approve` 真正接资金校验 | ❌ 仍默认全成交 — 需 cash 表基建,留 v5.0-beta M8 |
| 前端 status badge 显示 `partial_filled` | ❌ 留 v5.0-beta M8 |
| `try_fill_pending_order` REST API 暴露 | ❌ 当前仅 internal 函数 — 外部 broker 回调接入留 v5.0-beta M9 |

---

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| **v4.2.3 新增** `test_t1_watcher_partial_filled.py` | **19/19** | _simulate_buy partial_shares 边界 + try_fill_pending_order 5 场景 + process_pending_buys 集成 + 白名单 |
| v4.2 M1 `test_t1_watcher_n_state.py` | 30/30 | 6 态机 + transition() 守卫 |
| v4.2 M2 `test_factor_service_minute.py` | 25/25 | MINUTE_FACTOR_REGISTRY + compute_minute_factors + 5m TTL |
| v4.2.2 patch 引入的 live 集成 | 11/11 | /live 仪表板 |
| realtime_signal / minute-factor / live-page smoke | 49/49 | 现有回归 |
| **总计** | **134/134** | patch 无现有回归 |

---

## 📁 文件清单(本 patch)

| 类别 | 文件 | 改动 |
|---|---|---|
| **feat** | `backend/services/t1_watcher.py` | _simulate_buy 加 partial_shares kwarg + process_pending_buys 扫 partial_filled + 新增 try_fill_pending_order helper + 白名单加 partial_filled → partial_filled (157 LOC) |
| **test** | `tests/test_t1_watcher_partial_filled.py` | 新建 19 个测试,~280 LOC |

---

## 📌 下一步

- **v5.0-beta M5** — WebSocket 推送(替换 5s 轮询,~1 周)
- **v5.0-beta M6** — 分钟级 K 线接入(`futu_raw_kline` 1m/5m)
- **v5.0-beta M8** — 多用户 + 权限分层 + bulk_approve 接 cash 表 + 前端 partial_filled badge

详见 [`2026-08-01-v5.0-strategy.md`](../2026-08-01-v5.0-strategy.md) + [`RELEASE-NOTES-v5.0.md`](RELEASE-NOTES-v5.0.md)。

---

## 📚 相关文档

- [`RELEASE-NOTES-v4.2.md`](RELEASE-NOTES-v4.2.md) — v4.2 M1 release notes
- [`RELEASE-NOTES-v4.2-m2.md`](RELEASE-NOTES-v4.2-m2.md) — v4.2 M2 release notes
- [`RELEASE-NOTES-v4.2.2.md`](RELEASE-NOTES-v4.2.2.md) — v4.2.2 patch (5 commit)
- [`CHANGELOG.md`](../CHANGELOG.md) — 完整日志
- [`CLAUDE.md`](../../CLAUDE.md) — 开发指引
- [`INDEX.md`](../../INDEX.md) — 项目入口

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>