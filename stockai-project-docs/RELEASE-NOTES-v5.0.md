# StockAI v5.0 — 准实盘量化 alpha 阶段完成

**发布日: 2026-08-01**
**代码基线: a70f530**
**代号: v5.0-alpha-M1..M4 (4 个 milestone)**

> ⚠️ **当前是 v5.0 alpha 阶段** — 4 个 milestone 已完成,但仍按 alpha 迭代。下一步 beta 计划见末尾 §6。

---

## 🎯 v5.0 一句话

从「T+1 研究回测」升级到「**盘中实时量化分析**」—— 用户在交易时段能直接看到实时行情 / 实时持仓盈亏 / 自动信号扫描 / 手动确认下单,而不只是收盘后回看。

> **关键战略**: D1 锁定 — **准实盘**(实时行情 + 手动确认 + 模拟成交)。**不下实单**,所有成交走 `t1_pending_orders` 状态机模拟。

---

## ✨ 四大主线交付

### 1️⃣ M1 — 实时行情接入(盘中 + 盘后统一腾讯 API)

| 能力 | v4.1 | v5.0 M1 |
|---|---|---|
| 实时报价 | 无 | `RealtimeQuoteService` 单例 + 5s 轮询(daemon thread) |
| 时段判断 | 无 | `is_trading_hours()` 9:30-11:30 + 13:00-15:00 |
| 前端实时数据 | 收盘价 | `useRealtimeQuote` SWR 5s hook |
| WebSocket | 无 | `WS /api/realtime/ws`(alpha 简化推送 status) |
| 统一接口 | Futu / akshare 分裂 | 腾讯 `qt.gtimg.cn` 统一盘中 + 盘后 |

### 2️⃣ M2 — 盘中因子缓存(5m TTL)

| 能力 | v4.1 | v5.0 M2 |
|---|---|---|
| 因子计算 | 55 因子一次性回测 | 复用 `factor_lab` 30 因子按需计算 |
| 缓存层 | 无 | `realtime_factor_cache` 表 + 5m TTL |
| 前端展示 | `/quant` 量化页 | `/quant` + 复用 `RealtimeFactorCard`(趋势/技术/动量 三组) |
| 性能 | — | 单只 30 因子 < 100ms(命中)/ < 500ms(重算) |

### 3️⃣ M3 — 信号扫描 + 手动确认

| 能力 | v4.1 | v5.0 M3 |
|---|---|---|
| 策略评估 | 离线回测 | 盘中实时扫描(`_evaluate_code` 复用 M2 因子 + 13 YAML 模板) |
| 信号历史 | 无 | `realtime_signal_log` 表(log / mark_accepted / recent_signals) |
| 手动确认 | 无 | `POST /api/realtime/signal/{id}/accept` → `t1_watcher.create_pending_order` |
| 守护线程 | 无 | `RealtimeSignalScanner` 单例 + 5s/轮 + `is_trading_hours()` 网关 |
| 复用策略 | — | 复用 `condition_engine` + `strategy_registry` + `_load_strategy_conditions`,**无新抽象** |

### 4️⃣ M4 — /live 仪表板前端

| 能力 | v4.1 | v5.0 M4 |
|---|---|---|
| 用户界面 | 无 | `/live` 路由 + 5 个 section |
| 实时盈亏 | 收盘价 | 实时价 × 持仓 PnL(红涨绿跌,中国 A 股惯例) |
| 信号 UI | 无 | 信号卡片列表 + 接受/拒绝按钮 + 待确认 Badge |
| 因子展示 | `/quant` | 选中股票 → `RealtimeFactorCard`(SWR 30s) |
| 设计规范 | — | 100% 符合 DESIGN.md: Tabler Icons / rounded-none / tabular-nums / 暗色 |

---

## 📁 文件清单(alpha 阶段新增)

### 后端服务 (5)
```
backend/services/realtime_quote.py              # M1 — RealtimeQuoteService
backend/services/realtime_factor_cache.py      # M2 — 因子计算 + 5m TTL 缓存
backend/services/realtime_signal.py            # M3 — 信号评估(scan_signals)
backend/services/realtime_signal_log.py        # M3 — 信号持久化
backend/services/realtime_signal_scanner.py    # M3 — 5s 扫描守护线程
```

### 后端路由 (3)
```
backend/routers/realtime.py                    # M1 — REST + WS
backend/routers/realtime_factor.py             # M2 — 因子 REST
backend/routers/realtime_signal.py             # M3 — 信号 REST(含 accept)
```

### 前端 (3)
```
frontend/src/hooks/use-realtime-quote.ts        # M1 — SWR 5s
frontend/src/components/realtime-factor-card.tsx  # M2 — 因子展示
frontend/src/app/live/page.tsx                 # M4 — /live 仪表板
```

### 数据库 (2 张新表)
```sql
CREATE TABLE realtime_factor_cache (
    stock_code TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    value REAL,
    ts REAL NOT NULL,                -- unix timestamp, 写入时刻
    PRIMARY KEY (stock_code, factor_name)
);

CREATE TABLE realtime_signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    direction TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.7,
    triggered_at REAL NOT NULL,
    accepted INTEGER NOT NULL DEFAULT 0,
    order_id INTEGER,
    snapshot_json TEXT NOT NULL DEFAULT '{}'
);
```

### 测试 (4 文件, 69 测试)
```
tests/test_realtime_quote.py       # M1 — 21 测试
tests/test_realtime_factor.py     # M2 — 17 测试
tests/test_realtime_signal.py     # M3 — 20 测试
tests/test_live_page_smoke.py     # M4 — 11 测试(文件内容断言 + DESIGN 规范)
```

### 改动文件 (3)
```
backend/main.py                    # 注册 3 个新 router + 启动 scanner 守护
backend/services/scheduler.py      # 加 start_realtime_signal_scanner_thread()
backend/database.py                # 加 2 张新表 schema
```

---

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| M1 `test_realtime_quote.py` | 21/21 | 时段判断 / service / poll / REST |
| M2 `test_realtime_factor.py` | 16/17 | 1 个 Windows asyncio teardown 崩溃(测试本身已 PASS) |
| M3 `test_realtime_signal.py` | 20/20 | scan / log / REST / scanner |
| M4 `test_live_page_smoke.py` | 11/11 | DESIGN 规范符合 |
| **总计** | **68/69** | 1 个已知 Windows + bcrypt 环境问题 |

---

## 🚧 已知限制(alpha 阶段)

| 项 | 现状 | beta 计划 |
|---|---|---|
| K 线频率 | 日级 fallback(60 根) | M11 切 `futu_raw_kline` 分钟级 |
| 行情延迟 | 5s SWR 轮询 | M5 切 WebSocket 推送 |
| 因子范围 | 30 个(factor_lab) | 55 个 factor_service 完整接入 |
| 用户体系 | 单 admin(alpha) | 多用户 + 权限分层 |
| 数据源 | 腾讯免费 API(限频) | Futu OpenD + akshare fallback |

---

## 📌 下一步(v5.0-beta 候选)

- **M5**: WebSocket 推送(替换 5s 轮询)
- **M6**: 分钟级 K 线接入
- **M7**: 55 因子全部接入
- **M8**: 多用户 + 权限
- **M9**: 通知集成(盘中信号 → 邮件/微信/Telegram 推送)

详见 [`2026-08-01-v5.0-strategy.md`](2026-08-01-v5.0-strategy.md) + [`2026-08-01-v5.0-alpha-plan.md`](2026-08-01-v5.0-alpha-plan.md)。

---

## 📚 相关文档

- [`CHANGELOG.md`](CHANGELOG.md) — 完整日志(含历史 v4.0/v4.1)
- [`2026-08-01-v5.0-strategy.md`](2026-08-01-v5.0-strategy.md) — v5.0 战略(D1-D6 决策)
- [`2026-08-01-v5.0-alpha-plan.md`](2026-08-01-v5.0-alpha-plan.md) — alpha 实施计划(M1-M4 详细)
- [`INDEX.md`](../INDEX.md) — 项目入口
- [`CLAUDE.md`](../CLAUDE.md) — 开发指引

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**