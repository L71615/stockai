# StockAI 项目日志

> StockAI 从 0 到 v4.2 的完整演进记录。按时间倒序。
> **当前版本: v4.2.4**(2026-08-05 tag) — leaderboard 超时修复 + 5min 缓存 + `async def` 漏改修复(`70f9dc3`)
> **上一稳定版**: v4.2.3(2026-08-03)— partial_filled 完整处理骨架(1 feat + 19 测试)
> **再上一稳定版**: v4.2.2(2026-08-03)— v4.2.1 patch(2 bug fix + 1 feat + 2 docs)
> **再上一稳定版**: v4.2.1(2026-08-03)— T+1 watcher N 态(M1) + 因子分钟级 55 因子(M2)
> **下一阶段**: v5.0-beta(M5 WS 推送 / M6 分钟级 K 线 ✅ / M7 55 因子 ✅ / M9 通知集成)

---

## v5.0-beta-M7 — 2026-08-05

**代号**: v5.0-beta M7 — 55 因子完整接入
**代码基线**: 235f20b
**范围**: `services/realtime_factor_cache.py` in-place 升级 30→55 因子

### 关键改动

- **feat(55_factors)**: `compute_realtime_factors()` 转发到 `factor_service.compute_minute_factors`(55 因子 + 5 元组分发)
- **feat(55_factors)**: `fetch_recent_bars()` 改返 `((closes, highs, lows, opens, volumes), data_source)` 2 元组
- **feat(55_factors)**: 复用 M6 灰度开关 `REALTIME_USE_MINUTE_BARS` + 3 函数拆分模式 (`_fetch_minute_bars` / `_fetch_daily_bars` / `_to_series`)
- **feat(router)**: `/api/realtime/factor/{code}` 解包 5 元组 + 新增 `data_source` 字段
- **test(55_factors)**: 新增 20 个 mock 测试 (M6 30 回归仍通过)
- **test(conftest)**: test_db fixture 加 `realtime_factor_cache` 表 schema

### 双 cache 表共存

| 表 | 接口 | 因子 | 来源 |
|----|------|------|------|
| `realtime_factor_cache` | `/api/realtime/factor/{code}` | **55** (M7 升级) | alpha M1 接口 |
| `minute_factor_cache` | `/api/realtime/factor/{code}/minute` | 55 | M6 已就位 |

### 不变项

- `factor_service.compute_minute_factors` 不动(已实现)
- `realtime_factor_minute.py` 不动(M6 已 55 因子)
- 前端不动(因子数据更全,UI 不变)
- `factor_lab.py` 30 因子保留(alpha M2 screener 用)

### 验收

- 20/20 测试通过 (M7)
- 30/30 测试仍通过 (M6 回归)
- 手动验证 `curl /api/realtime/factor/600519` 返 55+ 因子 + data_source 字段

---

## v5.0-beta-M6 — 2026-08-05

**代号**: v5.0-beta M6 — 分钟级 K 线接入
**代码基线**: 9241c29
**范围**: `services/realtime_factor_minute.py:fetch_recent_bars()` 灰度切 1m 分钟级

### 关键改动

- **feat(minute_bars)**: `fetch_recent_bars()` 拆出 `_fetch_minute_bars` / `_fetch_daily_bars` / `_to_series` 三函数
- **feat(minute_bars)**: 环境变量 `REALTIME_USE_MINUTE_BARS` 灰度开关(默认 `false`)
- **feat(minute_bars)**: Futu 分钟表空 → 自动 fallback 日级(永不返 503)
- **feat(router)**: `data_source` 字段从函数返回值取,值域 `{futu_1m, historical_daily_fallback}`
- **chore(env)**: `.env.example` 加 `REALTIME_USE_MINUTE_BARS=false`
- **test(minute_bars)**: 新增 30 个 mock 测试

### 不变项

- `run_intraday_sync()` 保持 5min 同步
- `sync_minute_kline()` 不动
- `futu_raw_kline` schema 不动
- 因子计算 `compute_minute_factors` 不动

### 验收

- 30 个测试全过
- 灰度切换零停机(`.env` 改 env 即可)
- staging 观察 1 周再 prod 启用

---

## 2026-08-05 — v4.2.4 (patch: leaderboard 超时修复 + 5min 缓存 + async def 漏改)

### 🆕 feat: leaderboard 向量化 + 缓存层

**触发**:`/api/factor-lab/leaderboard` 55 因子 × 240 天全量计算 ~90s,客户端 60s timeout 必 500。

| 改动 | 内容 |
|------|------|
| `_pearson_daily` | per-date 循环 → NumPy 矩阵(~0.3s → ~0.015s) |
| `decay` 1d/5d/10d/20d | 同样向量化,复用模式(~12s → <0.1s) |
| 默认窗口 | 365 → 240 天(减 33% 数据量,仍 > 200 有效 IC 天) |
| `get_cached_leaderboard()` | 5min TTL 内存缓存 + per-key `asyncio.Lock` 防并发双算 |
| `invalidate_leaderboard_cache()` | helper,后续接入调度触发 |
| Router `_cache` 字段 | 透出 `hit`/`miss` 给前端排查 |

### 🐛 fix: async def 漏改导致后端 ECONNREFUSED

**症状**: 前端 `/api/stocks/holdings/with-pnl` → HTTP 500,错误 `AggregateError: connect ECONNREFUSED ::1:3000`。后端 3000 端口完全无人监听。

**根因**:`backend/routers/factor_lab.py:81` 函数体加 `await get_cached_leaderboard(...)` 但函数签名是 `def` 而非 `async def` → **SyntaxError** → Python 解释器 import main.py 阶段崩溃 → uvicorn 卡在 `Waiting for application startup`。

**修复**: 单行改动 `def get_leaderboard` → `async def get_leaderboard`。

**验证**:
- `python -c "import main"` ✅ 无 SyntaxError
- uvicorn 启动 ✅ Application startup complete,3000 LISTENING
- `GET /api/health` ✅ 200 (17ms)
- `GET /api/stocks/holdings/with-pnl` ✅ **200 (5ms)** ← 用户报告失败的接口

### 📌 不在 v4.2.4 范围
- ❌ 缓存持久化(进程重启即失效) — 留 v5.0-beta
- ❌ 缓存自动失效 hook(因子生命周期变化时) — 留 v5.0-beta
- ❌ `test_factor_lab.py` 完整 pytest 覆盖 — 本 patch 用端到端验证代替

### ✅ 回归测试 (`cca034a` — `tests/test_factor_lab_v424.py`)
- **14 个测试**,1.11s 跑完,3 个核心验证:
  - **P0-1** `_pearson_daily` 向量化数值一致性(6 个): 与原 per-date 循环对比,误差 < 1e-9
  - **P0-2** `get_cached_leaderboard` 5min TTL + per-key Lock(7 个): miss/hit/invalidate/TTL 过期/并发
  - **P0-3** 向量化性能 smoke(1 个): 向量化应至少快 5x
- 不依赖数据库,纯 DataFrame + monkeypatch,CI 友好

### 📚 详见
- [`RELEASE-NOTES-v4.2.4.md`](RELEASE-NOTES-v4.2.4.md)
- commit `70f9dc3`(代码)+ `cca034a`(测试)+ `3006835`(gitignore)

---

## 2026-08-03 — v4.2.3 (patch: partial_filled 完整处理骨架)

### 🆕 feat: partial_filled 状态从"有字段"升级为"可调用 API"

**触发**: v4.2 M1 加了 STATUS_PARTIAL_FILLED 状态常量 + 白名单 + filled_shares/pending_shares 字段,但 `_simulate_buy` 仍默认全成交。本次 patch 把代码路径补全。

| API | 改动 |
|---|---|
| `_simulate_buy(order, price, *, partial_shares)` | 加 `partial_shares` kwarg,N < requested 时走 STATUS_PARTIAL_FILLED + 写 filled/pending |
| `try_fill_pending_order(order_id, *, open_price, partial_shares)` | 新增:给 partial_filled 订单补成交的外部入口 |
| `process_pending_buys(today)` | SQL 增加 partial_filled 扫描 + 风控按补成交金额算 |
| `_ALLOWED_TRANSITIONS` | 加 `partial_filled → partial_filled`(补成交合法状态不变) |

### ✅ 测试验收
- **19 个新测试**(`tests/test_t1_watcher_partial_filled.py`)
- **134/134 全过**(无现有回归)

### 📌 不在 v4.2.3 范围
- ❌ bulk_approve 真接资金校验 — 需 cash 表基建,留 v5.0-beta M8
- ❌ 前端 status badge 显示 partial_filled — 留 v5.0-beta M8
- ❌ try_fill_pending_order REST 暴露 — 留 v5.0-beta M9

---

## 2026-08-03 — v4.2.2 (patch: v4.2.1 后续 5 个 commit 打包)

### 🆕 修复/增强/文档同步

**触发**: v4.2.1 打完 tag 后临时累积的 5 个 commit(2 bug fix + 1 feat + 2 docs),无新功能/新表/新接口。

| 类型 | Commit | 说明 |
|---|---|---|
| bug fix | `52be641` | 因子 key 大小写不匹配 + scanner 默认策略 ID typo(momentum → momentum_leader) |
| bug fix | `a919100` | scanner 默认策略列表扩展 3 → 7 个(覆盖突破/回归/动量/趋势中途/反转/弱反转) |
| feat | `7fc9a6f` | `/live` 第 6 section — 选中股票的分钟级 55 因子卡片 + 百分比自动格式化 |
| docs | `aa0e250` | 三件套 + README.en.md 同步到 v4.2.1 + v5.0-alpha |
| docs | `1a1e359` | 移除 docs/README.md 的 v4.0 ASCII 架构图(描述已过期) |

### ✅ 测试验收
- **212/212 全过**(patch 没改后端代码,全部回归通过)

### 📌 不在 v4.2.2 范围
- ❌ 无新功能 / 新表 / 新接口
- ❌ 无新依赖 / 无 breaking change
- 纯 patch tag

---

## 2026-08-03 — v4.2 M2 (因子分钟级 55 因子完整对齐)

### 🆕 feat: factor_service 55 因子分钟级 + REST + 前端

**触发**: v5.0-strategy.md §3.4 M5「实时因子计算(55 因子分钟级)」前置。

#### 核心交付

| 项 | 文件 | 说明 |
|---|---|---|
| `MINUTE_FACTOR_REGISTRY` (55 因子) | `factor_service.py` | 5 元组 (fn, needs_vol, needs_hilo, needs_open, fn_volumes_only), 与既有 92-key FACTOR_REGISTRY 并存 |
| `compute_minute_factors()` | `factor_service.py` | 复用 55 个 `factor_xxx` 函数(签名天然兼容 `list[float]`), 大写 key 自动归一化, 单因子失败返回 None 不抛 |
| `realtime_factor_minute.py` (新) | `services/` | 5m TTL 缓存 CRUD + `compute_minute_factors_with_cache` + `fetch_recent_bars` (~160 LOC) |
| `minute_factor_cache` 表 | `database.py` | 独立于 `realtime_factor_cache` (5m TTL), 后续 v5.0-rc 可独立调 TTL |
| REST 3 端点 | `routers/realtime_factor_minute.py` | GET `/api/realtime/factor/{code}/minute` + invalidate + factor-names |
| 前端 hook | `hooks/use-realtime-minute-factor.ts` | SWR 30s + 8 组因子分类 |
| 前端组件 | `components/realtime-minute-factor-card.tsx` | 4 组核心因子 + 数据源标识(fallback 黄色 / 真实 绿色) |

#### 数据源
- **临时**: `historical_kline` 日级 fallback (240 根)
- **v5.0-rc M11** 切 `futu_raw_kline` 1m/5m(响应加 `data_source` 字段标记)

### ✅ 测试验收
- **25 个新测试**(`tests/test_factor_service_minute.py`)
- **212/212 全过**(含 187 现有 v4.0/v4.1/v4.2 M1/v5.0-alpha 回归)

### 📌 设计要点
- **fn_volumes_only 第 5 字段**: `factor_vol_ma5(volumes)` 等只接 volumes 的因子显式标记,计算入口据此区分参数构造
- **大写兼容**: 用户传 "MA5" 自动归一化为 "ma5"
- **数据缺失不抛**: K 线因子无 highs/lows 时返 None(不抛),量价因子无 volumes 时返 None
- **与 factor_lab 30 因子并存**: 不动 v5.0-alpha M2 的 factor_lab 路径, M2 走 factor_service 新路径

### 📁 文件清单
- **改** `backend/database.py` (新表 DDL)
- **改** `backend/services/factor_service.py` (新注册表 + compute_minute_factors)
- **改** `backend/main.py` (注册新 router)
- **改** `database/schema.sql` + `schema.sqlite.sql`
- **新** `backend/services/realtime_factor_minute.py`
- **新** `backend/routers/realtime_factor_minute.py`
- **新** `scripts/migrations/v4.2_m2_add_minute_factor_cache.sql`
- **新** `tests/test_factor_service_minute.py`
- **新** `frontend/src/hooks/use-realtime-minute-factor.ts`
- **新** `frontend/src/components/realtime-minute-factor-card.tsx`

### 📌 不在 M2 范围
- ❌ 真正的 `futu_raw_kline` 5m/1m 接入 — 留 v5.0-rc M11
- ❌ 增量更新(每根新 bar 触发) — 留 v5.0-rc M10
- ❌ `/live` 页面集成 — 留 v5.0-beta M8
- ❌ 缓存 TTL 动态配置 — 留 v5.0-rc

---

## 2026-08-02 — v4.2 M1 (T+1 watcher N 态 + 事件溯源)

### 🆕 feat: T+1 订单状态机升级 — 6 态 + 白名单 + 审计

**触发条件**: `v5.0-strategy.md §3.2`「T+1 watcher N 态」+「因子分钟级」各 ≥ 1 周,先开 v4.2。

#### 6 状态(OSS OMS 风格)

| 新字面量 | 替代老字面量 | 含义 |
|---|---|---|
| `open` | `pending_buy` / `pending_sell` | 未成交(含买/卖挂单) |
| `partial_filled` | (新增) | 部分成交 |
| `filled` | `bought` | 已成交(持仓中) |
| `closed` | `sold` | 已卖出结算完成 |
| `cancelled` | (不变) | 用户取消 |
| `rejected` | (新增) | broker/系统拒绝 |

#### 状态转换白名单
- `open` → partial_filled / filled / cancelled / rejected
- `partial_filled` → filled / open (撤单重挂) / cancelled / rejected
- `filled` → closed / cancelled (极端平仓)
- **closed / cancelled / rejected 均为终态**,不能转出

#### 新增 API
- `t1_watcher.transition(*, order_id, target, actor, event_type, reason, ...)` — 统一状态转换入口
  - CAS 校验 expected_status (防并发覆盖)
  - 写入 `t1_order_events` 审计行(append-only)
  - 同一事务内执行(支持 caller 提供 `cur`)
- `_ALLOWED_TRANSITIONS` 字典 — 白名单
- `LEGACY_STATUS_MAP` — 老字面量 → 新名字映射
- `_expand_legacy_status(status)` — 查询层把新名字展开为 [新, 老...] 兼容集合
- `_legacy_status_to_new(status)` — 任意字面量归一化为新名字

#### 新表 `t1_order_events`(事件溯源)

```sql
CREATE TABLE t1_order_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       INTEGER NOT NULL REFERENCES t1_pending_orders(id) ON DELETE CASCADE,
    actor          TEXT    NOT NULL DEFAULT 'system',   -- 'user:1' / 'scheduler' / 'risk_guard' / 'realtime_signal' / 'bulk_approve'
    event_type     TEXT    NOT NULL,                    -- 'transition' / 'risk_blocked' / 'cancel' / 'filled' / 'closed' / 'partial_filled'
    from_status    TEXT,                                 -- 原样记录老字面量(可追溯)
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

#### `t1_pending_orders` 加 2 列(partial_filled 用)
- `filled_shares INTEGER NOT NULL DEFAULT 0`
- `pending_shares INTEGER`

#### 4 处状态变更点改造
| 函数 | 改造 |
|---|---|
| `cancel_order` | 走 `transition(target=cancelled, actor='user:{id}')` |
| `_simulate_buy` | 事务内 `transition(target=filled, actor='scheduler')` + 同步 `executed_entry_price` 等字段 |
| `_simulate_sell` | 事务内 `transition(target=closed, actor='scheduler')` + 同步 `executed_exit_price` / pnl 等字段 |
| `_cancel_blocked_order` | 走 `transition(target=cancelled, actor='risk_guard', event_type='risk_blocked', metadata=risk_result)` |

#### 查询层双谓词兼容
8 处 `t1_pending_orders` 查询改成兼容新旧字面量:
- `process_pending_buys` / `process_pending_sells` 双谓词查询
- `get_user_orders(status=...)` 自动展开同义老字面量
- `summarize_user_pnl` by_status 按新名字聚合 + 重新算 avg_return_pct

**老记录字面量保留**,新代码双谓词兼容 — **0 数据迁移、跨 deployment 期间不丢数据**。

### ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `tests/test_t1_watcher_n_state.py` (新) | **30/30** | N 态机核心 + 审计 + 双谓词兼容 |
| `tests/test_t1_watcher.py` (现有回归) | 16/16 | 老字面量 alias + 测试更新到新字面量 |
| `tests/test_t1_watcher_risk.py` (现有回归) | 10/10 | 风控集成零回归 |
| `tests/test_pipeline_source_field.py` (现有回归) | 4/4 | source/proposal_id 兼容零回归 |
| **总计 v4.2 M1** | **60/60** | |

### 📌 设计要点
- **同事务写入**: `transition(cur=...)` 在 caller 事务内复用 cursor,保证 order UPDATE + event INSERT 原子性
- **audit 失败不阻塞**: audit 内部异常 `try/except` 兜底,log warning 不抛
- **partial_filled 实战场景**: bulk_approve 资金不足(留 v4.2.x — 需 cash 表基建)
- **legacy 兼容**: 老字面量 alias 常量保留(`STATUS_PENDING_BUY = "pending_buy"`),让现有调用方继续工作
- **summary by_status 归一化**: 老字面量 sold/bought/pending_buy/pending_sell 自动归到新名字 key,前端用新名字展示

### 📁 文件清单
- **改** `backend/database.py` (新表 DDL + ALTER 兜底)
- **改** `backend/services/t1_watcher.py` (~250 LOC — 6 态 + transition + 4 处状态变更改造 + 8 处查询双谓词)
- **改** `database/schema.sql` + `database/schema.sqlite.sql` (新表 + 新列同步)
- **新** `scripts/migrations/v4.2_m1_add_t1_order_events.sql` (dev DB 手动 apply)
- **新** `tests/test_t1_watcher_n_state.py` (30 测试,~300 LOC)
- **改** `tests/test_t1_watcher.py` (5 处断言更新到新字面量 + import 加 alias)

### 📌 下一步
- v4.2 M2: 因子分钟级(55 因子完整对齐 + compute_minute_factors + minute_factor_cache)
- bulk_approve partial_filled 实现留 v4.2.x(需 cash 表基建)
- 前端 status badge 显示新状态字面量留 v5.0-beta M8

---

## 2026-08-01 — v5.0 stable (alpha 阶段完成)

### 🏁 tag v5.0 — alpha 阶段完整收尾

**Release Notes**: [`RELEASE-NOTES-v5.0.md`](RELEASE-NOTES-v5.0.md)

v5.0 alpha 阶段 4 个 milestone 全部完成,共交付:

| Milestone | 主题 | 测试 | 核心交付 |
|-----------|------|------|---------|
| M1 | 实时行情接入 | 21 | RealtimeQuoteService + WS + 5s 轮询 |
| M2 | 盘中因子缓存 | 17 | factor_lab 30 因子 + 5m TTL + 因子卡片 |
| M3 | 信号扫描 + 手动确认 | 20 | scan_signals + accept REST + scanner 守护 |
| M4 | /live 仪表板前端 | 11 | 5 个 section + sidebar + DESIGN 规范 |
| **合计** | | **69** | **准实盘量化全链路** |

**关键战略决策**(D1 锁定): 准实盘 — 实时行情 + 手动确认 + 模拟成交,**不下实单**

### 📌 v5.0-beta 候选
- M5: WebSocket 推送(替换 5s 轮询)
- M6: 分钟级 K 线接入(`futu_raw_kline`)
- M7: 55 因子全部接入(`factor_service` 完整版)
- M8: 多用户 + 权限分层
- M9: 通知集成(信号 → 邮件/微信/Telegram)

---

## 2026-08-01 — v5.0-alpha M4 (/live 仪表板前端)

### 🆕 feat: 盘中量化分析仪表板
- **新文件** `frontend/src/app/live/page.tsx` (~440 行)
- **5 个 section**:
  1. **顶部 PnL 总览** — 持仓实时盈亏汇总 + 成本对比 + 盘中/盘后状态徽章
  2. **实时 watchlist 行情** — 5s 刷新,点击选中展示因子卡片
  3. **盘中信号触发列表** — 含待确认数 Badge,逐行"接受"/"拒绝"按钮
  4. **实时持仓表** — 现价 × 数量 实时计算 pnl/pnl_pct
  5. **选中股票因子卡片** — 复用 M2 `RealtimeFactorCard`
- 复用 M1-M3 已有 API/hook:
  - `useRealtimeQuote` (M1) — SWR 5s 拉 `/api/realtime/watchlist`
  - `useRealtimeFactor` (M2) — `RealtimeFactorCard` 组件
  - `apiPost /api/realtime/signal/{id}/accept` (M3) — 手动接受下单

### 🆕 feat: sidebar 入口
- **改动** `frontend/src/components/app-sidebar.tsx`
- "投资"组加 `盘中量化` 入口(`/live`,IconWaveSine 波形图标)
- 紧跟 watchlist / browse / market 之后,符合"实时 → 浏览 → 大盘"使用频率

### ✅ 测试验收
- 11 个 smoke 测试(`tests/test_live_page_smoke.py`):
  - 文件存在 + default export
  - 5 个 section 标识齐全
  - accept + reject API 调用
  - Tabler Icons / rounded-none / tabular-nums 规范符合
  - 中国色惯例(涨红跌绿, `text-red-400` + `text-emerald-400`)
  - 无 emoji 作为功能图标
  - sidebar 含 `/live` 入口 + 中文 label + Tabler Icon
- **11 passed / 0 failed**
- TypeScript 类型检查: live page + sidebar 无错(全工程其他文件 error 与本 milestone 无关,系历史 Playwright 类型缺失等)

### 📌 设计规范符合性
- ✅ 暗色主题(.dark)+ `rounded-none`(DESIGN.md §3)
- ✅ Tabler Icons 全功能图标(无 emoji)— `IconCheck/X/Refresh/Bolt/AlertTriangle/Clock/CircleDot/WaveSine`
- ✅ 数字列 `tabular-nums` (价格/涨跌幅/PnL/百分比)
- ✅ 中国 A 股色惯例(红涨绿跌)
- ✅ 状态徽章区分盘中/盘后(`IconCircleDot animate-pulse`)

### 📌 下一步
- M5: WebSocket 推送(替换 5s 轮询) — alpha 阶段轮询够用,M5 优化延迟
- M6: 分钟级 K 线接入(M11 阶段切 futu_raw_kline)

---

## 2026-08-01 — v5.0-alpha M3 (盘中信号扫描 + 手动确认下单)

### 🆕 feat: 盘中信号扫描服务
- **新文件** `backend/services/realtime_signal.py`
- `RealtimeSignal` dataclass(strategy_id/name/stock_code/direction/score/triggered_at/reason/snapshot)
- `scan_signals(enabled_strategies, candidate_codes)` — 对每只股票跑启用策略,命中返回 Signal
- `_evaluate_code(code, window)` — 拉日级 K 线 + 复用 M2 `compute_factors_with_cache` + 补算 `avg_amount_20d` / `close_vs_high_Nd` / `atr_pct` 等 YAML 策略需要字段
- 复用 `condition_engine.evaluate` + `strategy_registry.get_registry` + `strategy_backtest_service._load_strategy_conditions`

### 🆕 feat: 信号持久化(轻量)
- **新文件** `backend/services/realtime_signal_log.py`
- `log_signal / mark_accepted(signal_id, order_id) / recent_signals(limit) / get_signal(id)`
- 复用 M2 已建表 `realtime_signal_log`(M2 milestone 已预埋)

### 🆕 feat: 手动确认下单 REST API
- **新文件** `backend/routers/realtime_signal.py`
- `GET /api/realtime/signal/recent?limit=50` — 最近 N 条信号
- `GET /api/realtime/signal/{id}` — 单条详情
- `POST /api/realtime/signal/{id}/accept` — 调 `t1_watcher.create_pending_order` 创建 T+1 模拟下单(默认 100 股, 10bps 滑点, 按当前价 planned_entry_price),关联 order_id 写回 signal_log
- alpha 简化: 用户 ID 取 admin 单用户;已接受 → 409;未知 ID → 404

### 🆕 feat: 后台扫描守护线程
- **新文件** `backend/services/realtime_signal_scanner.py`
- `RealtimeSignalScanner` 单例 + daemon thread(5s/轮)
- `_loop` / `_tick` / `_candidate_codes` — 候选 = `holdings.quantity>0 ∪ watchlist`
- 仅 `is_trading_hours()` 期间扫描;盘后不扫描;单轮异常不影响下一轮
- `services/scheduler.py` 新增 `start_realtime_signal_scanner_thread()` 顶层入口
- `main.startup()` 中启动

### ✅ 测试验收
- 20 个新测试(`tests/test_realtime_signal.py`):
  - `scan_signals` 5 个(空候选/空策略/未知策略/数据不足/构造 stock_data)
  - `signal_log` 4 个(log+recent 往返/倒序/mark_accepted/未知 ID)
  - REST 6 个(recent 列表/详情/404/accept 创建订单/409/404)
  - Scanner 5 个(单例/非交易时段跳过/盘中触发/log_signal/_candidate_codes)
- M3 单独跑: **20 passed / 0 failed**

### 📌 下一步
- M4: `/live` 仪表板前端(组合卡片 + 信号列表 + 手动确认按钮 + 推送状态)

---

## 2026-08-01 — v5.0-alpha M2 (盘中分钟级因子 + 5m TTL 缓存 + REST + 前端卡片)

### 🆕 feat: RealtimeFactorCache 盘中因子缓存(5m TTL)
- **新文件** `backend/services/realtime_factor_cache.py`
- `compute_realtime_factors()` 复用 `services/factor_lab.FACTOR_REGISTRY`(30 个因子)
- `compute_factors_with_cache()` 自动 cache 命中 / miss 走重算
- `_extract_scalar()` ndarray/float/None/NaN/inf → 标量或 None 兜底
- `set/get_cached_factor / get_all_cached / invalidate / fetch_recent_bars`
- 性能目标: 单只 × 30 因子 < 100ms(命中)/ < 500ms(重算)

### 🆕 feat: REST API
- **新文件** `backend/routers/realtime_factor.py`
- `GET /api/realtime/factor/{code}[?names=ma5,ma10,...]` — 返回 `{factors, cached_count, fresh_count, bar_count}`
- `POST /api/realtime/factor/{code}/invalidate` — 清缓存(alpha 测试用)
- 复用 `historical_kline` 日级 fallback(M11 阶段切 futu_raw_kline 分钟级)

### 🆕 feat: 前端 useRealtimeFactor + RealtimeFactorCard
- **新文件** `frontend/src/hooks/use-realtime-factor.ts` — SWR 30s 轮询
- **新文件** `frontend/src/components/realtime-factor-card.tsx` — 趋势(MA5/10/20/60)+ 技术(RSI/MACD/BOLL)+ 动量(RET_5D/20D) 三组展示
- 数字 `tabular-nums`,Loading/Empty/Error/Success 四态处理,符合 DESIGN.md 暗色 + `rounded-none`

### 🆕 feat: 数据库 schema
- `realtime_factor_cache`(PK: stock_code+factor_name, value REAL, ts REAL) — M2 因子缓存
- `realtime_signal_log`(M3 用,本 milestone 暂未启用) — 策略信号日志 + 手动确认状态

### ✅ 测试验收
- 17 个新测试(`tests/test_realtime_factor.py`):
  - `compute_realtime_factors` 7 个(序列不足/全部算/未知因子/单因子失败兜底/extract_scalar ndarray/None/NaN/inf)
  - 缓存层 5 个(set+get/None 跳过/TTL 过期/get_all_cached 跳过过期/invalidate)
  - `compute_factors_with_cache` 2 个(首次算并缓存/二次命中)
  - REST API 3 个(factor 返回/no-data 404/invalidate)
- 与 M1 一起跑: **38 passed / 0 failed**

### 📌 下一步
- M3: 实时信号扫描 (复用 13 YAML + compute_factors_with_cache) + 手动确认 UI
- M4: `/live` 仪表板前端(组合卡片 + 信号列表 + 推送状态)

---

## 2026-08-01 — v5.0-alpha M1 (实时行情接入 — 盘中 + 盘后统一腾讯 API)

### 🆕 feat: RealtimeQuoteService 单例
- **新文件** `backend/services/realtime_quote.py`
- `Quote` dataclass 标准化腾讯 API 返回(price/yesterday_close/open/high/low/volume/amount/change/change_pct)
- `is_trading_hours()` / `is_trading_day()` 时段判断(9:30-11:30 + 13:00-15:00)
- `subscribe()` / `get_snapshot()` / `_poll_once()` 行情接口
- 后台 5s polling(daemon thread + asyncio),拉持仓 + 自选股的 quote

### 🆕 feat: REST + WebSocket API
- **新文件** `backend/routers/realtime.py`
- `GET /api/realtime/watchlist?codes=000725,600519` — 一次性 snapshot
- `GET /api/realtime/trading-status` — 时段状态(前端判断"实时"徽章)
- `GET /api/realtime/all` — 当前 cache 全量(调试用)
- `WS /api/realtime/ws` — alpha 简化版(只推送 status),beta 切真实推送

### 🆕 feat: 前端 useRealtimeQuote hook
- **新文件** `frontend/src/hooks/use-realtime-quote.ts`
- SWR 5s 高频轮询 / 自动 join codes / 返回 Map<code, Quote> / lastUpdate + isTradingHours

### ✅ 测试验收
- 21 个新测试(`tests/test_realtime_quote.py`):
  - 时段判断 8 个(工作日早/午/晚/开盘/收盘边界 + 周末)
  - 服务类 5 个(单例/subscribe/get_snapshot/更新推送/subscriber 异常隔离)
  - `_poll_once` 3 个(空 codes / akshare 批量 / 异常兜底)
  - REST API 4 个(watchlist / 空 codes / trading-status / all)
- 全套件:189 passed / 0 failed(v4.1 168 + v5.0 M1 21),14.08s

### 📌 下一步
- M2: 盘中分钟级因子 + 5m TTL 缓存
- M3: 信号触发扫描 + 手动确认下单
- M4: `/live` 仪表板前端

---

## 2026-08-01 — v4.1.1 patch3 (5 项 bug 修复 + v4.1 收尾测试验收)

### 🐛 fix(quant): 股票代码 input 框"修改不了"
- **问题**: `/quant?code=000725` 页用户改 input 框 → 输入被立即覆盖回 `000725`
- **根因**: `page.tsx` useEffect 依赖列表包含 `code`,输入触发 state 更新 → effect 重跑 → 读到 URL 旧 code → 强制 setCode 把输入改回
- **修复**: 同步方向改为**单向 URL → state**,从依赖列表移除 `code`。添加防御性分支(URL 清空时 state 也清)
- **回归测试**: 覆盖 3 个场景(直接进入/外部跳转/快速选择器)

### 🐛 fix(shadow): `get_shadow_equity_curve` cutoff off-by-one
- **问题**: `shadow_portfolio_service.py:577` 算 cutoff = `today - days` → "过去 N 天"丢了边界日
- **触发**: 今天 2026-08-01, `days=30` → cutoff=2026-07-02 → 把 2026-07-01 滤掉
- **修复**: `cutoff = today - timedelta(days=days + 1)`,业务语义"过去 30 天"包含边界日

### 🐛 fix(test): Phase 2A orchestrator 测试撞 Phase 2B pipeline gate
- **问题**: `test_drift_policy.py` 2 个测试(Phase 2A 时代)直接调 `run_drift_check()` → 撞 Phase 2B 加的 `experiment_runs.last_status='done'` gate → `events_written=0`
- **修复**: 给两个测试加 `skip_pipeline_gate=True` 旁路参数(保留 PSI/KL 写表覆盖)
- **不影响**: `test_drift_policy_phase2b.py` 的新测试已正确处理 gate

### 🐛 fix(test): Phase 2B fixture 删 users 表污染后续测试
- **问题**: `test_drift_policy_phase2b.py:27` autouse fixture `DELETE FROM users` 把 admin 用户也删了 → 后续 18 个 approval 测试 + 3 个 e2e + 3 个 integration 全部失败(都依赖 admin user_id)
- **修复**: fixture 不清 users 表(init_db 自动建的 admin 是基础设施)。`_seed_experiment_run` 在 user 不存在时会重建

### 🐛 fix(test): v4.1.1 risk_guard 集成回归 test_t1_watcher
- **问题**: `test_t1_watcher.py::TestSimulateBuy` 2 个测试 admin 用户无初始 NAV,单次 buy 100% 占仓违反 30% 单票上限 → BLOCKED
- **修复**: TestSimulateBuy 加 autouse fixture `monkeypatch` `_evaluate_buy_risk` 旁路。风险测试由 `test_t1_watcher_risk.py` + `test_risk_guard.py` 单独覆盖

### ✅ v4.1 收尾测试验收
- 跑了 **19 个 v4.1 相关测试文件**,**168 个测试 0 失败**(17.43s)
- 包括: scheduler / pipeline_source_field / shadow_equity / retrospective_writer / bulk_approve / portfolio_vs_shadow / index_sync / etf_sync / drift_policy (×2) / t1_watcher (×2) / risk_guard / pipeline_persist / retrospective / counterfactual_api / approval_double_submit / e2e / integration
- 5 个修复全部在 main,代码无需 revert

---

## 2026-07-31 — v4.1.1 patch2 (路径一致 + dev DB seed)

### 🐛 fix: 策略加载路径与 registry 一致
- **问题**: `optimize_strategy_params` / `compare_strategies` 硬编码 `os.path.dirname(__file__)/../strategies`,测试 monkeypatch `registry.strategies_dir` 后两边路径不一致 → 无法端到端测试
- **修复**: 3 处(`_load_strategy_conditions` fallback / `optimize_strategy_params` / `compare_strategies`)统一走 `registry.strategies_dir`,保留 caller file 路径 fallback
- **测试**: 新增 3 个端到端用例(`test_strategy_registry.py` 18/18 passed)

### 📊 dev DB 5 年一次性 seed
- `index_sync_service.run_full_seed()` 6/6 指数成功 — `index_kline` 1250 行/指数 (2021-06-04 ~ 2026-07-30)
- v4.1 真实基准(沪深300/中证500/创业板等)从 fallback 切到真实 series
- ETF seed 因东方财富限频 7/11 失败,稍后重试(关键 Index 表已就位)

---

## 2026-07-30 — v4.1.1 patch (策略注册 + 冲击成本修复)

### 🆕 YAML 策略注册中心 (移植自 OSS quant-trading-system)
- **新文件** `backend/services/strategy_registry.py` — 单例 + 自动扫描 + mtime 失效 + validate
- 13 个内置策略(boll_mean / turtle_s1 / momentum_leader 等)自动发现,无需手动注册
- `_load_strategy_conditions` 用 `registry.validate()` 拦截 typo,不再静默通过
- 加新策略:丢 YAML 进 `backend/strategies/`,API/前端自动出现
- 测试: `tests/test_strategy_registry.py` 15/15 passed

### 🐛 fix: `_calc_impact_cost_bps` 移除未来数据泄漏
- **Bug**: 原 SQL 用 `date('now','-1 day')` 做 ADV 上限 → 回测 2024 年时读 2026 年真实数据
- **修复**: 加 `as_of_date: str` 必需 kw 参数,3 处调用方传 `next_date`/`final_date`
- **回归测试**: `test_as_of_date_isolates_historical_window` — 2024 截面 vs 2026 截面 impact 比 > 1.5x

### 📊 累计
- 测试: 35 passed (registry 15 + impact 12 + slippage 8)
- Commits: 13 个未推送到 origin (含 v4.1 的 11 个 + 2 个 patch)

---

## 2026-07-30 — v4.1.1 OSS port (RSRS + 仓位算法 + 联动通知)

移植自 `D:\some-oss\quant-trading-system` 的 strategies/rsrs.py + risk/sizing.py

### 🆕 factor_rsrs — 阻力支撑相对强度
- **新函数** `factor_service.factor_rsrs(highs, lows, window=18)`
- 经典 alpha: high~low OLS 回归 beta z-score,正=买方推力强
- 注册到 `FACTOR_REGISTRY['RSRS']`,`compute_all_factors` 自动调用
- 测试: 5/5 passed

### 🆕 risk_sizing.py — 4 种仓位算法
- **新文件** `backend/services/risk_sizing.py`
- FixedFraction / Kelly (half_kelly + 25% cap) / RiskParity / VolTarget
- 统一入口 `get_position_size(method="kelly", ...)` 返回 dict 带 diagnostic
- `calc_win_rate_and_profit_factor(trades)` 从历史交易算 Kelly 输入
- 测试: 22/22 passed

### 🆕 factor_lifecycle.retired → 通知
- **新函数** `factor_lifecycle._notify_lifecycle_changes(retired, warnings, policy_version)`
- 因子自动退役或新进 warning 时,推送邮件/微信/Telegram
- 失败不阻塞主流程(D7: 通知独立 audit 原则)
- 测试: 5/5 passed

### 📊 累计
- 测试: 47 passed (registry 15 + rsrs/sizing/notify 32)
- v4.1.1 总 commits: 4 (impact fix + registry + rsrs/sizing + docs)

### 🚫 没做(架构或红线原因)
- **配对交易策略** — StockAI YAML 单 symbol,不支持 spread 模式 → 推 v4.2
- **TWAP 拆单** — 7K 本金单笔 100 股不需要
- **QMT broker** — 红线:不做实时量化

---

## 2026-07-30 — v4.1.1 risk_guard + dev DB seed

### 🆕 risk_guard.py — 4 条规则纯函数评估器
移植自 `D:\some-oss\quant-trading-system\execution\risk_guard.py`

4 条规则按严重度递增:
1. 最大回撤 > 20% → `LIQUIDATE_ALL`(全部平仓)
2. 日亏损 > 5%    → `BLOCK_BUY`(锁仓,只允许平)
3. 单品种 > 30%   → `BLOCK_BUY`
4. 总仓位 > 80%   → `BLOCK_BUY`

返回 `RiskCheckResult(action, reason, 各指标快照)` — 便于审计/通知

- **新文件** `backend/services/risk_guard.py`
- **新测试** `tests/test_risk_guard.py` — 16 测试(各规则 + 边界 + 自定义阈值)
- 与 `discipline_service.py` 互补:本模块"实时硬拦截",discipline 是"用户纪律配置"

### 🆕 dev DB 5 年一次性 seed
- **index_kline** 180 rows → 7500 rows (6 indices × 1250 天, 2021-06 → 2026-07)
- **etf_kline** 仍 0 rows(eastmoney API 限频,scheduler 17:10 nightly 会补)
- 用户首次部署需手动跑: `python -c "from backend.services.index_sync_service import run_full_seed; run_full_seed()"`

### 🐛 fix: registry 与 loader 路径不一致
- `_load_strategy_conditions` 改用 `registry.get(sid).yaml_path` 加载
- 之前 registry 用 monkeypatch 目录(测试),loader 用真实 `backend/strategies/`
- 修后两边共享同一目录源 + mtime 缓存

### 📊 累计
- 测试: 67 passed (risk_guard 16 + registry 15 + rsrs/sizing 32 + impact 12
  含 8 个 Windows DB lock 噪音)
- 总 v4.1.1 commits: 6 个未推 origin

---

## 2026-07-30 — v4.1 完成 (Phase 1A/1B/2A/2B)

### 🎯 v4.1 战略: Decision-Loop 闭环 + 真实基准 + 漂移监控

| 维度 | v4.0 (旧) | v4.1 (新) |
|---|---|---|
| Pipeline 入口 | daily_quant_pipeline 手动触发 | 22:00 守护线程 + busy_timeout 10s + pool 15 |
| T+1 watcher | 单线程一次跑 | scheduler 守护 + 09:35 first-tick 校验 + 通知 |
| Shadow 组合 | 跑通但无 UI | 净值曲线图 + holdings vs shadow 对比卡 |
| Bulk approve | 无 | 单事务 + 三层乐观锁 + 0.85 边界 |
| 反事实 | 一次性 | run_retrospective_writer 自动跟跑 |
| 基准曲线 | ETF 510300 代理 | index_kline (6 默认指数) + etf_kline (11 默认 ETF) |
| Drift | 无 | drift_events + PSI/KL + 阈值版本化 + pipeline gate |

### 📋 实施完成清单 (4 个 Phase, 11 个 commit)

#### Phase 1A — Daily Pipeline 入口
- **1A.1** scheduler 守护注册 t1_watcher (25b7e96)
- **1A.2** pipeline 路由 18→22 + 连接池 5→15 (54b874f)
- **1A.3** inbox accept → pending_buy + source 字段 (4d6ac21)
- **1A.4** 反事实接入 run_retrospective_writer (b45a16c)
- **1A.5** fees.py audit (no code) (52c65a1)

#### Phase 1B — Watcher + Bulk Approve + UI
- **1B.1** watcher 推送通知 (9f72072)
- **1B.2** shadow 净值曲线图 (9c7c592)
- **1B.3** bulk-approve 单事务 + 0.85 边界 (a87ea48)
- **1B.4** holdings vs shadow 对比卡 (aadd55e)

#### Phase 2A — 真实基准 (Index/ETF K-line)
- **2A.1** index_kline + etf_kline 同步服务 (6 指数 + 11 ETF)
- **2A.2** strategy_backtest_service._get_benchmark_curve 4 段 fallback
- **2A.3** drift_policy PSI/KL 纯函数 + drift_monitor orchestrator

#### Phase 2B — Drift 监控 + v4.0 outside voice 修复
- **2B.1** drift_policies 表版本化阈值
- **2B.2** run_drift_check pipeline gate (实验 done 才跑)
- **2B.3** baseline_value 真实填值 (历史 30 天均值)
- **2B.4** v4.0 outside voice 5 项修复: ALTER 顺序 / watcher 事务 / pipeline_lock / 09:30 race / admin lookup

### 🧪 测试统计
- v4.1 新增: 30 测试 (Phase 2A 21 + Phase 2B 9)
- 总计: 53+ 测试 (含 v4.0 已存在的 32+ 回归)
- 全部: 单文件跑全过; 全集跑因 pytest collection Windows file-lock 已知问题有噪音

### 📦 已删除的 WIP: commit
- 全部 10 个 WIP: 前缀的 commit 通过本次合并转正 (e.g. 9c7c592, 54b874f 等已收尾)
- commit history 清理详见 git log

---

## 2026-07-26 — v4.0 计划完整敲定(D1-D4)

### 🎯 v4.0 战略决策

| # | 决策 | 内容 |
|---|------|------|
| **D1** | 战略方向 | 🧠 AI 深度 + 📊 因子回测 + 🔁 决策闭环(三方向并行) |
| **D2** | 主线能力 | **AI 选股智能化**(5→8 角色辩论 + Agent 调函数 + 推理增强) |
| **D3** | 形态入口 | **保持桌面 Web 不动**(不扩展 PWA / Tauri / 移动 app) |
| **D4** | 交付场景 | **T+1/T+2 短线预测**(前一晚收盘→次日开盘买入→第三日卖) |

### 📋 实施路线(5 阶段,总估时 6-10 周)

- **Phase 1**(2-3 周): 主线 MVP — 多 Agent 升级 + 工具调用 + 滑点 + T+1 成本
- **Phase 2**(2-3 周): Alpha158 Batch 1 + 冲击成本
- **Phase 3**(1-2 周): 反事实可视化 + 推理增强 + 多策略组合
- **Phase 4**(1-2 周,可选): Alpha158 Batch 2/3 + 个性化
- **Phase 5**: 发布 — README 同步 + CHANGELOG + release notes

详细计划见 [V4-PLAN.md](V4-PLAN.md)

---

## 2026-07-27 — v4.0 Phase 1 完成(A1 + A2 + B4 + C2 + T+1/T+2)

### 🎉 Phase 1 全部 5 子项落地

| 子项 | 状态 | 主要改动 |
|------|------|----------|
| **A1** 多 Agent 5→8 角色 | ✅ | `multi_agent_service.py` 加 3 角色(资金面/政策/做空),8 角色并行 + 3 轮编排 |
| **A2** Agent 工具调用 | ✅ | 新增 `agent_tools.py`(get_quote/get_factor/run_backtest/calc_t1_cost),`ai_service.py` 加 Claude + OpenAI tool_use 协议 |
| **B4** 滑点模型 | ✅ | `strategy_backtest_service.py` 加 `slippage_bps` 参数(默认 10bps),3 处价格调整 |
| **C2** T+1 成本计算器 | ✅ | 新增 `t1_cost.py`,含卖费+持仓风险溢价+滑点,集成到 agent_tools |
| **T+1/T+2 场景** | ✅(核心) | 新增 `t1_watcher.py` + `t1_pending_orders` 表,状态机 pending_buy→bought→sold,写 holdings + transactions |

### 📁 新增/修改文件

**新增**:
- `backend/services/agent_tools.py` (258 行)
- `backend/services/t1_cost.py` (155 行)
- `backend/services/t1_watcher.py` (380 行)
- `tests/test_agent_tools.py` (21 tests)
- `tests/test_slippage_model.py` (8 tests)
- `tests/test_t1_cost.py` (21 tests)
- `tests/test_t1_watcher.py` (16 tests)

**修改**:
- `backend/services/ai_service.py` (加 5 个新函数, +310 行)
- `backend/services/multi_agent_service.py` (3 新角色 + 8 角色编排, +130 行)
- `backend/services/strategy_backtest_service.py` (slippage_bps 参数, 3 处价格调整)
- `backend/database.py` (新增 t1_pending_orders 表 + 4 索引)
- `database/schema.sqlite.sql` (同步 t1_pending_orders)
- `frontend/src/components/multi-agent-analysis.tsx` (2x4 卡片布局 + 3 新角色)

### 🧪 测试覆盖

**85 个新测试 100% 通过**(覆盖 A2 协议转换 + 工具循环、8 角色编排、滑点价格调整、T+1 成本边界、watcher 状态机)

### ⏳ Phase 1 后续胶水代码(可下版本补)

- [ ] `scheduler.py` 加 t1_watcher 守护线程(22:00 pipeline + 09:30 watcher)
- [ ] `daily_quant_pipeline.py` 跑时机前移到 22:00
- [ ] 前端 `/pipeline` 收件箱 + 审批 → 创建 pending_buy
- [ ] 反事实报告接入 `proposal_retrospectives`(Phase 3 范围)
- [ ] `fees.py` 最小佣金 5 元在 T+1 100 股低本金场景下显著影响净收益,后续可调

### 🎯 Phase 1 验收

- ✅ 多 Agent 8 角色编排(E2E 通,后端 round1×4 + round2×3 + judge 3 轮)
- ✅ Agent 工具调用(Claude tool_use + OpenAI function_calling 双协议,21 个测试覆盖)
- ✅ 滑点模型(默认 10bps,价差验证 + 净 PnL 验证)
- ✅ T+1 成本计算(卖费 + 持仓溢价 + 滑点,4 个边界 + 3 个高级用法)
- ✅ T+1 watcher 状态机(16 个测试覆盖 CRUD/buy/sell/cancel/summarize)

**Phase 1 核心已就绪,Phase 2 (Alpha158 因子) 可随时启动。**

---

## 2026-07-27 — v4.0 Phase 2 完成(B1 + B5 + IC 重新校准)

### 🎉 Phase 2 全部 3 子项落地

| 子项 | 状态 | 主要改动 |
|------|------|----------|
| **B1** Alpha158 Batch 1 | ✅ | `factor_service.py` 加 15 价量类因子(K线形态/变化率/偏离度/价格变异/自回归 beta/量能变化/价量相关) |
| **B5** 冲击成本模型 | ✅ | `strategy_backtest_service.py` 加 `impact_bps` 参数 + `_calc_impact_cost_bps` 平方根模型,基于 ADV 比例 |
| **因子 IC 重新校准** | ✅ | `factor_lab.py` 加 11 B1 因子 + `recalibrate_all_factors_ic()` 排名函数 |

### 📁 新增/修改文件

**新增**:
- `tests/test_alpha158_batch1.py` (32 tests)
- `tests/test_impact_cost.py` (11 tests)
- `tests/test_ic_recalibration.py` (13 tests)

**修改**:
- `backend/services/factor_service.py` (15 因子函数 + opens 参数 + compute_all_factors 集成)
- `backend/services/factor_lab.py` (11 B1 lambda + `_factor_autocorr_beta` + `recalibrate_all_factors_ic()`)
- `backend/services/strategy_backtest_service.py` (impact_bps/adv_window 参数 + 3 处冲击计算 + `_calc_impact_cost_bps` 辅助)
- `backend/services/agent_tools.py` (run_backtest schema + 透传 impact_bps)

### 🧪 测试覆盖

**56 个新测试 100% 通过**(32 B1 + 11 B5 + 13 IC)

### 🎯 关键设计

- **B1 因子** — K线形态需 OHLC 数据,compute_all_factors 加 `opens` 参数(向后兼容,缺则 K 线 4 因子为 None)
- **B5 冲击** — 平方根模型 `impact = base × sqrt(order_size / ADV)`,5x base 上限保护,数据不足(<5 日)返回 0
- **IC 校准** — 复用 `compute_factor_metrics`,新增 B1 11 个 + 经典 15 个 = 26 个可计算因子,按 |ic_mean| 降序输出 Top-N

### 🎯 Phase 2 验收

- ✅ 15 B1 因子(11 个可在 factor_lab 算,4 个 K 线需 OHLC)
- ✅ B5 平方根模型,价格随订单规模/ADV 比例变化
- ✅ IC 重新校准接口就绪,跑实际数据即可出 Top-N 排名

**Phase 2 核心已就绪,Phase 3 (闭环可视化) 可随时启动。**

---

## 2026-07-27 — v4.0 Phase 3 完成(C1 + A3 + B6)

### 🎉 Phase 3 全部 3 子项落地

| 子项 | 状态 | 主要改动 |
|------|------|----------|
| **C1** 反事实报告可视化 | ✅ | 新增 `counterfactual.py` router,2 个端点(`/counterfactual` + `/retrospectives`),前端 `/pipeline` 加新 Tab |
| **A3** 推理增强(CoT) | ✅ | `multi_agent_service.py` 加 `JUDGE_SYSTEM_COT` 5 步推理 prompt,`enable_cot` 参数,`reasoning_chain` 输出字段 |
| **B6** 多策略组合回测 | ✅ | `strategy_backtest_service.py` 加 `run_combined_backtest`,3 种合并模式(union/intersect/majority)+ trade_attribution |

### 📁 新增/修改文件

**新增**:
- `backend/routers/counterfactual.py` (2 端点)
- `tests/test_counterfactual_api.py` (10 tests)
- `tests/test_combined_strategies.py` (11 tests)

**修改**:
- `backend/services/multi_agent_service.py` (JUDGE_SYSTEM_COT + CoT 推理链)
- `backend/services/strategy_backtest_service.py` (run_combined_backtest 3 模式)
- `backend/main.py` (注册 counterfactual router)
- `frontend/src/app/pipeline/page.tsx` (反事实 Tab + CounterfactualView)
- `frontend/src/components/multi-agent-analysis.tsx` (CoT 推理链折叠卡)

### 🧪 测试覆盖

**46 个新测试 100% 通过**(10 C1 + 11 B6 + 25 A3 含 CoT)

### 🎯 关键设计

- **C1**: 基于已有 `proposal_retrospectives` + `proposal_outcomes` 表,**无需新建表**;前端 3 卡片对比(已通过/已拒绝/Edge)
- **A3 CoT**: 5 步显式推理(关键信号 → 多空评估 → 风险 → 决策 → 信心),`reasoning_chain` 字段可折叠展示
- **B6**: 信号合并阈值 `union=1` / `intersect=N` / `majority=N/2+1`;trade_attribution 统计每个策略贡献

### 🎯 Phase 3 验收

- ✅ 反事实报告 API + 前端 Tab(approved vs rejected 实际表现对比)
- ✅ CoT 推理链(5 步显式推理,可折叠 UI)
- ✅ 多策略组合回测(3 模式 + attribution)

**Phase 3 核心已就绪,Phase 4 (B2/B3 剩余 Alpha158 + A4 个性化, 可选) 1-2 周可启动。**

---

## 2026-07-27 — v4.0 Phase 4 完成(B2 + B3 + A4)

### 🎉 Phase 4 全部 3 子项落地

| 子项 | 状态 | 主要改动 |
|------|------|----------|
| **B2** Alpha158 Batch 2 | ✅ | 15 动量/波动类因子(DEVIATION5/60 / STD10/60 / BETA5/10 / CORR5/10/60 / CORD5/10/20/60 / KMID / VWAP / VOL_CHANGE5) |
| **B3** Alpha158 Batch 3 | ✅ | 5 技术/资金流类因子(VOL_RATIO_5_20 / OBV_TREND_5 / KMID2 / AMPLITUDE_MA20 / VPA_SIGNAL) |
| **A4** 个性化 prompt | ✅ | `user_style.py` 新增(分析交易历史 → 胜率/持仓/风险偏好),`analyze_stock` 加 `personalize` + `user_id` 参数 |

### 📁 新增/修改文件

**新增**:
- `backend/services/user_style.py` (110 行)
- `tests/test_alpha158_batch2_3.py` (28 tests)
- `tests/test_user_style.py` (8 tests)

**修改**:
- `backend/services/factor_service.py` (20 新因子函数 + opens/highs/lows/volume 集成 + factor_beta20 参数化)
- `backend/services/multi_agent_service.py` (personalize/user_id 参数 + user_style 注入到 8 个 system prompt)

### 🧪 测试覆盖

**36 个新测试 100% 通过**(28 B2/B3 + 8 A4)

### 🎯 关键设计

- **B2**: factor_beta20 改为接受 period 参数(短周期 5/10 不再要求 10 个 rets)
- **B3**: 量价配合信号 VPA = 5 日收益 × 量能加速度
- **A4**: 从 transactions 表聚合胜率/持仓天数/风险偏好,自动注入 8 个角色的 system prompt

### 🎯 Phase 4 验收

- ✅ Alpha158 扩展到 64 个已完成因子(B1 15 + B2 15 + B3 5 + 经典 29)
- ✅ A4 个性化 prompt 完整链路(user_style → system prompt 注入)

**Phase 4 核心已就绪,Phase 5 (发布: tag + README + GitHub release) 可随时启动。**

---

## 2026-07-28 — v4.0 正式发布 🚀

### 📦 版本

- **Tag**: `v4.0`
- **Release Notes**: [RELEASE-NOTES-v4.0.md](RELEASE-NOTES-v4.0.md)

### 📚 文档同步

- `README.md` / `stockai-project-docs/README.md` / `stockai-project-docs/README.en.md` 三件套同步 v4.0
- `INDEX.md` / `CLAUDE.md` 当前版本 v4.0
- `docs/RUNBOOK.md` 新增 §8-§12(T+1 异常 / 工具调用异常 / 反事实异常 / 8 角色异常 / 部署检查清单)
- `stockai-project-docs/V4-PLAN.md` Phase 1-4 全标完成 ✅,Phase 5 发布节点

### 📊 4 阶段累计

| 阶段 | 测试 | 提交 |
|------|------|------|
| Phase 1 (AI + T+1) | 85 | `9a6ad79` |
| Phase 2 (因子 + 冲击) | 56 | `eab142d` |
| Phase 3 (闭环) | 46 | `5b2414f` |
| Phase 4 (Alpha158 + 个性化) | 36 | `a34fde7` |
| Phase 5 (发布) | — | `0efcbec` + `v4.0` |
| **累计** | **223** | 6 commits |

### 🆕 v4.0 完整能力清单

- **AI**: 8 角色多 Agent + CoT 5 步推理 + Agent 工具调用(Claude tool_use + OpenAI function_calling)+ 个性化 prompt
- **因子**: 64 个(29 经典 + 35 Alpha158 B1-B3)
- **回测**: 滑点(B4 10bps)+ 冲击成本(B5 ADV 平方根)+ 多策略组合(B6 union/intersect/majority)
- **T+1**: 22:00 Pipeline → 09:30 watcher 模拟成交 → 第三日卖出
- **闭环**: 反事实报告(基于已有表)+ IC 重新校准接口
- **3 路由**: counterfactual(2 端点)

### ⏭️ 下一步

- v4.0.x 维护期(社区反馈 / 胶水代码补全 / 监视器适配)
- 持续因子研究(剩余 Alpha158 K线形态 Q-15 未实现,需 OHLC 数据)
- 跨市场扩展(M1/HK/US)— 已在 TODOS.md 跟踪

---

## 2026-07-26 — README 三件套重写 + GitHub 主页修复

### 📝 README 重写

- **根目录 `README.md`** (新建,GitHub 主页):
  - 高端化重设计:badges + TL;DR + ASCII 架构图 + 表格化能力
  - **合并 v3.11 五个 🆕 重复项**:实验账本 / OOS 快照 / 影子组合 / 审批收件箱 / 灰度开关 → 一张总表
  - 环境变量全部占位符,无真实密钥
- **`stockai-project-docs/README.md`**: 同步重写(与根目录内容一致)
- **`stockai-project-docs/README.en.md`** (重写): 英文版,翻译原版结构,版本号 v3.11,链接相对路径调整
- **`INDEX.md`**: 同步更新文档导航 + 加入"同步清单"段(每次改动后必须更新的 MD)

### 🆕 v4.0 计划启动

- **新建 `V4-PLAN.md`**: 第四次大更新计划
- **D1 战略方向已敲定**: A. AI 深度能力 + B. 因子与回测体系 + C. 决策与执行闭环 (3 个方向并行)
- **D2-D4** 待用 AskUserQuestion 敲定(重点能力/形态入口/交付场景)

---

## 2026-07-26 — v3.11.x 补丁 + Monitor v0.1.0 引入

### 🛠 补丁(bug fixes, commit `3b186cb`)

- **`multi_agent_service.py`**: 补全 `_aggregate_results` / `_build_candidate_text` 等多 agent 测试所需内部函数 + 风险一票否决阈值
- **`quant/page.tsx`**: 修复 URL 切换代码时 K 线/insight 卡 stale 问题(`useRef` 锁住 lastFetchedCode,Strict Mode 双调用不再覆盖最新数据)
- **`plan/page.tsx`**: ESLint TDZ 警告修复(`resetForm` 提前声明)
- **`screener/page.tsx`**: ESLint TDZ 警告修复(`pollScan` 改 named function expression)
- **`test_retrospective.py`**: 修复 `limit=100` 默认截断导致 subset 断言失败
- **`frontend/tests/`** (新增): 4 个前端测试文件 — auth-redirect / holding-row-actions 等

### 📚 文档重构(commit `f36537a`)

- **6 个根目录 MD 移到 `stockai-project-docs/`**:
  `AGENTS.md` / `CHANGELOG.md` / `DESIGN.md` / `README.md` / `README.en.md` / `TODOS.md`
- **新建 `INDEX.md`** (根目录入口): 文档导航 + 项目说明 + 监视器链接
- **`CLAUDE.md`**: 引用路径更新到 `stockai-project-docs/`
- **`.gitignore`**: 新增 `monitor-desktop/` 构建产物规则

### 🖥 后端监视器 v0.1.0(commit `cc3562e`)

**新功能**: 独立桌面 app,只读观察 stockai 后端,**Deep Freeze 操作**(不污染主项目)。

- **新增子项目** `D:\stocks\monitor-desktop\`(完整 Electron + Vite + React + Tailwind 工程)
- **新增子项目** `D:\stocks\monitor-desktop-docs\`(`PLAN.md` + `DAILY-LOG.md`)
- **5 个面板模块**:
  - ① 进程总览(backend uvicorn + frontend next-server,CPU/RAM/PID/uptime)
  - ② 实时访问日志(虚拟 access log,监视器心跳 ping /api/health)
  - ③ 数据库结构(表清单 + 字段 + 外键 + 索引 + 抽样)
  - ④ Pipeline 状态(5 步进度 + 元信息)
  - ⑤ 错误统计(INFO/WARN/ERROR 计数)
- **技术栈**: Electron 32 + Vite 5 + React 18 + TS 5 + Tailwind 3 + systeminformation 5
- **DB 探针**: Python `sqlite3` 子进程(避免 better-sqlite3 native 编译失败 + sql.js 245MB 全量加载内存爆)
- **启动**: `cd monitor-desktop && run.bat`
- **红线**: 0 改动 stockai 主项目代码 / 只读 stockai.db / 5s 轮询

### 🚀 下一步: v4.0 大更新(规划中)

---

## 2026-07-25 — v3.11 — 研究→决策证据闭环（9 个 step 全部交付）

按 plan-ceo-review 2026-07-24 + plan-eng-review 2026-07-25 + plan-design-review 2026-07-25
三关 ALL CLEARED 后实施. **Gate 1 路径走通 + Gate 2 框架就绪**, **append-only 证据链完整**.

### 🎯 系统定位转变

```
v3.10:  跑因子 → 简报
v3.11:  跑因子 → 冻结假设 → 样本外验证 → 影子组合 → 人工审批 → 复盘
       (决策可追溯, 反事实可对比)
```

### 🆕 T1 — 实验账本 + 三轴状态机

- **新增表**: `experiments` / `experiment_runs` / `experiment_run_events` / `pipeline_lock` (+ 防御性补 `factor_candidates` / `factor_lifecycle_status` schema)
- **新服务** `backend/services/experiment_service.py`:
  - 三轴状态: `lifecycle_status` (candidate/validated/blocked/stale/rejected/paper/champion/retired) + `portfolio_role` (none/baseline/paper/champion/challenger) + `proposal_status` (pending/approved/rejected/expired/withdrawn)
  - 迁移白名单 + 版本 CAS + append-only 审计
  - 单飞锁 `pipeline_lock(scope)` 抢占过期锁
- **Pipeline write-through**: `quant_pipeline.run_pipeline()` 每步写 `experiment_runs` (不再纯内存)
- **`/api/factor-lab/mine/candidate/{id}/promote`** 改走 `create_experiment()`, 不再裸 UPDATE
- **测试**: 20 passed

### 🆕 T2 — Point-in-time OOS 快照

- **新增表**: `experiment_snapshots(experiment_id, version, policy_hash, input_version_hash, as_of_date, snapshot_json, UNIQUE(experiment_id, version))`
- **新服务** `backend/services/snapshot_service.py`: `freeze_snapshot` / `get_snapshot` / `replay_from_snapshot` / `assert_no_future_data`
- **`strategy_backtest_service._evaluate_overfit_from_snapshot()`** — OOS 重算从 snapshot 读 (不再切同一条 equity curve)
- **Fixture builder** `backend/scripts/build_freeze_fixture.py` → `tests/fixtures/freeze_demo.json`
- **测试**: 23 passed

### 🆕 T3 — 验证策略层

- **新增表**: `validation_policies(version, hash, body_json, activated_at)`
- **新服务** `backend/services/validation_policy.py` — 纯规则无 IO, 单例 dataclass + sha256 hash:
  - `v1.0.0` 默认: ir_active=0.15, ir_warning=0.05, warning_days_retire=14
  - **v1 Gate**: forward ≥60 交易日 且 ≥8 次独立决策
  - **Champion Gate**: forward ≥120 交易日 且 ≥12 次独立决策
  - 三档成本 (basis 30bps / conservative 60bps / extreme 120bps) × 周月调仓 = 6 行 matrix
  - bull/bear/sideways/unknown 状态分层
  - 5 个固定种子 + 5 次标签置换的负对照
- **`factor_lifecycle.py`** 委托给 policy (删魔数), 仍暴露兼容常量
- **`quant_service.get_benchmark_comparison(user_id: int)`** 删 default (D8)
- **`routers/data_ops.py`** 私有 `_trading_days_lag` → `services/trading_calendar.py` (D4 公共工具, 含 `next_trading_day` / `is_trading_day`)
- **测试**: 50 passed

### 🆕 T4 — 影子组合结算

- **新增表**: `shadow_portfolios` + `shadow_portfolio_snapshots(UNIQUE(portfolio_id, observation_date, input_version))`
- **新服务** `backend/services/fees.py` — A 股佣金万三+最低5, 印花税千一(仅卖), 过户费十万分之一
- **新服务** `backend/services/shadow_portfolio_service.py`:
  - 收盘后生成信号 → 下一可交易日 T+1 执行
  - 整手 (100 股) + 现金约束 + fee buffer (默认 100 元)
  - 缺价 → `blocked` / 部分缺价 → 跳过该代码 / 整组合缺价 → `blocked`
  - UNIQUE 防重复结算 (同日同 input_version 仅一条)
- **测试**: 23 passed

### 🆕 T5 — 审批 API + 对象级授权 + TTL lease + CAS

- **新增表**: `approval_proposals` (含 policy_hash / snapshot_hash / lease_id / lease_expires_at / version CAS) + `approval_attempts` (append-only 审计)
- **新服务** `backend/services/approval_service.py`:
  - 三层 CAS: `proposal.version` + `proposal.lease_id` + `proposal.lease_expires_at`
  - 默认 lease 24h, 可 `reopen_lease()` 重开发新 lease
  - approve 自动触发 `experiment_service.transition()` 到目标 lifecycle / portfolio_role
- **新 routers**: `/api/pipeline/proposals` + `/api/pipeline/experiments` + `/api/pipeline/shadow` (全部 owner 校验)
- **测试**: 19 passed (含双 submit 并发竞争)

### 🆕 T6 — `/pipeline` 前端页面 (Gate 1 收件箱)

- **`frontend/src/app/pipeline/page.tsx`** 改 Tabs 布局:
  - 默认 Tab **收件箱**: 待审批 / 已通过 / 已拒绝 / 已过期 (4 子 tab)
  - 第 2 Tab **运行**: 原 auto-pipeline runner 内容保留
- **新组件**: `ProposalRow.tsx` (接受/拒绝/稍后/过期 reopen, 44px 触摸目标) + `GateBadgeGroup.tsx`
- **新 hook**: `use-pipeline.ts` — SWR fetcher + 3 个 mutation helpers + lease 倒计时工具
- **新类型**: `api-types.ts` 加 9 个 TS interface
- 视觉契约: 照搬 `~/.gstack/.../inbox.html` 设计 wireframe
- 编译通过 (pre-existing playwright 模块缺失与本版本无关)

### 🆕 T7 — 回归测试 + 故障注入

- **新增 e2e** `tests/e2e/test_one_proposal_to_retro.py` — 3 个链路测试: 完整链路 / 拒绝路径 / 多 proposal
- **新增 integration** `tests/integration/test_restart_recovery.py` — 6 个: 过期锁抢占 / stale run 标记 / 多 worker 抢锁 / DB 状态重建
- **新增 integration** `tests/integration/test_budget_partial.py` — 13 个: 样本不足 unknown / NaN 数据 / 负价 / 全部缺价
- **测试**: 22 passed

### 🆕 T8 — 灰度发布 + 单飞锁 + 预算 + 告警 + 回滚

- **新增表**: `feature_flags(flag_key, enabled, scope)` + `notification_log(run_id, channel, success)`
- **新服务** `backend/services/feature_flag_service.py` — 5min TTL 缓存, 默认 OFF
- **5 个 bootstrap flag** (全 OFF):
  - `pipeline.shadow.enabled`
  - `pipeline.approval.enabled`
  - `pipeline.negative_control.enabled`
  - `pipeline.champion_replacement.enabled`
  - `pipeline.auto_promote.enabled` (永远 OFF, 自动晋级必须人工)
- **`quant_pipeline.run_pipeline()`** 加 `pipeline_lock` 单飞 + flag check, 第二次调用立即返回 `status=skipped`
- **`notify_service.send_notification(markdown, title, run_id)`** 独立 audit (D7: 通知失败不掩盖研究状态)
- **新文档** `docs/RUNBOOK.md` — 应急响应 / 一键回 OFF / stale run 检测 / counterfactual SQL
- **测试**: 15 passed

### 🆕 T9 — 复盘 + Counterfactual + AI Prompt 注入

- **新增表**: `proposal_outcomes(UNIQUE proposal_id)` + `proposal_retrospectives`
- **新服务** `backend/services/retrospective_service.py`:
  - `record_outcome()` 自动按 `decision + fwd_baseline_diff` 分类 good/bad/neutral
  - `counterfactual_summary()` 算接受 vs 拒绝的 edge
- **`trading_memory.record_proposal_retrospective()`** 写入 proposal lesson, `get_research_lessons(n)` 拉出来供后续 AI prompt 引用
- **测试**: 15 passed

### 📦 累计交付

| 阶段 | 任务 | 测试 |
|---|---|---|
| T1 状态机 | 4 | 20 ✓ |
| T2 OOS 快照 | 3 | 23 ✓ |
| T3 策略层 | 3 | 50 ✓ |
| T4 影子组合 | 3 | 23 ✓ |
| T5 审批 | 3 | 19 ✓ |
| T6 前端页 | 3 | 编译 ✓ |
| T7 故障注入 | 3 | 22 ✓ |
| T8 灰度审计 | 3 | 15 ✓ |
| T9 复盘 | 4 | 15 ✓ |
| **总计** | **31 任务** | **187 测试 + 1 编译** |

### 🔑 关键工程取舍 (为什么这样设计)

| 取舍 | 选择 | 理由 |
|---|---|---|
| 三轴 vs 单 boolean | **三轴** | 区分 "research 通过" 和 "组合里挂了" 和 "用户批没批" |
| OOS replay 怎么读数据 | **独立 snapshot 表** | `historical_kline` 重读会泄露未来行 |
| Gate 验证放哪 | **纯函数 policy + hash** | 便于 audit, version 化追溯 |
| Champion 替换自动 vs 人工 | **只建议 + 人工** | 一人项目也保命 |
| Auto-promote | **永远 OFF** | flag 写入, 不允许误开 |
| 通知失败 | **独立 audit** | 研究结论不能被通知拖下水 |
| 复盘 lesson | **写进 trading_memory** | AI 选股 prompt 引用, 闭环 |
| 任何 append-only 表 | **永不 DELETE** | 反事实证据链是研究系统的灵魂 |

---

## 2026-07-24 — v3.10.4 — /quotes 性能 + /pipeline warnings + 死代码清理 + 测试

### ⚡ /quotes N+1 → 单次 IN 查询 (commit `<tbd>`)
- **问题**: Futu 不可用时本地 DB 兜底路径 per-code `query_all`，100 只股票 = 100 次串行 SELECT，~10s
- **修复**: 单次 IN-clause + 相关子查询取每只股票最新收盘价，~200ms (50x 提升)
- **附带**: 本地兜底路径加 `_QUOTE_CACHE` 写入，60s 轮询不再重复 DB 查询

### 🛡️ /quotes 加 codes 长度上限 (commit `<tbd>`)
- **修复**: `BatchQuoteBody.codes: list[str] = Field(..., max_length=500)` 防 DoS
- **清理**: 删除不可达 legacy fund 路径 (~70 行死代码)

### 🎨 /pipeline warnings 列表展开 (commit `<tbd>`)
- **问题**: v3.10.3 修复了 `step.warnings` 渲染崩溃，但只显示 count，warnings[].message 从不展示
- **修复**: 改为可点击的"告警: N 个 ▸"，点击展开显示 `[step.name] [level] [type] message` 列表

### 🧪 K 线 fix 补单元测试 (commit `<tbd>`)
- 新增 `tests/test_technical_local_kline.py` 6 个 case:
  - DB 空 → None
  - DB 数据 < 20 条 → None
  - DB 数据 < days → None
  - DB 数据充足 → dict 含 source=local + 正序 dates
  - days 截断生效
  - DB 抛异常 → None (不 crash)
- **结果**: 6 passed in 0.34s

### 文件变更
- `backend/routers/stocks.py` — 删 70 行死代码 + IN-clause + codes max_length + 缓存写入 + 日志
- `frontend/src/app/pipeline/page.tsx` — warnings 折叠展开 + level/type badge
- `tests/test_technical_local_kline.py` — 新增 (K 线 fix 首个测试覆盖)

---

## 2026-07-23 — v3.10.3 — K 线时间修正 + screener 解构 + 自选股 + CI

### 🔧 Hotfix 1: /quant K 线时间戳错位 (commit `7e382a7`)
- **问题**: `/quant` 页 K 线最后日期显示 `2026-01-19`（6 个月前）
  - DB 实际 `historical_kline` 最新是 `2026-07-09`
  - 根因: `fetch_kline()` A 股分支走 `vendor_router` → akshare/sina/baostock，远程 API 被限频/缓存命中老数据
- **修复**: `technical.py` 新增 `_fetch_local_daily_kline()`，优先读本地 DB（≥20 条或 1/4 数据才认），不足时回退远程
- **影响**: 个股 K 线时间永远跟 DB 对齐，远程限频不再让 K 线日期穿越

### 🔧 Hotfix 2: screener AI 精选 + 5 Agent 解构错误 (commit `d63c0e7`)
- **问题**: `screener/page.tsx` 三处解构错位
  - `aiScreen()` 用 `Array.isArray(picks)` 过滤，但后端返回 `{ picks: [...] }` → 永远空数组
  - `MultiAgentResult` 接口与后端结构不匹配（误以为是 `decisions: [...]`，实为 `results: [...]`）
  - 评分列展示原始 `score`，不展示排序后的 `score_neutral` Z-score
- **修复**:
  - `setAiPicks(result?.picks ?? [])` — 读正确字段
  - 重写 `MultiAgentResult` interface 与渲染块，匹配后端实际返回 `{ results, summary: {total,buy_count,hold_count,sell_count,avg_confidence}, top_picks }`
  - 评分列优先 `score_neutral`，tooltip 显示原始 `score`

### ⚡ 性能优化: 自选股 30s → 60s + 窗口隐藏停刷 (commit `2525cbc`)
- **改动**: `watchlist/page.tsx`
  - `setInterval(tick, 60000)` 减半流量
  - `document.visibilitychange` 监听，hidden 时停刷新
- **背景**: 60s 行情刷新对自选股已足够（盘中价格波动没那么快），后台标签页浪费请求

### 🔧 Hotfix 3: /api/stocks/quotes 防 Futu 死循环 + 返回数组 (commit `abf639d`)
- **问题**: OpenD 没启动时 `/api/stocks/quotes` 永久 hang
  - 旧 `futu_client.healthcheck()` 只 `import` 检查，OpenD 关闭仍返回 True
- **修复**: 加 socket 探针（1 秒 `connect_ex('127.0.0.1', 11111)`），健康检查失败直接走 akshare fallback
- **附带**: 改返回 `{quotes: [...]}` → 直接数组，跟 OpenAPI 一致

### 🔧 Hotfix 4: CI npm ci EUSAGE + ERESOLVE (commits `23002ff` / `d8e98fb`)
- **ERESOLVE**: `@playwright/test@1.49.0` 与 `next@16.2.9` peer 冲突（要求 `^1.51.1`）
  - 加 `--legacy-peer-deps`
- **EUSAGE**: Windows 生成的 lock 缺 `fsevents@2.3.2`（macOS only package），Linux CI `npm ci` 失败
  - `npm ci` → `npm install --legacy-peer-deps --no-audit --no-fund`

### 🎨 UI: /pipeline 放宽宽度 + 双列布局 + TS 类型修复 (commits `0897d01` / `05168df`)
- **问题**: /pipeline 宽度太窄（`max-w-5xl`），单列堆叠，告警字段渲染崩溃 `Objects are not valid as a React child`
- **修复**:
  - `max-w-5xl` → `max-w-7xl`（不再局促）
  - 数据健康 + 5 步进度左右双列
  - `step.warnings` 改读 `step.warning_count ?? step.warnings?.length ?? 0`

### 📦 工程: 前后端版本号同步 v3.9 → v3.10.2 (commit `b9cd9a0`)
- **问题**: 前端 `version.ts` 写 `v3.9`，后端 `config.py` 写 `3.9`，与实际功能严重脱节
- **修复**: 双端同步到 `v3.10.2` / `3.10.2`
- **附带**: `README.md` 版本历史从列表重排为 4 列表格（版本/日期/主题/亮点），并补全 v3.10 系列

### 文件变更
- `backend/services/technical.py` — 新增 `_fetch_local_daily_kline` (~50 行)
- `frontend/src/app/screener/page.tsx` — 3 处解构 + 接口重写
- `frontend/src/app/watchlist/page.tsx` — 60s + visibilitychange
- `backend/routers/stocks.py` — quotes 防 Futu 死循环
- `backend/services/futu_client.py` — healthcheck 加 socket 探针
- `.github/workflows/ci.yml` — npm install + --legacy-peer-deps
- `frontend/src/app/pipeline/page.tsx` — UI 宽度 + TS 类型
- `frontend/src/lib/version.ts` + `backend/config.py` — VERSION 同步
- `README.md` — 版本历史表格化

---

## 2026-07-23 — v3.10.2 — Pipeline 简报质量 + /browse 自动刷新 + 板块补齐

### 🔧 Hotfix 1: 简报 GP 表达式显示
- **问题**: 简报"新挖因子 Top 10"里表达式全是 `...` 被截断
  - 后端 GP 输出字段叫 `expr`, 但简报读 `c.get("expr_text", "")` 拿到空字符串
- **修复**: `quant_brief.py` 改读 `c.get("expr", c.get("expr_text", ""))` (向后兼容)
- **验证**: 第 8 次 pipeline 跑通后, 简报里 10 个真实表达式 (`returns` / `delta(open, 10)` / `(close - abs(volume))` 等)

### 🔧 Hotfix 2: 简报状态汇总 race condition
- **问题**: 简报"状态汇总"里 5_brief_notify 显示 `running`, 实际已 done
  - `generate_brief()` 在 `STATUS.step("done")` 之前被调用, 看到的是 running
- **修复**: `quant_pipeline.py step_5` 在 `generate_brief()` 前手动标记 `steps_data["5_brief_notify"]["status"] = "done"`
- **验证**: 第 8 次 + 最新 1 次 pipeline, 状态汇总都显示 5/5 ✅ done

### 🆕 /browse UI 增强
- **顶部板块下拉补齐** (`FreshnessBar` 新增):
  - 6 个板块 Select: 沪深主板 / 深证主板 / 创业板 / 科创板 / 北交所 / ETF
  - 选中板块 → 点"补齐此板块"按钮 → 后台 sync 该板块所有股票
  - 替代每板块卡片右上角的小按钮 (不容易找)
- **freshness 30s 自动刷新** (`useFreshness`):
  - 之前只在挂载时 fetch 1 次
  - 现在加 `setInterval(fetchFreshness, 30000)`, 停留能看到数据自动更新

### 文件变更
- `backend/services/quant_brief.py` (1 行修复)
- `backend/services/quant_pipeline.py` (3 行 race fix)
- `frontend/src/app/browse/page.tsx` (FreshnessBar 加板块 Select + useFreshness 加 setInterval)
- TS check: 0 错误 (browse/page.tsx)

---

## 2026-07-23 — v3.10.1 — 量化 Pipeline 端到端跑通 (5 项 bug fix)

### 🔧 Hotfix 1: PipelineStatus.step() 签名 (commit `6506c45`)
- **问题**: `def step(self, name: str, **details)` 不接受 positional 第二参数
  - 调用 `STATUS.step("1_gp_mining", "running")` → `TypeError: takes 2 positional arguments but 3 were given`
- **修复**: 签名加 `status: str = "running"` keyword 参数, **details 不接受 positional
- **额外**: `if "status" in details: status = details.pop("status")` 向后兼容

### 🔧 Hotfix 2: step_1 best_factors 字段 (commit `6506c45`)
- **问题**: step_1 detail 的 `candidates` 是 int (count), 但 generate_brief 当 list 用 `[:10]` 切片
  - `'int' object is not subscriptable`
- **修复**: 同时存 `candidates=int count` (前端用) + `best_factors=list` (简报用)

### 🔧 Hotfix 3: step_3 warning_count + warnings list 拆分 (commit `6506c45`)
- **问题**: step_3 detail 的 `warnings` 是 int, generate_brief L49 `len(decay_step.get("warnings", []))` → `int has no len()`
- **修复**: 同时存 `warning_count=int` + `warnings=list of dicts`

### 🔧 Hotfix 4: step_4 health_status 字段重命名 (commit `6506c45`)
- **问题**: step_4 detail 的 `status=` 和 pipeline run status 同名字段冲突
  - generate_brief 读到的是 "done"/"failed", 不是 overall health status
- **修复**: 改名为 `health_status=` (业务字段) + `issues=` (count)
- **附带**: generate_brief dict iteration 改 `.values()`, 适配 dict-shaped steps_data

### 🔧 Hotfix 5: notify_service.send_notification 接口 (commit `6506c45`)
- **问题**: step_5 调 `send_notification(body=..., title=...)`
  - 真实签名是 `send_notification(markdown: str, title: str = "")` — 没有 body= 参数
- **修复**: 改用 `markdown=` 参数, 自动从 generate_brief 输出截断 1500 字

### 🆕 database.init_db 加 quant_briefs CREATE TABLE (commit `6506c45`)
- **问题**: schema.sql 有 quant_briefs 表, 但 init_db 是硬编码 CREATE TABLE, 不读 schema.sql
  - 上次重启会丢表
- **修复**: init_db 加上 `CREATE TABLE IF NOT EXISTS quant_briefs`

### 端到端验证 (8 次跑, 第 8 次成功)
| 步骤 | 状态 | 输出 |
|------|------|------|
| 1_gp_mining | done | 10 个候选因子 (top IR=0.390) |
| 2_ml_training | done | IR 提升 +7.94% (csi800 池子, 40 树) |
| 3_factor_decay | done | 3 因子自动退役 (volatility / ma_disposition / vol_ratio) |
| 4_data_health | done | stale, 1 issue (akshare 限频) |
| 5_brief_notify | done | brief-20260723-204155 已保存到 reports/quant/ + DB |

总耗时 ~151s (GP 训练 + ML 训练是主要耗时, factor_lifecycle IC 计算 13 次)

---

## 2026-07-20 — v3.9.1 — 浏览页 bug 修复 6 项 + 数据准确性

### 🔧 Hotfix 1: Select 空字符串错误 (commit `c0ac714` 之前漏记)
- **问题**: Radix UI `Select.Item value=""` 不允许（空串用于"清除选择"状态）
- **修复**: 用 `"all"` 占位替代，onValueChange 映射回 `""`
- **影响**: /browse 页面加载直接 crash

### 🔧 Hotfix 2: 行业涨幅榜改表格布局 (commit `7e0d11a`)
- **问题**: 横向 flex 滚动，窄屏溢出，"股票走马灯"观感
- **修复**: 改为表格（行业 / 总数/有数据 / 平均涨幅 / 柱状），与下方股票列表风格统一
- **用户已确认**: "横向不好看"

### 🔧 Hotfix 3: 默认折叠板块 + 过滤冷门 (commit `80be760`)
- **问题**: 5530 只股票一次渲染 + 5530 个 sparkline 请求，页面加载慢
- **修复**:
  - 默认只显示 5 个 A 股主板（沪深主板/深证主板/创业板/科创板/北交所）
  - 冷门板块（ETF/指数/三板）默认折叠到"+ 显示冷门板块"按钮里
  - 大幅降低首次加载压力（5530 → ~4500 主流 + 1000 冷门按需）

### 🔧 Hotfix 4: A 股交易日历判断 days_ago (commit `f48756b`) ⭐ 重要
- **问题**: 之前用日历天数 (today - last_date).days
  - 周末/节假日被算成"滞后"，误判大量 fresh 股票为 stale
  - 7-15 距 7-20 = 5 天日历差，但实际只缺 7-16/7-17/7-20 = 3 个交易日
- **修复**:
  - 用 akshare.tool_trade_date_hist_sina() 拉官方 A 股交易日历（8797 天）
  - `_trading_days_lag()` 计算实际 A 股交易日差距
  - freshness 从 0% → **94.1%** ✓

### 🔧 Hotfix 5: 股票数显示 "总数 / 有数据" (commit `1d53aa1`)
- **问题**: 之前只显示 `n` = 有完整数据的股票数（INNER JOIN 过滤）
  - 用户看到 "C27 医药 309 +1.75%" 可能误以为是 309 只股票平均
  - 实际是"有完整数据的 309 只"平均
- **修复**:
  - 新增 `n_total` / `n_with_data` / `data_pct` 字段
  - 显示 "309 / 309 (100% 有数据) +1.75%" —— 真实反映均值覆盖范围
- **数据核实**:
  - akshare/baostock **都用 qfq 前复权**（一致）
  - akshare 限频是免费 API 硬限制（不是代码 bug）
  - DB 同步跑后 733 只已更新到 7-20，3417 只到 7-15

### 🔧 Hotfix 6: 批量加自选 API 路径 (commit `9076155`)
- **问题**: 前端用 `/api/holdings/watchlist`，404 Not Found
- **根因**: `routers/holdings.py` 用 `prefix="/api/stocks"` 注册，正确路径是 `/api/stocks/watchlist`
- **修复**: 前端路径修正
- **测试**: 11/11 API 端点全部通过，POST 添加 600519 成功 (id=3408)

### 📊 v3.9.1 总体效果
| 指标 | v3.9 | v3.9.1 |
|---|---|---|
| /browse 加载慢 | 5530 只一次渲染 | ~4500 主流 + 冷门按需 |
| 行业涨幅榜 | 横向滚动 | 表格清晰 |
| Fresh 数据判定 | 0%（日历错） | 94.1%（交易日历对）|
| 股票数 n | 单数字歧义 | 总数/有数据 透明 |
| 批量加自选 | 404 | 200 OK |
| Select 控件 | crash | 正常 |

---

## 2026-07-23 — v3.10 量化 Pipeline (auto)

### 🆕 新增页面：`/pipeline` 量化 Pipeline 控制台
- **定位**: 按 plan-ceo-review 2026-07-22 方案, 自动化 GP 挖掘 → ML 训练 → 过拟合验证 → 衰减告警 → 简报 → 推送
- **5 步编排**:
  1. `1_gp_mining` — GP 挖因子 (复用 factor_expr.gp_mine)
  2. `2_ml_training` — ML 训练 (复用 factor_ml.train_ml_with_gp_factors)
  3. `3_factor_decay` — 因子衰减告警 (复用 factor_lifecycle.update_all_factors)
  4. `4_data_health` — 数据源健康 (新 services/health_monitor.py)
  5. `5_brief_notify` — 简报 + 推送 (新 services/quant_brief.py)
- **cron 入口**: `scripts/daily_quant_pipeline.py` (Linux cron / Windows 任务计划)
- **5 个新文件** + 3 个修改:
  - 新建: `backend/services/quant_pipeline.py` (300 行)
  - 新建: `backend/services/quant_brief.py` (160 行)
  - 新建: `backend/services/health_monitor.py` (130 行)
  - 新建: `backend/routers/pipeline.py` (60 行)
  - 新建: `backend/scripts/daily_quant_pipeline.py` (70 行)
  - 新建: `frontend/src/app/pipeline/page.tsx` (350 行)
- **修改**: main.py (import pipeline + include_router), schema.sql (加 quant_briefs 表), app-sidebar.tsx (加 Pipeline 入口)

### 6 个新 API (路由 /api/pipeline/*)
- `GET  /api/pipeline/status` - 当前 5 步进度
- `POST /api/pipeline/run` - 手动触发
- `GET  /api/pipeline/brief` - 最新简报 Markdown
- `GET  /api/pipeline/briefs` - 历史简报列表
- `GET  /api/pipeline/health` - 数据源健康度
- (内部) `services/health_monitor.check_all()` - akshare 限频 + Futu 断连检测

### 用户体验变化
- 之前: 每天手动跑 GP / ML / 检查
- 现在: 18:00 自动跑, 早上打开浏览器看简报

### 文件统计
- 6 个新文件 (~1000 行)
- 3 个修改
- 0 破坏性改动 (向后兼容)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

---

## 2026-07-20 — v3.9 正式版 — 股票浏览 + 数据运维

### 🆕 新增页面：`/browse` — 全市场浏览入口
- **定位**：填补"自选股"和"AI 选股"之间的空白 —— 全市场股票浏览 + 数据运维
- **不重复**：不做持仓 P&L（`/`）/ AI Top 选股（`/screener`）/ 深度技术指标（`/quant`）/ 预警盯盘（`/watchlist`）
- **唯一职责**：浏览 + 数据库运维

### 新增 6 个 API（`/api/data-ops/*`）
- **`GET /api/data-ops/stocks`** — 全市场股票列表 + 板块 + 最新价 + 涨跌幅 + 完整性标签 + 滞后天数
  - 过滤：`sector=main_sh/main_sz/gem/star/bse/etf/index` + `integrity=fresh/stale/missing` + `search=600519`
  - 一次返回全部 5530 只，按板块分组 + 完整性统计
- **`GET /api/data-ops/freshness`** — 各板块 K 线新鲜度仪表盘（最新日期 + 滞后天数 + 滞后分布）
- **`GET /api/data-ops/sector-performance`** — 行业涨幅榜 TOP N（按行业聚合当日/历史涨幅）
- **`GET /api/data-ops/sparkline/{code}?days=N`** — 单只股票最近 N 天收盘价序列（用于前端 sparkline）
- **`POST /api/data-ops/sync-stocks`** — 异步补齐 K 线（scope=missing/stale/sector/all）
  - 后台线程 + 进度可查（`GET /api/data-ops/sync-status/{task_id}`）
- **`GET /api/data-ops/sync-status/{task_id}`** — 任务进度（completed/failed/percent）

### Browse 页面功能（11 项）
- ✅ A 股票搜索框（代码/名称模糊匹配）
- ✅ B 60 日 K 线迷你图（sparkline，纯 SVG 自绘，涨绿跌红）
- ✅ C 最新价 + 涨跌幅 + 成交量 + 滞后天数
- ✅ D 一键补齐按钮（按 scope 一键补齐）
- ✅ E 按板块分组（沪深主板/深证主板/创业板/科创板/北交所/ETF/指数）
- ✅ F K 线新鲜度仪表盘（顶部彩色块，每个板块显示滞后天数）
- ✅ G 按板块批量补齐（板块行右侧"补齐此板块"按钮）
- ✅ H 数据完整性标签（✓ 新鲜 / ⚠ 滞后 / ❌ 缺失 三态 Badge）
- ✅ I 行业涨幅榜 TOP 10（横向彩色卡片）
- ✅ J 批量勾选 + 批量加自选（前端循环调 `/api/holdings/watchlist`）
- ✅ K 点击代码 → 跳转 `/quant?code=xxx` 深入分析

### 实现细节
- **板块分类**：`60/688/00/30/83/87/43/51/15` 等前缀自动归类（main_sh/star/gem/bse/etf）
- **完整性算法**：滞后 ≤3天=fresh / 4-7天=stale / >7天=stale；K线 <60=missing
- **涨跌幅 SQL**：LEFT JOIN `latest` + `prev` 子查询，单次 SQL 取最新价 + 前一交易日
- **sparkline**：纯 SVG `<polyline>`，120×32 px，涨红跌绿
- **同步补齐**：BackgroundTasks 异步 + 任务 ID + 状态轮询（每 2s）

### 文件统计
- 新增 `backend/routers/data_ops.py`（约 280 行）
- 新增 `frontend/src/app/browse/page.tsx`（约 470 行）
- 修改 `backend/main.py`（注册 router）
- 修改 `frontend/src/components/app-sidebar.tsx`（加 "股票浏览" 入口）
- 修改 `frontend/src/lib/api-types.ts`（加 9 个新类型）

---

## 2026-07-19 — 量化方向：Top 候选警告 + F10 + 回测保护 + GP+ML 联合

## 2026-07-19 — P0 修复：筛选功能 + 因子衰减评分

### 🔴 Bug #1：条件选股 / AI 选股筛选功能不可用
- **根因**：`backend/services/cache.py:35,42` 用了 `row[2]` / `row[0]` / `row[1]` 整数索引访问 dict
  - `database.py:62` `query_all()` 返回 `[dict(r) for r in rows]`,dict 不支持整数索引 → `KeyError: 2`
  - 每只股票 `_process_single_stock` 抛 KeyError → `try/except` 静默吞掉 → `all_factors=[]` → `candidates=0`
  - **历史原因**：`cache.py` 假设 row 是 `sqlite3.Row`(支持整数索引),但 `query_all` 已强制转 dict,接口契约未对齐
- **修复**：改用列名访问 `row["updated_at"]` / `row["factor_name"]` / `row["value"]`
- **附带发现**：`/api/quant/strategies` 路由 404 — 路由其实存在 (`routers/quant.py:985`),后端重启后自动修复
- **附带修复**：`screener_service.py` 顶部加 `logging.basicConfig(force=True)` —— `main.py` 没配 logging,应用 logger 静默丢失
- **诊断方法**：systematic-debugging 4 阶段 + 6 处 `[DIAG]` 埋点 + curl 触发 60 秒看 stderr → 一次定位到 `KeyError: 2`
- **验证**：21 只扫描 → 21 个候选(修复前 0),Top score=0.77

### 📊 因子衰减评分（明天计划 P0 遗留 2 天）
- **后端**：`factor_lab.py` 新增 `_compute_decay_score(ic_decay)` 函数（60 行，含 5 case 单元测试）
- **规则**：
  - 1→5 日 IC 相对衰减 >50%  → `red` / `rapid_decay`(建议退役)
  - 20-50%                  → `yellow` / `decay_warning`(观察)
  - ≤20%                    → `green` / `stable`(健康)
  - 数据不足                → `gray` / `insufficient_data`
- **接入**：`compute_factor_metrics()` 返回结果新增 `decay_score` 字段（`score`/`status`/`color`/`decay_pct`/`label`），`/api/factor-lab/ic` 路由自动透传
- **前端**：`factor-lab/page.tsx` 新增 `DecayScore` 接口 + IC 表格"衰减评分"列（绿/黄/红 Badge + Tooltip 显示衰减百分比）
- **真实用例命中**：`ret_5d` 因子 IR=0.148（中等），但 1 日 IC=+0.025 → 5 日 IC=-0.019（反向）→ score=0 / rapid_decay / red —— 典型"看着 IR 还行但实际快速衰减"的散户陷阱
- **建议后续**：`factor_lifecycle.py` retired 状态联动推送通知（邮件/微信/Telegram）

### 🔬 运行时诊断基础设施（保留）
- `screener_service.py` 保留 18 处 `[DIAG]` 埋点：`run_screener` 入口/出口/2 处早 return + 3 个预热函数耗时（`bench_kline`/`industry_map`/`stock_info`）+ ThreadPool `submitted/ok/failed/timeout/cache_hit` 计数
- 下次"扫描结果为空"问题可一眼定位：`[DIAG] all_factors=N top50=M` 即知数据形状
- 生产环境用 `LOG_LEVEL=WARNING` 屏蔽噪音

### 文件统计
- 1 个 commit `ab1e09b` （fix: 筛选功能 + 因子衰减评分）
- +167 / -9 行
- 4 个文件：`cache.py` / `factor_lab.py` / `screener_service.py` / `factor-lab/page.tsx`
- 已 push 到 `origin/main`

---

## 2026-07-19 — 量化方向：Top 候选警告 + F10 + 回测保护 + GP+ML 联合

> **项目重点调整**：从 7 月交易纪律方向转向**量化方向**（因子挖掘/分析 + 回测 + 预测）。
> 删除项目：分钟 K 线全套 K08-K12 / 服务器级数据备份（用户不需要）。

### 🔴 Top 候选警告联动衰减评分（半天）
- **后端** `routers/screener.py` 新增 `_attach_factor_warnings(candidates)` helper
  - 查 `factor_lifecycle_status` 表（`active` / `warning` / `retired`）
  - 给每个 candidate 涉及的因子标 warning + `has_critical_warnings` 标志
  - `/api/screener/results` 两处返回路径都加 warnings
- **前端** `screener/page.tsx` `ScanResult` 接口加 `factor_warnings` + 表格"关键因子"列渲染 Badge 警告色（红/黄）+ Tooltip 显示 `warning_days` + `ir_current`
- **真实用例**：候选 600056 涉及 `ret_20d`（warning, IR=0.125）+ `vol_ratio`（warning, IR=-0.065）→ 用户立刻知道该候选"信号弱"

### 🔴 F10 K线买卖点标注（1-2 天）
- **`components/KlineChart.tsx`** 新增 `TradeMarker` 接口 + `markers?: TradeMarker[]` prop
  - 在 `useEffect` 里调 `candleSeries.setMarkers(markers ?? [])`
  - 支持 `position: aboveBar/belowBar` + `shape: arrowUp/arrowDown` + 颜色
- **`app/quant/page.tsx`** 新增"叠加买卖点"按钮
  - 调 `/api/quant/strategy-backtest` with `stock_codes=[insight.code]`
  - 过滤当前股票 trades → 转 markers → 传给 KlineChart
  - 按钮可刷新/清除
- 后端 `strategy_backtest_service.py` 已返回完整 `trades: [{date, code, direction, price}]` —— 直接消费

### 🔴 回测内置保护（1 天）
- **后端** `services/strategy_backtest_service.py` 新增 `_evaluate_protection()` 函数（130 行）
  - **6 维风险评估**：(1) 样本量 (trades<20 警告) / (2) 过拟合 (sharpe>2+trades<30=high) / (3) 胜率异常 (4) 股票池多样性 (<5) / (5) 回测期长度 (<180 天) / (6) 手续费透明度
  - 综合 risk 等级：low / medium / high
  - 返回 `_protection: {warnings, suggestions, overfit_risk, summary}`
- **API** `routers/quant.py` `StrategyBacktestRequest` 加 `commission_rate: float = 0.0003`（默认万3）
- **单测 4/4 通过**：高 sharpe + 少交易 → high / 中等 → low / 低 sharpe → low / 极 sharpe + 小池 → high
- **端到端验证**：5 只股票 + 151 天回测期 → 触发"交易笔数过少"+"回测期过短"2 个警告 + 3 个改进建议

### 🔴 GP + ML 联合训练（核心突破）
- **后端** `services/factor_ml.py` 抽取通用 helper `_train_lgb()`（复用训练逻辑）+ 新增 `train_ml_with_gp_factors()`
- **工作流**：
  1. 读 `factor_candidates` 表 Top K GP 表达式（按 IR 降序）
  2. 训练基线 LightGBM（仅 15 个内置因子）
  3. 把 GP 因子作为新特征叠加训练增强 LightGBM
  4. 返回 base vs enhanced 完整对比
- **API** `routers/factor_lab.py` 新增 `POST /api/factor-lab/mine/train-ml-with-gp`
- **实测结果（hs300 + 3 GP 因子 + 60 树）**：
  - 基线 test IR=0.3802
  - 增强 test IR=**0.4323**（**+13.69% lift**）
  - spread 0.4930% → 0.5564%（+12.86%）
  - improved=True ✨
  - 6 秒完成，命中 7 月计划预期的"IR 提升 10-30%"区间
- **Bug 修复**：gp_df.trade_date（str）与 big_base.trade_date（datetime64）merge 类型不匹配 → `pd.to_datetime()` 转换

### 文件统计
- 1 个 commit（pending push）
- ~+520 / -10 行
- 8 个文件改动：4 后端服务 + 2 后端路由 + 3 前端页面/组件

---

### 🔴 Bug #1:条件选股 / AI 选股筛选功能不可用
- **根因**:`backend/services/cache.py:35,42` 用了 `row[2]` / `row[0]` / `row[1]` 整数索引访问 dict
  - `database.py:62` `query_all()` 返回 `[dict(r) for r in rows]`,dict 不支持整数索引 → `KeyError: 2`
  - 每只股票 `_process_single_stock` 抛 KeyError → `try/except` 静默吞掉 → `all_factors=[]` → `candidates=0`
  - **历史原因**:`cache.py` 假设 row 是 `sqlite3.Row`(支持整数索引),但 `query_all` 已强制转 dict,接口契约未对齐
- **修复**:改用列名访问 `row["updated_at"]` / `row["factor_name"]` / `row["value"]`
- **附带发现**:`/api/quant/strategies` 路由 404 — 路由其实存在 (`routers/quant.py:985`),后端重启后自动修复
- **附带修复**:`screener_service.py` 顶部加 `logging.basicConfig(force=True)` —— `main.py` 没配 logging,应用 logger 静默丢失
- **诊断方法**:systematic-debugging 4 阶段 + 6 处 `[DIAG]` 埋点 + curl 触发 60 秒看 stderr → 一次定位到 `KeyError: 2`
- **验证**:21 只扫描 → 21 个候选(修复前 0),Top score=0.77

### 📊 因子衰减评分(明天计划 P0 遗留 2 天)
- **后端**:`factor_lab.py` 新增 `_compute_decay_score(ic_decay)` 函数(60 行,含 5 case 单元测试)
- **规则**:
  - 1→5 日 IC 相对衰减 >50%  → `red` / `rapid_decay`(建议退役)
  - 20-50%                  → `yellow` / `decay_warning`(观察)
  - ≤20%                    → `green` / `stable`(健康)
  - 数据不足                → `gray` / `insufficient_data`
- **接入**:`compute_factor_metrics()` 返回结果新增 `decay_score` 字段(`score`/`status`/`color`/`decay_pct`/`label`),`/api/factor-lab/ic` 路由自动透传
- **前端**:`factor-lab/page.tsx` 新增 `DecayScore` 接口 + IC 表格"衰减评分"列(绿/黄/红 Badge + Tooltip 显示衰减百分比)
- **真实用例命中**:`ret_5d` 因子 IR=0.148(中等),但 1 日 IC=+0.025 → 5 日 IC=-0.019(反向)→ score=0 / rapid_decay / red —— 典型"看着 IR 还行但实际快速衰减"的散户陷阱
- **建议后续**:`factor_lifecycle.py` retired 状态联动推送通知(邮件/微信/Telegram)

### 🔬 运行时诊断基础设施(保留)
- `screener_service.py` 保留 18 处 `[DIAG]` 埋点:`run_screener` 入口/出口/2 处早 return + 3 个预热函数耗时(`bench_kline`/`industry_map`/`stock_info`) + ThreadPool `submitted/ok/failed/timeout/cache_hit` 计数
- 下次"扫描结果为空"问题可一眼定位:`[DIAG] all_factors=N top50=M` 即知数据形状
- 生产环境用 `LOG_LEVEL=WARNING` 屏蔽噪音

### 文件统计
- 1 个 commit `ab1e09b` (fix: 筛选功能 + 因子衰减评分)
- +167 / -9 行
- 4 个文件:`cache.py` / `factor_lab.py` / `screener_service.py` / `factor-lab/page.tsx`
- 已 push 到 `origin/main`

---

## 2026-07-16 — v3.9 后续 性能优化 + 因子实验室 Phase 1/2/3

### 性能优化
- **Tushare K 线 Provider** (`services/providers/tushare.py`)：新增 `TushareKLineProvider`，1 次 MCP 调用拉 1 只股票 ~250 个交易日（~0.4s/只，比 Baostock 1.5s 快 4×）
- **vendor_chain 顺序调整**：`tushare_kline → baostock_kline → akshare_kline`（默认 Tushare 优先）
- **screener max_workers 3 → 12**：全市场扫描提速 4×
- **DB 联合索引** `(stock_code, trade_date)`：历史 K 线查询提速 3-5×
- **schema.sql** 补 `historical_kline` 表声明（之前缺失）+ 索引声明

### 三层缓存
- `factor_snapshot` 表（55 因子 × 全市场）：precompute 11 秒完成 5528 只；screener 命中秒读
- `daily_north_flow` / `daily_inst_holding` 表：precompute 30 秒完成 watchlist+holdings 200 只
- `services/cache.py`：统一 read/write 接口（lazy-write + TTL 24h）

### 数据扩充
- `sync_kline_full.py` 跑完 5524 只全市场：从 0% 覆盖到 **5114 只有 1 年 K 线**
- 之前 3001 只 < 60 条 → 现在 344 只残缺（北交所代码 Tushare 不覆盖）
- `precompute_factors.py` / `precompute_market_cache.py` 离线预热脚本

### 因子实验室 (新模块 `/factor-lab`, 5 Tab)

#### Phase 1: 诊断 (1 天)
- **Tab IC 分析**：15 个纯价格/技术因子的 IC 时序 + IR + 胜率 + 衰减 + 评级
- **Tab 相关性矩阵**：N×N Pearson 热图 + 点击格子看解读（>0.7 提示重复因子）
- **Tab 散点图**：两因子散点 + 相关系数 + 回归线
- 后端：`services/factor_lab.py` (440 行) + `routers/factor_lab.py` (140 行)

#### Phase 2: GP 遗传编程挖掘 (1 周)
- **Tab GP 挖掘**：随机生成 + IC 评估 + 选择 top + 变异/交叉 + 迭代
- 表达式引擎：15 算子（close/ma/std/delta/abs/log 等）+ AST 安全求值
- 实测 (30 pop × 3 代 × 9 个月)：挖出 `returns` IR=+0.388（比手算 ret_5d IR=0.149 强 2.6×）
- `factor_candidates` 表 + 采纳/未采纳状态

#### Phase 3: LightGBM ML 因子生成 (1-2 周)
- **Tab ML 挖掘**：15 特征 → LightGBM 训练 → 特征重要性 + 训练/测试 IR + 多空 spread
- 实测 (100 树 × csi800 × 9 个月 = 8 秒)：训练 IR=2.0, 测试 IR=0.45, **多空 spread=+0.50%/日**
- 模型保存 .pkl 到 `backend/data/ml_models/`
- 后端：`services/factor_ml.py` (260 行)

### 清理
- **删除板块资金 + 北向资金**（akshare 接口全坏且用户决定不需要）：
  - 删 `routers/stocks.py` `/api/stocks/market-heatmap` 路由
  - 删 `services/akshare_adapter.py` `get_sector_fund_flow` / `get_north_flow_ranking` / `get_market_heatmap`（170 行）
  - 删 `frontend/src/components/hot-panel.tsx`（132 行）

### UI / 文档
- 双层 Header 重构：去掉 `site-header.tsx` 多余 SidebarTrigger（DESIGN.md 合规）
- 侧边栏导航加"因子实验室"入口
- README 完善：中英双语 + TOC + 数据源章节准确化
- Tushare token rotate + 脱敏（token 已泄漏到 git history，rotate 后失效）

### 文件统计
- 19 个 commit 全部 push
- 新增 ~2000 行（factor_lab + factor_ml + factor_expr）
- 删除 ~700 行（hot-panel + 3 个 akshare 函数）
- 总计 27 次重大更新

---

## 2026-07-16 — v3.9 登录健壮性 + UI 合规


### 登录 JSON 解析防御
- `frontend/src/app/login/page.tsx` 改写 fetch 错误处理：先 `res.text()` 读全文，再用 try/JSON.parse 解析
- 防御场景：后端瞬时 502 / dev `--reload` 重载 / 网络异常导致响应非 JSON 时，前端不再抛 `Unexpected token 'I', "Internal S"...` 给用户
- 用户体验：错误时直接展示真实状态码 + 响应内容前 80 字符（如 `服务器返回了非 JSON 内容（HTTP 502）— Internal Server Error`），不再被 SyntaxError 误导
- 保留 `error` / `detail` / 数组型 `detail.msg` 三种后端错误格式兼容

### 双层 Header UI 重构（DESIGN.md §Navigation 合规）
- 根因：`app-layout.tsx` 全局 header 与 `site-header.tsx` 页面 header 各有一个 `SidebarTrigger`，每个页面顶部出现两道折叠按钮，视觉重复
- `frontend/src/components/site-header.tsx` 移除 `SidebarTrigger` + `Separator`，仅保留页面标题
- `frontend/src/components/app-layout.tsx` 全局 header 改为 `justify-between`：左 `SidebarTrigger`，右版本号
- 满足 DESIGN.md 第 73-75 行"Top header: h-12, SidebarTrigger + version"硬性要求（之前缺 version）
- 影响 12 个使用 `SiteHeader` 的页面（screener / quant / plan / settings / journal / transactions / ai-assistant / watchlist / market / page 等）

### 版本号集中管理
- 新增 `frontend/src/lib/version.ts` 单一来源 `APP_VERSION = "v3.9"`
- 与 `backend/config.py::VERSION` 同步约定，注释提醒
- 版本号使用 `tabular-nums`，符合 DESIGN.md §Typography

---

## 2026-07-09 — v3.8 策略系统升级 + 选股增强 + 体验优化

### 策略模板系统

**12 个 YAML 策略升级为 13 个：**
- 每个策略新增 `source`（来源）、`tags`（标签）、`market_state`（适用市场）、`recommended_position`（推荐仓位）元信息
- 每个策略的数值条件暴露为 `params` 可调参数——含范围、步长、中文说明
- 新增策略 `trend_continuation` — 趋势中途介入（Stan Weinstein 阶段分析法，"半山腰埋伏"）
- 前端策略选择器展示来源、标签、适用市场、可调参数编辑器

### 参数优化器

- 新增 `POST /api/quant/strategy-optimize` — 网格搜索最优参数组合
- 自动生成参数候选值（number 类型均匀采样、range 类型生成典型组合），上限 300 组
- 排序逻辑：最大回撤升序 → 夏普降序 → 胜率降序（优先控制回撤）
- 前端展示排名表（🥇🥈🥉）+ 默认 vs 最优对比 + 一键应用参数
- 回测引擎新增 `param_overrides` 参数支持，可在运行时覆盖 YAML 默认值

### 策略对比

- 新增 `POST /api/quant/strategy-compare` — 多策略独立回测并排比较
- 前端选 ≥2 策略时显示"对比策略"按钮，结果排名表展示交易数/胜率/夏普/回撤/总收益

### 回测引擎增强

- **手续费自动计入**：佣金万分之三(最低5元) + 印花税千分之一(仅卖出) + 过户费十万分之一。买入卖出均扣费。`include_fees=True` 默认开启
- **过拟合警告**：0 笔交易→提示策略条件未触发+排查建议；<10 笔→统计不足；夏普>4→异常警告；回撤<2%→条件过宽警告
- **买卖点标注**：净值曲线新增绿色圆点(买入)/红色圆点(卖出)，hover 显示价格和盈亏
- **信号附带理由**：每笔交易自动附带触发策略名 + 该策略在此股票上的历史胜率

### 月报系统

- 新增 `POST /api/quant/monthly-report` — AI 驱动月报生成
- 聚合当月交易数据 + 交易记忆反思 → AI 写结构化报告（总成绩/赚最多/亏最多/策略PK/改进建议/评分）
- 幂等缓存：已生成月份直接返回
- 新增 `GET /api/quant/monthly-compare` — 上月对比诊断（胜率变化/盈亏变化/趋势判定：进步/退步/持平）
- 前端月报 Tab：月份选择器 + 生成按钮 + 上月对比按钮 + 报告卡片

### 交易记忆 → 策略维度

- `TradingMemoryLog.store_decision()` 新增 `strategy_id` 参数——记录每笔交易由哪个策略触发
- `_parse_entry()` 兼容新旧 tag 格式（含/不含 strategy_id）
- 新增 `get_strategy_context()` — 按策略维度查询历史表现
- `multi_agent_service.analyze_stock()` 裁判阶段自动注入：股票历史交易教训 + 策略在该股上的历史胜率
- 新增 `build_signal_reason()` — 选股信号解释生成器

### 连亏保护增强

- 新增 `get_protection_advice()` — 3 级警告（safe/warning/danger）+ 亏损明细 + 针对性行动建议
- 首页连亏 >0 时自动显示警告卡片，含最近亏损股票列表
- `/api/discipline/loss-streak` 端点切换到增强版

### 市场热点面板

- 新增 `frontend/src/components/hot-panel.tsx` — 首页顶部热点面板
- 两栏布局：板块资金流向 TOP5 + 北向资金持股 TOP5
- SWR 5 分钟自动刷新
- 后端数据源：`stock_sector_fund_flow_rank` + `stock_hsgt_hold_stock_em`
- API：`GET /api/stocks/market-heatmap` 一次返回全部数据

### 组合风险指标搬家

- 量化页"组合风险"Tab（Sharpe/最大回撤/波动率/Beta）移到首页第二排 KPI 卡片
- 新增 `frontend/src/components/portfolio-risk-cards.tsx`
- 页面打开自动加载，无需手动点按钮

### 选股板块过滤

- 新增 `detect_board()` — 根据代码前缀识别沪深主板/创业板/科创板/北交所/三板
- `run_screener()` 新增 `allowed_boards` 参数，默认只用沪深主板（散户买不了的科创板/北交所/创业板自动排除）
- 前端新增「创业板」开关按钮，手动开启后纳入 300 开头股票
- 解决 AI 选股选出科创板/北交所等买不了的股票的问题

### Bug 修复

- `multi_agent_service.run_multi_agent_screen` 函数缺失 → 已实现，选股页"多 Agent 交叉验证"恢复正常
- 北向资金数据显示异常（日期当代码）→ 改用 `stock_hsgt_hold_stock_em` API
- 涨停数据显示异常（代码当板块名）→ 删除该板块（用户不需要）
- 0 笔回测交易时提示"结果不可靠" → 改为"策略条件未触发"并给出排查建议

### 文件变更
- **新增**: `frontend/src/components/hot-panel.tsx`, `frontend/src/components/portfolio-risk-cards.tsx`, `backend/strategies/trend_continuation.yaml`
- **修改**: 22 个文件（详见 diff），总计约 2000 行新增代码，8 个新 API 端点

---

## 2026-07-03 — v3.7 策略回测引擎 + Futu 连接优化 + 数据扩充

### 策略回测引擎

**新增 `backend/services/strategy_backtest_service.py`：**
- `run_strategy_backtest()` — 核心函数，串联 YAML 策略选股→历史模拟交易→绩效报告
- 工作流：对每个调仓日，从 `historical_kline` 构建历史截面 → 计算技术字段 → `condition_engine.evaluate()` 跑策略筛选 → 模拟买入(次日开盘价)/卖出(持仓满 N 天)
- 支持参数：策略多选(OR 逻辑)、股票池、日期范围、持仓天数、调仓频率(daily/weekly/monthly)、仓位比例、基准指数
- 输出：6 大绩效指标(年化收益/夏普/最大回撤/胜率/盈亏比/卡玛) + 净值曲线 + 交易明细 + 月度收益 vs 基准

**新增 `backend/services/backtest_field_builder.py`：**
- 从 K 线数据计算策略所需全部技术字段(MA/RSI/MACD/ATR/布林带/动量等 30+ 字段)
- 纯函数，不调外部 API，回测和实时选股可共用
- 输出 `condition_engine.evaluate()` 能直接使用的 `stock_data` dict

**API 端点：**
- `POST /api/quant/strategy-backtest` — 策略回测
- `GET /api/quant/strategies` — 列出 17 个可用策略(12 YAML + 5 内置)

**前端：**
- `chart-equity-curve.tsx` — 净值曲线对比图(Recharts，策略紫色 vs 基准灰色)
- `backtest-results.tsx` — 回测结果展示(6 指标卡片 + 净值图 + 交易明细表 + 月度收益)
- `quant/page.tsx` 重写回测 Tab — 策略多选 + 股票池 + 参数面板 + 结果展示

### Futu 连接优化

**修复连接爆炸：**
- `futu_sync_service.py`：`run_intraday_sync` 和 `run_nightly_sync` 改为创建一个 `FutuClient` 实例，所有股票共享
- `sync_futu_data.py`：batch 模式支持 `--count` 参数
- 根因：之前每只股票新建 `OpenQuoteContext`，300 只 = 300 个 TCP 连接，超限后全部超时

### 数据扩充

- 自选股导入沪深300成分股(300 只)，总计 353 只股票，105K 条日线
- 时间跨度 2025-04-01 ~ 2026-07-03

### Bug 修复

- 基准曲线：ETF 不在库时回退为全市场等权合成基准(100 只随机采样)
- 个股透视：技术指标摘要从全序列数组改为只显示最新值
- 日期默认值：回测页默认日期改为匹配数据实际范围

### 文件变更
- **新增**: `backend/services/strategy_backtest_service.py`, `backend/services/backtest_field_builder.py`, `frontend/src/components/backtest-results.tsx`, `frontend/src/components/chart-equity-curve.tsx`
- **修改**: `backend/routers/quant.py`, `backend/services/futu_sync_service.py`, `backend/scripts/sync_futu_data.py`, `frontend/src/app/quant/page.tsx`, `backend/config.py`, `README.md`

---

## 2026-07-04 — v3.7 多 Agent 分析 + 数据源抽象 + 交易记忆 + 纪律系统 + 性能修复

### 多 Agent 深度分析

**重写 `backend/services/multi_agent_service.py`：**
- 5 角色多空辩论：技术面分析师 + 基本面分析师 → 多头研究员 + 空头研究员 → 裁判
- 3 轮调用（每轮并行），DeepSeek 下 15-20 秒完成
- 输出：结构化决策（买入/持有/卖出 + 置信度 + 止损建议 + 风险提示）
- **数据优先本地**：K 线/指标直接从 `historical_kline` 读取（零网络），仅基本面调外部 API
- API：`POST /api/quant/multi-agent-analysis`
- 前端：`multi-agent-analysis.tsx` 组件，量化页「AI 分析」Tab

### 数据源抽象层

**新增 `backend/services/vendor_config.py` + `vendor_router.py`：**
- 配置驱动的多源 fallback 链（Futu → Sina → AKShare → Baostock）
- 环境变量 `VENDOR_*` 一键切换供应商优先级
- 新数据源插拔式接入：实现函数 + 注册 + 配置
- **Futu 快速跳过**：OpenD 不可达时 1 秒检测跳过（之前 4 分钟超时）
- `technical.py`、`stocks.py`、`discipline.py` 全部改用 vendor_router

### 交易记忆系统

**新增 `backend/services/trading_memory.py`：**
- TradingAgents 风格交易记忆日志（Markdown 追加式）
- Phase A：卖出时自动写入 pending 条目
- Phase B：每天 15:30 自动解析（查数据库盈亏 → AI 生成反思）
- Phase C：下次 AI 复盘时注入历史上下文
- `discipline_service.py` 卖出接记忆钩子
- `scheduler.py` 新增记忆解析线程
- `review_service.py` 注入历史记忆到 AI 复盘 Prompt

### AI 复盘重构

- 删除旧的 `POST /api/stocks/review` / `/review/structured` / `/reviews` / `/reviews/{id}`
- 替换为 `GET /api/stocks/memory/stats` / `/memory/entries` / `/memory/context/{code}`
- `review_service.py` 精简：保留 `aggregate_transactions`，新增 `get_memory_entries` / `get_memory_stats`
- 前端量化页「AI 复盘」→「交易记忆」Tab：展示记忆条目 + 统计卡片

### 交易纪律强制系统

- `discipline_service.py` 新增：`get_rules` / `save_rules` / `validate_buy`
- 买入前校验：止损检查 + 仓位限制 + 追涨停禁止 + 连亏保护
- API：`GET/PUT /api/discipline/rules` + `POST /api/discipline/rules/validate-buy`
- 前端设置页：`TradingRulesSection` 可视化开关 + 参数调整

### AI 设置 Bug 修复（6 项）

| 问题 | 修复 |
|---|---|
| 测试连通用掩码 Key → 必然失败 | 后端 `POST /ai-test` 自动用数据库真实 Key |
| 改 model 保存会清空 Key | 后端 `PUT /ai-configs` 掩码检测 → 保留已存 Key |
| 死功能 `review` 无消费者 | 前端删除，替换为 `explain`（多 Agent 分析/因子解读） |
| 默认供应商 MiniMax 无 Key | `config.py` 默认改为 `deepseek` |
| MiniMax 标签误导 | 改为 `MiniMax（国内）` |
| `AIServiceError` 未导入 | `ai_service.py` 补充 import |

### 性能修复（6 项）

| 问题 | 修复 |
|---|---|
| 筛选页 6500+ 次重复请求 | `pollScan` → `useCallback` + `useRef` 防重复 |
| DataTable 3 套 DndContext 同时挂载 | 受控 Tab `activeTab` + `forceMount={false}` |
| DataTable `useState(initialData)` 不更新 | `useEffect` 同步 prop 变化 |
| `GET /holdings/with-pnl` 串行 N 次 HTTP | 先收集代码 → 一次 `get_batch_quotes` 批量获取 |
| `/api/version` 重复请求 | 删除 `app-layout.tsx` 中重复 SWR |
| 多 Tab 切回全量刷新 | SWR 全局 `revalidateOnFocus: false` + 去重 5s |

### 其他修复

- 基准曲线：ETF 不在库时回退为全市场等权合成基准
- 空 model 保存 → 后端掩码保护
- Python 编码错误 → 修复 `ai_service.py` 异常处理

### 盘前计划页面

- 新增 `frontend/src/app/plan/page.tsx`
- 侧边栏分析分组新增「盘前计划」入口
- 日期选择 + 市场状态 + 策略多选 + 候选标的 + 仓位滑块 + 风险提示 + 总结

### 文件变更
- **新增 4 文件**: `trading_memory.py`, `vendor_config.py`, `vendor_router.py`, `multi-agent-analysis.tsx`
- **新增 1 目录**: `frontend/src/app/plan/`
- **修改 19 文件**: 详见 git diff
- **总计**: 23 files, +1970/-1639 lines

---

## 2026-07-01 #2 — Futu P1 同步系统：批量同步 + 夜间补齐 + 状态落库 + 告警

### 目标

在已完成的 Futu Phase A 基础上，把 A 股 Futu 接入升级成一个可持续运行的小型同步系统，不再停留在单股脚本验证。

本轮 P1 范围锁定为：
- 覆盖对象：`watchlist + holdings`
- 白天增量同步：`quote + minute`
- 夜间补齐：以 `daily` 为主，必要时补 `minute`
- 监控方式：日志 + 数据库状态 + 严重失败主动通知

### 同步任务中心 `futu_sync_service.py`

**新增 `backend/services/futu_sync_service.py`：**
- `_load_sync_targets(scope)` — 从 `watchlist + holdings` 生成 A 股同步目标集合，去重并标记来源
- `_summarize_run()` — 统一分级：`success / partial_success / failed / skipped`
- `run_intraday_sync()` — 批量执行 `quote + minute`
- `run_nightly_sync()` — 批量执行 `daily`
- `_maybe_alert()` — 整轮失败或高失败率时触发告警
- `_build_alert_message()` — 生成告警摘要

### 状态表

**数据库 `backend/database.py` 新增 2 张表：**

- `futu_sync_runs`
  - 记录每一轮同步任务
  - 字段：`run_type`, `scope`, `target_count`, `success_count`, `failed_count`, `status`, `started_at`, `finished_at`, `duration_ms`, `error_summary`, `alert_sent`

- `futu_sync_run_items`
  - 记录每只股票、每种同步类型的结果
  - 字段：`stock_code`, `sync_type`, `status`, `error_message`, `source`, `from_watchlist`, `from_holdings`

### 脚本升级

**`backend/scripts/sync_futu_data.py` 升级为双模式入口：**

- `--mode single`
  - 保留 Phase A 单股脚本能力
- `--mode intraday`
  - 跑批量白天同步
- `--mode nightly`
  - 跑批量夜间补齐

并支持：
- `--scope watchlist`
- `--scope holdings`
- `--scope watchlist+holdings`

### 调度器接线

**`backend/services/scheduler.py` 新增：**
- `start_futu_intraday_sync_thread()` — 交易时段定时跑 `run_intraday_sync()`
- `start_futu_nightly_sync_thread()` — 每天固定时间跑 `run_nightly_sync()`

调度器只做触发，不承载业务同步逻辑。

### 告警与通知

复用现有 `notify_service.send_notification()`：
- 整轮失败 → 告警
- 失败比例过高 → 告警
- 单只股票偶发失败 → 仅记录，不立即通知

### 测试与真实验收

**自动化测试新增/补充：**
- `tests/test_futu_sync_service.py`
  - 目标集合生成
  - 运行状态分级
  - intraday / nightly 编排
  - 告警逻辑
  - 批量脚本路由
  - 调度触发
- 全量自动化回归：`108 passed`

**真实验收：**
- 在 `watchlist` 中加入 `600667`、`603399`
- 运行 `intraday`：成功，`target_count=2`, `success_count=4`
- 运行 `nightly`：成功，`target_count=2`, `success_count=2`
- `futu_sync_runs` 与 `futu_sync_run_items` 成功落库

### 文件变更
- **新增**: `backend/services/futu_sync_service.py`
- **修改**: `backend/database.py`, `backend/scripts/sync_futu_data.py`, `backend/services/scheduler.py`, `backend/requirements.txt`, `tests/test_futu_sync_service.py`
- **总计**: 1 新建 + 4 主要修改 + 完整测试补齐

---

## 2026-07-01 #1 — Futu Phase A：A 股 quote / minute / daily 接入 + raw 落库 + 现有链路接通

### 目标

把 Futu `OpenD + futu-api` 正式接入 StockAI，先只做 A 股，不碰 PG 底座和港美股。

本轮范围：
- A 股 `quote / minute / daily`
- raw 落库
- 日线同步 `historical_kline`
- 现有报价 / 日线 / 1m 图表链路接通

### Futu SDK 封装

**新增 `backend/services/futu_client.py`：**
- `healthcheck()` — 检查 Futu SDK / OpenD 可用性
- `get_snapshot()` — A 股实时报价映射
- `get_kline()` — A 股 `1m / 1d` K 线映射
- 统一 `symbol` / `market` / `dates` / `closes` 等返回结构
- 未安装 `futu-api` 时返回结构化错误，而不是启动时崩掉

### 原始落库与兼容层同步

**新增 `backend/services/futu_ingest_service.py`：**
- `sync_quote()` — 写 `futu_raw_quote`
- `sync_minute_kline()` — 写 `futu_raw_kline`
- `sync_daily_kline()` — 写 `futu_raw_kline` 并同步 `historical_kline`
- `get_quote_with_fallback()` / `get_daily_kline_with_fallback()` / `get_minute_kline_with_fallback()`

### 数据库结构

**`backend/database.py` 新增：**
- `futu_raw_quote`
- `futu_raw_kline`
- 唯一键：`(symbol, interval, bar_time, adjust_type)`
- 索引：
  - `idx_futu_raw_quote_symbol_time`
  - `idx_futu_raw_kline_symbol_interval_time`

### 现有服务链路接通

**1. 日线：`backend/services/technical.py`**
- A 股 `fetch_kline()` 改为：
  - Futu 日线优先
  - 失败再回退新浪 / 腾讯 / 东方财富 / Baostock

**2. 报价：`backend/routers/stocks.py`**
- `_fetch_quote_sync()` 改为：
  - A 股报价优先 Futu
  - 失败回退旧源
- 港股 / 美股维持旧逻辑

**3. 图表：`backend/routers/stocks.py`**
- `get_kline_data(period=1m)` 改为优先走 Futu 分钟线
- 其他周期继续沿用现有日线 / 聚合逻辑

### 脚本与真实验证

**新增 `backend/scripts/sync_futu_data.py`（Phase A 初版）**
- 支持单股：
  - `--type quote`
  - `--type minute`
  - `--type daily`
- 补了脚本环境变量与 `init_db()` 初始化，避免 CLI 直接启动时报错

**真实 OpenD 验证：**
- `600519` 的 quote 成功
- `600519` 的 minute 成功
- `600519` 的 daily 成功
- SQLite 中成功写入：
  - `futu_raw_quote`
  - `futu_raw_kline`
  - `historical_kline`

### 测试

**新增/补齐：**
- `tests/conftest.py`（恢复当前 worktree 的 pytest 基座）
- `tests/test_futu_client.py`
- `tests/test_futu_ingest_service.py`
- `tests/test_quant_service.py`（补回 worktree 量化回归）

覆盖：
- SDK 可用性
- raw 落库
- 日线同步
- fallback
- quote / 1m API 兼容
- 自动化测试通过

### 文件变更
- **新增**: `backend/services/futu_client.py`, `backend/services/futu_ingest_service.py`, `backend/scripts/sync_futu_data.py`, `tests/test_futu_client.py`, `tests/test_futu_ingest_service.py`, `tests/conftest.py`, `tests/test_quant_service.py`
- **修改**: `backend/database.py`, `backend/services/technical.py`, `backend/routers/stocks.py`, `backend/requirements.txt`
- **总计**: A 股 Futu 接入 + 落库 + 链路接通 + 测试闭环

---

## 2026-06-27 — 交易纪律系统 v1

### 背景

用户画像：7000 元本金，1-2 只持仓，1-3 天超短线。当前 StockAI 能选股但缺三件事：
1. 买了不知道什么时候割
2. 策略偏中长线，没有超短专用策略
3. 选股结果不敢信任

### 止损绑定系统

**数据库:** `transactions` 表 +4 列(stop_loss_price, stop_loss_triggered, planned_exit_price), `holdings` 表 +2 列(stop_loss_price, take_profit_price)

**后端 `routers/discipline.py`（新文件，~300 行）:**
- `POST /api/discipline/stop-loss/{holding_id}` — 为持仓设置止损/止盈价
- `GET /api/discipline/stop-loss/check` — 批量检查持仓触发状态(触发/接近/安全)
- `POST /api/discipline/stop-loss/{holding_id}/trigger` — 执行止损卖出(自动生成交易记录)
- `GET /api/discipline/dashboard` — 仪表板聚合数据

**`services/scheduler.py`:**
- `start_stop_loss_thread()` — 每 5 分钟检查止损(仅交易时段 9:00-15:00)
- 触发时推送通知到企业微信/Telegram/邮件

**前端:**
- 交易表单买入时新增止损价/止盈价输入框
- 仪表板新增止损监控卡片(红色警告: 距止损<2%)

### 连亏保护 + 交易日志

**数据库:** 新建 `trade_journal` 表(盈亏/纪律评分/情绪状态/教训), `trading_plans` 表(盘前计划)

**后端 `services/discipline_service.py`（新文件）:**
- `get_consecutive_losses()` — 从日志倒序数连亏次数
- `check_protection()` — 连亏>=3 次自动锁定
- `auto_create_journal_entry()` — 卖出时自动生成日志

**后端路由新增:**
- `GET /api/discipline/loss-streak` — 连亏状态 + 保护模式
- `POST /api/discipline/protection/toggle` — 开关保护
- `GET/PUT /api/discipline/journal` — 交易日志 CRUD
- `POST/GET /api/discipline/plan` — 盘前计划

**前端新页面 `/journal`:**
- 交易日志列表(盈亏、评分、情绪复盘、教训)
- 汇总卡片(总笔数/盈利/亏损/累计盈亏)
- 行内编辑: 纪律评分(1-10) + 情绪状态 + 教训

**前端侧边栏:** 加"交易日志"入口

### 超短线策略

**2 个新策略 YAML:**
- `gap_reversal.yaml` — 连跌反弹(RSI≤35 + 5日跌>5% + 放量止跌收阳, 1-2天持有)
- `breakout_pullback.yaml` — 突破回踩(放量突破20日高点 + RSI 50-75 + 量能确认, 2-3天持有)

### 信号置信度评分

在 `screener_service.py` 的选股结果中加 `confidence` (0-1) + `confidence_label` (高/中/低):
- 因子一致性 (40%) + 风险调整 (25%) + 流动性 (20%) + 因子覆盖率 (15%)

### 文件变更
- **新建**: `routers/discipline.py`, `services/discipline_service.py`, `journal/page.tsx`, `strategies/gap_reversal.yaml`, `strategies/breakout_pullback.yaml`
- **修改**: `database.py` (+60行), `main.py` (+3行), `scheduler.py` (+50行), `screener_service.py` (+35行), `transactions/page.tsx` (+30行), `page.tsx` (+40行), `app-sidebar.tsx` (+3行)
- **总计**: 5 新建 + 7 修改, ~550 行代码

---

## 2026-06-26 #3 — 条件选股性能优化 + 候选池保护 + 数据源故障诊断

### 问题定位

用户反馈条件选股页面"扫描失败: HTTP 500"，逐步排查发现三层问题：

**1. 首次扫描串行太慢 → 加并发**

`get_stock_factors_http` (AKShare) 串行调用 800 次 × 0.5s = 400s。L3a 改为 `ThreadPoolExecutor(max_workers=5)` 并发处理，300 只降至 ~3s。

**2. 无 L1/L2 过滤时全量进 L3/L4 → 加候选池上限**

超跌反弹、高股息防御等策略模板没有 L1(行业)/L2(价格) 条件，800 只直接进 L3/L4 → 挂死。

修复:
- L3a 候选上限 500 (AKShare并发, 超出返回400+提示)
- L3b 候选上限 200 (Baostock慢, 超出跳过并警告)
- L4 候选上限 300 (K线获取慢, 超出返回400+提示)
- K线获取天数从 120→60 减少传输量

**3. K线数据源大面积故障（根本原因）**

| 数据源 | 状态 |
|---|---|
| 腾讯 `web.ifzq.gtimg.cn` | HTTP 501 Not Implemented |
| 东方财富 `push2his` | 不可用 |
| Baostock | 可用但慢 (单次3-5s, RLock串行) |

`fetch_kline` 依次尝试腾讯(3s超时)→东财(失败)→Baostock(5s)，每只股票 ~8s。
`_http_get` 默认超时从 10s → 3s，减少等待。

**L2/L3 条件选股（PE/PB/ROE/价格/行业）完全可用，秒级返回。L4 需等腾讯/东财恢复。**

### Baostock 稳定性增强

- `_ensure_login()`: 登录失败后 60s 冷却，避免 bs.login() 反复阻塞
- `get_all_stock_list()`: Baostock 部分 ThreadPoolExecutor 包裹 8s 超时
- 股票池回退: Baostock 全 A 股查询失败 → 仅用沪深300+中证500 (800只)
- 行业字段已知问题: Baostock 行业查询也失败 → industry 显示为股票名

### 文件变更
- `backend/routers/screener.py`: L3a 并发化(ThreadPoolExecutor 5workers) + L3/L4 候选上限 + K线 60天 + L4 并发 6workers
- `backend/services/akshare_adapter.py`: `_http_get` 超时 10s→3s
- `backend/services/baostock_adapter.py`: 登录冷却机制
- `backend/services/screener_service.py`: Baostock 线程超时 + 股票池回退
- `CHANGELOG.md`: 补充本次排查记录

### 已知待解决
- [ ] K线数据源恢复监控 (腾讯/东方财富)
- [ ] 股票池扩至全 A 股 (需 Baostock query_stock_basic 恢复)
- [ ] L3/L4 上限可通过前端 `force` 参数绕过
- [ ] 前端策略模板加载 `close>open` (compare_field) 条件丢失

---

## 2026-06-26 #2 — 因子清理 + K线修复 + 条件选股L3两阶段重构

### K线图表三合一修复 (KlineChart.tsx)

**Bug: RSI/KDJ 线与K线时间轴不对齐**

根因：`toLine()` 函数先 `filter` 掉 null 再 `map`，index 重排导致所有指标线向左平移预热期长度（RSI -14天，KDJ -9天，MACD -35天）。改为先 `map` 保留原始 index 再 `filter`。

**新增：图表下方指标讲解栏**

显示每个可见指标的最新值 + 自动解读（金叉/死叉/超买/超卖/放量/缩量/多头/空头），颜色信号区分多空。

**优化：默认指标 + 坐标轴**
- 默认从 VOL+BOLL+MACD+RSI(4个) → VOL+MACD(2个)
- RSI/KDJ 子面板 scaleMargins 收紧，参考线始终可见

### 因子体系清理 (57→55)

**修复 5 个阈值单位不匹配 (quant.py):**

| 因子 | 根因 | 修复 |
|---|---|---|
| PE | 阈值写的是原始PE(10~100)，因子返回盈利率 1/PE | 阈值改为盈利率 |
| PB | 同上 | 阈值改为 1/PB |
| ROE | 阈值写百分比(2~35)，因子返回小数 | 阈值改为小数 |
| DIVIDEND_YIELD | 同上 | 阈值改为小数 |
| AVG_AMOUNT | 阈值写原始金额(1e6~1e9)，因子返回 log10 | 阈值改为 log10 |

**删除 2 个死因子:**
- SOCIAL_RANK / SOCIAL_BUZZ — 雪球 API 不可用，永远返回 0.0→5分
- 同步清理：FACTOR_REGISTRY / compute_all_factors / IC 权重 / 注释

### 条件选股 L3 两阶段重构 (screener.py)

**根因：** 高股息防御等含 `dividend_yield`/`debt_ratio`/`market_cap` 的策略永远 0 结果。L3 中 Baostock 字段只在候选<100时填充，但无 L1/L2 过滤时 800 只全进 L3 → Baostock 被跳过 → 字段永不填充 → 全部淘汰。

**修复：** L3 拆为 L3a + L3b
- L3a: AKShare HTTP 处理 PE/PB/ROE，先缩池
- L3b: Baostock 处理 dividend_yield/debt_ratio/market_cap，阈值 100→200

### Baostock 超时保护

- `_ensure_login()`: 登录失败后 60s 冷却，避免 bs.login() 反复阻塞
- `get_all_stock_list()`: Baostock 部分用 ThreadPoolExecutor 包裹 8s 超时

### 文件变更
- `frontend/src/components/KlineChart.tsx` (613→803行)
- `backend/routers/quant.py` (5行阈值 + 删社交因子)
- `backend/services/factor_service.py` (删 SOCIAL_RANK/SOCIAL_BUZZ)
- `backend/services/screener_service.py` (删社交 IC 权重 + Baostock 线程超时)
- `backend/routers/screener.py` (L3 拆 L3a+L3b, ~40行)
- `backend/services/baostock_adapter.py` (登录冷却机制)
- `backend/routers/screener.py` (注释更新)

---

## 2026-06-26 #1 — 条件选股两层→四层过滤架构重构

### 问题诊断

条件选股页 (`/screener/condition`) 存在 7 个严重 Bug，导致大多数条件字段不可用：

| # | Bug | 影响 |
|---|-----|------|
| 1 | `pe`/`pb`/`dividend_yield`/`debt_ratio`/`market_cap` 始终为 `None` | 所有基本面条件（除 ROE）完全失效 |
| 2 | `avg_amount_20d` 不在 `KLINE_FIELDS` 中 | 9 个策略 YAML 都依赖此字段，但单独使用时永不触发 K 线 |
| 3 | `_has_kline()` 和 `_strip_kline()` 不检查 `compare_field` | `close > ma20` 被误判为非 K 线条件 → 静默筛掉 |
| 4 | `market_cap` 死字段 | 市值条件从未被填充 |
| 5 | `_strip_kline()` 每只股票调用一次 | 不必要重复 |
| 6 | 条件引擎缺失字段静默返回 `False` | 无日志，调试困难 |
| 7 | `ret_5d`/`ret_20d` 返回小数 (0.05)，策略 YAML 用百分比 (5) | 条件判断不匹配 |

### 四层过滤架构

按数据获取成本从低到高分为四层：

| 层 | 数据来源 | 成本 | 字段 |
|---|---|---|---|
| L1 股票列表 | `get_all_stock_list()` 内存缓存 | 零 | `industry` |
| L2 实时行情 | 腾讯 `qt.gtimg.cn` 批量 HTTP | 极低 | `price` |
| L3 基本面 | AKShare `stock_financial_abstract_ths` + Baostock 兜底 | 中等 | `pe`, `pb`, `roe`, `dividend_yield`, `debt_ratio`, `market_cap` |
| L4 K线+指标 | 腾讯 K线 → 东方财富 → Baostock + 本地计算 | 最重 | 所有均线/RSI/MACD/BOLL/交叉/动量/ATR/量比 |

核心流程：`classify_conditions() → L1过滤 → L2获取+过滤 → L3获取+过滤 → L4并行计算+过滤 → 排序返回`

### 关键修复

- **PE/PB 计算**：从 AKShare 返回的 `eps`/`bvps` + 行情 `price` 现场计算（`pe = price/eps`, `pb = price/bvps`）
- **Baostock 兜底优化**：只在候选 < 100 时启用，避免全局锁串行化（大规模扫描时跳过 `dividend_yield`/`debt_ratio`/`market_cap`）
- **`ret_5d`/`ret_20d` 百分比化**：`factor_ret_5d() * 100` 转为百分比，与策略 YAML 值匹配
- **`avg_amount_20d` 加入 L4**：可独立触发 K 线获取
- **`compare_field` 检查**：`classify_conditions()` 同时检查 `field` 和 `compare_field`，归类到最高层
- **条件引擎日志**：`condition_engine.py` 新增 `logger.debug` 输出 None 字段和异常

### 前端改动

- 条件分类从 `{基础, 基本面, 技术指标, 因子}` → `{L1 股票列表, L2 实时行情, L3 基本面, L4 K线指标}`
- 条件行前加彩色层标签（L1 灰 / L2 蓝 / L3 绿 / L4 紫）

### 验证结果

| 测试 | 结果 |
|---|---|
| PE<30 (纯 L3) | ✅ 800→427, PE=3.23 真实值, 38s |
| 动量策略 (纯 L4) | ✅ 800→27, ret_20d=58.91%, 5s |
| avg_amount_20d 单独使用 | ✅ 800→109, 修复 Bug #2 |
| 价格区间 (L1+L2) | ✅ 800→356, 4s |

### 文件变更
- **重写**: `backend/routers/screener.py` (~200行: 四层字段集 + `classify_conditions()` + 四层 `condition_scan` + PE/PB 计算 + CONDITION_SCHEMA 更新)
- **修改**: `backend/services/condition_engine.py` (+10行: None 字段调试日志)
- **修改**: `frontend/src/app/screener/condition/page.tsx` (+15行: 四层标签 + L1-L4 彩色徽标)
- **新增**: `backend/.env` (开发环境变量)
- **修改**: `backend/config.py` (+3行: `load_dotenv()` 自动加载 .env)

---

## 2026-06-23 — AI 设置页重构 + Quant 交互优化 + 因子解读

### AI 设置页重构：功能→供应商映射表

**之前的问题：**
- 6 个供应商卡片 × 3 字段 = 18 个输入框，但所有功能只用一个默认供应商
- "小米"供应商 model/base_url 为空，选了必然失败
- 配置来源不透明（.env / 数据库 / 默认值）
- 6 个 AI 功能不能独立指定供应商

**新设计：**
- **功能→供应商映射表**：7 行（AI选股/复盘/对抗/对话/盯盘/日报/量化解读），每行独立选择供应商
- **动态供应商配置区**：只展开被表格引用的供应商，减少视觉噪音
- **配置来源标签**：每个供应商显示 `.env` / `已保存` / `默认` / `未配置`
- **连通测试**：`POST /api/settings/ai-test` 端点，前端每行都有测试按钮
- **删除"小米"**：合并到"自定义 OpenAI 兼容"

**后端改动：**
- `ai_service.py`：新增 `get_provider_for_function(function_key)` → 读取 `function_providers` 映射
- `ai_chat()` 新增 `function` 参数：`function="screener"` → 自动查映射表找供应商
- 12 个 AI 调用点全部传入 `function` 参数（screener/review/duel/chat/watchdog/kol/explain）
- 不配置 `function_providers` 时回退到 `get_default_provider()`，向后兼容

### Quant 页面交互优化

- 添加统一「查询」按钮：根据当前 tab 自动分发（个股透视→K线 / 因子分析→因子面板 / 回测→回测 / MC→模拟）
- 快速选择器（▼下拉）改为只填入代码，不自动查询
- Enter 键改为调用 `handleQuery()`，统一分发
- 因子分析空状态删除冗余的"查看因子"按钮，引导使用上方统一查询

### AI 因子解读

- 新增 `POST /api/quant/factor-explain` 端点
- 因子面板加载后出现「AI 因子解读」按钮
- AI 分析 10 类因子的优势维度（得分最高）和风险维度（得分最低）
- 生成结构化报告：优势/风险/综合评估/操作建议

### 根治 Turbopack "Object is disposed" 错误

- `proxy.ts` → `middleware.ts`（Next.js 标准命名，消除模块歧义）
- 函数 `proxy` → `middleware`
- 新增 `predev` 脚本：每次 `npm run dev` 自动清除 `.next/dev` 缓存

### Bug 修复

- **设置保存后丢失**：前端发送数据与后端 `MultiAiConfigBody` 结构不匹配（缺 `configs` 包装），修复 `{ configs }` 包装
- **掩码覆盖真实 Key**：GET 返回掩码 `sk-a****b3` → 保存时检查是否含 `****`，掩码不发送，保护真实 Key

### 文件变更
- 修改：`backend/services/ai_service.py` (+27行 get_provider_for_function + function参数)
- 修改：`backend/routers/settings.py` (+63行 测试端点 + env_keys + function_providers)
- 修改：`backend/routers/quant.py` (+106行 factor-explain端点)
- 修改：`frontend/src/app/settings/page.tsx` (完全重构，18框→7行表格)
- 修改：`frontend/src/app/quant/page.tsx` (+137行 查询按钮 + 因子解读)
- 删除：`frontend/src/proxy.ts`
- 新增：`frontend/src/middleware.ts`
- 后端 9 个调用点：各 +1 行 `function=` 参数

---

## 2026-06-22（续）— `/quant` 页面 10 问规划 + 全面改版

### Q1-Q10 量化页改版决策

| Q | 决策 | 状态 | 内容 |
|---|------|:---:|------|
| Q1 | A 升级蜡烛图 | ✅ 已实现 | recharts 折线图 → lightweight-charts 蜡烛图 + MA5/10/20 |
| Q2 | A 全面海龟 | ✅ 已实现 | 通道线叠加到K线图 + 评分卡片 + ATR/止损/仓位 |
| Q3 | B 不对比 | 不做 | 单只深度分析 |
| Q4 | A AI 底部 | ⬜ 未验证 | AI 解读卡片（技术面+基本面+风险）—— 需配 AI Key |
| Q5 | C 保持现状 | 不做 | 因子面板不动，优先激活 pending 因子 |
| Q6 | A 海龟回测 | 🔲 待实现 | 海龟S1/S2 加入策略对比 |
| Q7 | B 手动触发 | 不做 | 不自动刷新 |
| Q8 | A 提醒面板 | ⬜ 未验证 | 底部「我的提醒」列表+删除 —— 需进入页面确认 |
| Q9 | C 快速选择 | ⬜ 未验证 | 持仓/自选/海龟Top10 下拉选择器 —— 需前端确认 |
| Q10 | C 不考虑 | 不做 | 移动端不优化 |

### Q1 实现 — K线图表升级
- 后端: `stock-insight` +MA5/MA10/MA20 数组
- 前端: `KlineChart` 替换 `AreaChart`, 5 指标切换按钮 (VOL/BOLL/MACD/RSI/KDJ), 技术指标摘要 6 列精简

### Q2 实现 — 海龟全面集成
- 后端: `stock-insight` +`_calc_turtle()` (S1/S2通道 + 突破检测 + ATR + 0-100评分)
- KlineChart: `TurtleOverlay` prop → `createPriceLine` 画 4 条水平线 (S1入红虚线/S2入橙虚线/S1出绿点线/S2出绿点线)
- 前端: 海龟评分卡 + S1/S2入场价+触发标记🔥 + ATR(N)/止损2N/仓位股数

### Q4 实现 — AI 量化解读
- 后端: explain prompt 补海龟数据, 链路: `ai_chat()` → `get_default_provider()` → settings表Key
- 前端: 「AI 解读」按钮 + 紫色左边框卡片 (技术面/基本面/风险三栏)

### Q8 实现 — 提醒面板
- 数据: `GET /api/stocks/alerts`
- 前端: Tabs 下方橙色边框卡片, 3列网格, 触发检测(红色高亮), 删除按钮

### Q9 实现 — 快速选择器
- 数据: `GET /api/stocks/holdings` + `GET /api/stocks/watchlist` (挂载时拉取)
- UI: ▼按钮 → 下拉三组 (持仓/自选/海龟Top10) → 点击自动填入代码+触发查询

### 版本
- `config.py`: VERSION "3.2" → **"3.4"**

### 文件变更
- 修改: `backend/routers/quant.py` (+200行 MA数组+turtle计算+AI prompt增强)
- 修改: `frontend/src/components/KlineChart.tsx` (+60行 TurtleOverlay prop+priceLine)
- 修改: `frontend/src/app/quant/page.tsx` (+300行 KlineChart+海龟卡+AI解读+提醒+选择器)
- 修改: `backend/config.py` (VERSION→3.4)
- 新增: `reports/turtle_screener.py`, `analyze_top3.py`, `turtle_screen_*.json`

### ⚠️ 未验证
- [ ] Q4: AI 解读 — 需配 AI Key 后实际调用
- [ ] Q8: 提醒面板 — 需前端页面确认 UI
- [ ] Q9: 快速选择器 — 需前端页面确认交互
- [ ] Q1/Q2: K线+海龟通道线 — 需浏览器实际渲染验证

### 已知待修
- `page.tsx:259` — TS2352 类型错误 (已有)
- 端口 3000 僵尸进程
- AI 依赖 settings 表 Key 配置

---

## 2026-06-22 — 海龟交易法选股 + 因子分析面板

### 海龟交易法 × 多因子综合选股
- **turtle_screener.py** — 全新海龟交易法选股脚本，组合三大维度：
  - 海龟通道：S1(20日突破)/S2(55日突破)入场 + S1(10日低)/S2(20日低)出场
  - ATR(N) 波动率归一化仓位计算 + 2N 止损
  - 29 因子体系打分（动量/波动率/量价/情绪/估值）
  - 综合评分：海龟 60% + 因子 40%
- **筛选漏斗**：4955 只 A 股 → 2964 只(价<20+市值>5亿) → 400 只深度分析 → Top50
- **数据源**：Baostock(股票列表) + 腾讯财经(实时行情/K线)，绕过系统代理
- **Top3 标的**：楚江新材(78.0) / 皖维高新(76.6) / 汤臣倍健(72.2)
- 结果保存至 `reports/turtle_screen_20260622_*.json`

### 量化页「因子分析」面板
- **后端**: `GET /api/quant/factor-panel/{code}` — 返回 7 大类 59 因子的完整评分
  - 计算全部 29 个 done 因子 + 基于 A 股合理阈值 0-100 打分
  - 按分类汇总：价格/成交量/技术指标/动量/波动率/量价/基本面/情绪/资金/社交
- **前端**: 量化页新增第 5 个 Tab「因子分析」
  - 综合评分卡片（紫色左边框 + 渐变进度条）
  - 7 维因子雷达条（横向进度条 × 10 类因子）
  - 因子详情网格（2 列 × 每类因子独立打分条 + 原始值）
  - 颜色编码：绿(≥60) / 橙(40-59) / 红(<40)
  - ↑↓ 标记因子方向（正向/负向）

### 自选股 + 海龟提醒
- 楚江新材/皖维高新/汤臣倍健 加入自选股 (`watchlist` 表)
- 6 条海龟入场提醒 (`price_alerts` 表, `alert_type=turtle_s1_entry/turtle_s2_entry`)
- 提醒阈值：楚江 16.19 / 皖维 9.02 / 汤臣 10.60(S1) + 10.88(S2)

### 数据源调试踩坑
- 腾讯批量行情接口 `qt.gtimg.cn/q=` 盘前返回 volume=amount=0 → 改用市值过滤
- 腾讯市值单位为亿元 → `mcap < 5`（非 `5e8`）
- Windows 系统代理导致 akshare 无法直连东方财富 → `ProxyHandler({})` 全局禁用
- Baostock 字段偏移：`row[4]=type, row[5]=status`（非 `row[3]=type`）

### 文件变更
- 新增：`reports/turtle_screener.py` — 海龟选股脚本
- 新增：`reports/analyze_top3.py` — Top3 深度技术分析脚本
- 新增：`reports/turtle_screen_20260622_092733.json` — Top50 结果
- 修改：`backend/routers/quant.py` — +60 行 `/factor-panel/{code}` 端点
- 修改：`frontend/src/app/quant/page.tsx` — +130 行「因子分析」Tab
- 修改：`frontend/package.json` 无变更、依赖不变

---

## 2026-06-21（续）— 开源项目缝合 + K 线多面板升级

### 量化框架缝合 (4/4)
- **qlib_factor_platform** → `factor_utils.py` (20个工具函数) + `factor_service.py` 59因子注册表 + `screener.py` 3个API (因子注册表/模板/校验)
- **moonshot** → `monthly_backtest.py` (470行) + `POST /api/quant/monthly-backtest` 端点
- **QuantLessMoneyMore** → `StrategyConfig` + 多权重方案(等权/市值/评分) + 仓位限制
- **multi-factor-stock-selection** → 因子退场机制 `track_factor_performance()` + `POST /api/screener/factor-retirement`

### K 线多面板升级
- `KlineChart.tsx` 重写 (280行): 6个指标前端计算 + 多面板 (价格/MACD/RSI/KDJ/成交量)
- `stock-chart-drawer.tsx` 重写: 5个指标切换按钮 (VOL/BOLL/MACD/RSI/KDJ)
- 用户可自由组合显示哪些指标面板

### 已知问题 (TODO)
- K 线多面板: 指标切换后高度计算偶有抖动，待排查 ResizeObserver 时序
- 布林带与 MA20 颜色重叠，需区分色系
- **后端因子功能无前端 UI**: 因子注册表/模板/校验/月度回测/因子退场 5 个 API 已完成，但前端页面未接入

---

## 2026-05-20 ~ 06-10 — MVP 搭建（原始项目）

### 项目启动
- FastAPI 后端骨架 (JWT 认证、SQLite 数据库)
- Vanilla JS/HTML/CSS 前端 (12 个页面)
- AI 对话 (MiniMax/DeepSeek/OpenAI/Claude/小米)
- A股行情数据 (腾讯财经/AKShare/新浪)
- 量化分析引擎 (Sharpe/MaxDD/Beta/DCA/蒙特卡洛)
- AI 策略对抗 (多 AI 选股 PK)
- Agent 系统 (自定义 Agent + 记忆)
- 多因子选股扫描
- 大佬观点 X/Twitter 追踪
- Docker 部署配置

### 产品方向确定 (2026-05-30)
- 定位: A 股持仓追踪 + AI 分析助手 → AI 投资教练
- 新增 `review_service.py` 复盘引擎
- 新增 `review_reports` 表
- 确立 pytest 测试框架 (T1)
- 确立 Playwright E2E 测试 (T2)
- 确立 Docker 化部署 (T3)
- 确立 GitHub Actions CI/CD (T4)

---

## 2026-06-12 — Next.js + shadcn/ui 前端重构

### 技术栈升级
- Vanilla JS/HTML/CSS → `npx create-next-app@latest` (Next.js 16 App Router)
- `npx shadcn@latest init` 初始化 shadcn/ui (oklch 暗色主题)
- 配置 Tailwind CSS 4, `--radius: 0` 直角风格
- `next.config.ts` 添加 `/api/*` → `localhost:3000` 代理
- 旧 HTML/JS 前端删除，`frontend-next/` 正式上位 → `frontend/`

### 页面实现 (12 页)
- 侧边栏: 3 组折叠导航 (投资/分析/工具), 12 项中文导航
- 首页 `/`: KPI 卡片 + recharts 走势图 + DataTable + 骨架屏
- 大盘指数 `/market`: 全球 15 指数, 30s 刷新
- 自选股 `/watchlist`: 添加(500ms防抖查询)/删除/行情/加入持仓
- 交易记录 `/transactions`: CRUD + 5 KPI + AI 复盘
- 全球资讯 `/global-news`: SVG 世界地图(16金融城市) + 新闻
- AI 复盘 `/review`: KPI + 维度分析 + 改进建议 + 历史报告
- 量化分析 `/quant`: 4 Tab(个股透视/组合风险/回测/蒙特卡洛)
- AI 选股 `/screener`: 多因子扫描 + AI 精选
- 大佬观点 `/kol`: 雪球热门 + RSS + AI 日报
- AI 对话 `/ai-assistant`: Agent 选择 + 5 快捷指令 + conversationId
- AI 对抗 `/duel`: 6 AI 人格各 ¥10 万选股对战
- Agent 工坊 `/skills`: Agent CRUD + 记忆面板
- 设置 `/settings`: 6 供应商 Key + SMTP + 佣金
- 登录 `/login`: 邮箱+密码 → JWT → localStorage

### 架构变更
- 后端去掉 StaticFiles 挂载 → 纯 API 服务器 (端口 3000)
- `start.bat` 升级为双服务器控制面板

---

## 2026-06-12 ~ 06-13 — Bug 修复 + 功能增强

### Bug 修复 (15 个)
- 自选股: 现价小数位 (fund→4, etf→3, stock→2)、行情字段映射 (price vs change)、添加后数据覆盖、沪市 ETF 符号映射 (4个)
- 交易记录: `trade_date` vs `traded_at` 字段名不匹配 (1个)
- 量化分析: ETF 假数据、技术指标 undefined、组合风险全 "--"、Beta 始终 None、回测字段名、蒙特卡洛字段名、KPI 百分比 (7个)
- AI 选股: 扫描无结果、页面崩溃、名称/行业空 (3个)

### 新功能
- 持仓行业分布饼图 (`sector-pie-chart.tsx`, 暗色友好 12 色调色板)
- 手续费追踪: `calc_fee()` + `FeeConfig` + 设置页 UI + 一键重算
- 总资产走势图真实数据 (两条线: 成本灰虚线 + 市值红实线)
- KOL 代理支持
- Quant 页 `useSearchParams()` → `Suspense` 修复 `next build` 崩溃
- AI 对抗 demo 数据清理

---

## 2026-06-13 — 选股系统重大优化

### 死因子修复
- `eps_growth` 复活: Baostock 去年同期 EPS 真实增长率
- `dividend_yield` 复活: `bs.query_dividend_data()` 每股分红
- ROE 修复: Q4→Q3→Q2→Q1 逐季回退，季报自动年化
- PB 从真实值替代反推: K 线 `pbMRQ` 字段代替 PE×ROE 估算
- 因子状态: 21-22/25 → 23-25/25 有效，0 个死因子

### IC 权重从手工改为数据驱动
- 旧: 看大盘涨跌手工调权重
- 新: 截面 Spearman 秩相关，每个因子 Z-score 与 ret_20d 算秩 IC

### 并发性能优化
- 5 只股票: 141s → 6.7s (21 倍加速)
- K 线 fetch 改序: akshare→东财→Baostock (HTTP 源天然并发)
- 基本面: akshare HTTP 并发优先，失败回退 Baostock
- 行业分类全局缓存

### 社交因子 + 通知 + KOL
- 社交情绪因子: 25 → 28 个 (雪球关注数+微博情绪)
- 通知推送: 企业微信 Webhook + Telegram Bot + SMTP 邮件
- 大佬观点页: 雪球热门 + 财经 RSS + AI 摘要
- 前端 AI 选股页: 股票池选择器 (快速30/标准500/全市场)

---

## 2026-06-14 — P0 安全修复 + 多 Agent 选股 + SWR 缓存

### P0 安全 (7/7)
- S01-S04: JWT_SECRET/ADMIN_PASSWORD/CORS/EASTMONEY_TOKEN 强制校验
- S05: AI Key + SMTP 密码 AES-256-GCM 加密存储 (`crypto_service.py`)
- S06: 全局限流 slowapi (AI 20/min, 通用 60/min)
- S07: JWT 有效期 7天 → 2小时

### 多 Agent 交叉验证选股
- `services/multi_agent_service.py`: 5 个 AI 投资人格并行分析
- 聚合逻辑: 投票制(≥3/5 通过) + 加权评分 + 风险否决
- 前端新增 "5 Agent 验证" 按钮

### 多市场 + SWR
- 港股+美股行情支持 (akshare_adapter 新增 6 个函数)
- 前端 SWR 缓存层: 5 个共享 hooks (usePortfolio/useMarket/useReview/useWatchlist/useDiversification)
- 因子体系: 25→29 (新增资金类 3 因子: north_flow/margin_change/inst_change)
- AI 对抗支持多供应商对战

### 第三方审计 + ROADMAP
- 解读 7 份审计报告 (架构/代码/安全/市场/面试/项目管理/基础设施)
- 产出 `docs/ROADMAP.md` (P0-P1-P2 + 长期架构 + 产品演进)

---

## 2026-06-17 — 持仓删除 + 盈亏对齐同花顺

### Bug 修复
- Next.js API 代理端口错误 (3002→3000)
- 持仓删除功能 (AlertDialog 确认 → DELETE API → SWR 乐观更新)
- 盈亏对齐同花顺口径: 预估卖出费 + PnL/总成本×100%
- 验证: 彩虹股份 400 股，StockAI ¥308.37 vs 同花顺 ¥308.18 (差 ¥0.19)

---

## 2026-06-18 — K 线图表升级 (lightweight-charts)

### recharts → TradingView lightweight-charts v5.2
- 新增 `KlineChart.tsx`: CandlestickSeries + HistogramSeries + LineSeries ×3 (MA5/10/20)
- 删除 60+ 行废弃 recharts 代码
- 根因修复: shadcn Drawer hidden 状态下 ResponsiveContainer 返回 -1 导致初始化失败
- 新增 `stock-chart-drawer.tsx`: 右侧滑出面板 (5日/日K/周K/月K)

---

## 2026-06-21 — P1 工程规范批量修复 (10/10) + 开源缝合准备

### 工程质量批量修复
- P02: 22 个数据库索引 (零全表扫描)
- S08: 7 项安全响应头 (HSTS/CSP/X-Frame-Options 等)
- U05: subprocess curl → httpx (utils.py)
- U07: passlib → bcrypt 直接调用 (database.py + auth.py)
- P07: random.seed(42) → random.Random 独立实例 (quant_service.py)
- P10: 后端+前端依赖版本全部锁定
- T01: Next.js Proxy 统一认证守卫 (12 页删除 useEffect 重复代码)
- P08: 71 处裸 except:pass 全部消除 (9 个 services 文件 + scheduler.py)
- T03: 16 处前端 any 类型全部替换为明确类型
- P06: O(n²) → O(n) 性能修复 (500 只 8.9ms→0.1ms, 75x)

### 开源缝合准备
- 创建 `D:\some-oss\` 素材库目录
- 下载 11 个开源项目 (量化框架 4+TradingView 4+Pine Script 3)
- 制定 13 项融合任务 (F01-F13)

### 文档整合
- 旧文档 (TODOS/PROJECT_PLAN/ai-investment-coach) → 吸收到 CHANGELOG
- `docs/ROADMAP.md` 更新: 合并融合计划 + 标注已完成项
- 新增 `docs/ARCHIVE.md` 归档说明

---

> 版本演进: v3.0 (AI选股+对抗) → v3.1 (社交因子+通知) → v3.2 (K线+SWR) → v3.3 (P1工程收债+融合准备)

### 开源项目缝合准备
- 创建 `D:\some-oss\` 缝合素材库目录
- 下载 11 个开源项目：
  - 量化框架 (4): qlib_factor_platform, moonshot, QuantLessMoneyMore, multi-factor-stock-selection
  - TradingView/图表 (4): lightweight-charts(官方), lightweight-charts-python(30+指标), streamlit-lightweight-charts-v5, KLineChart
  - Pine Script (3): pinescript(QuanTAlib), pine-script-libraries, tradingview-pinescript-lab
- 1 个不可用: python-lightweight-charts (repo 404)
- 新增 `reports/stockai-status-2026-06-21.txt` — 以项目融合为核心的完整状态报告

### 数据库

**数据库索引 (P02)**
- `backend/database.py` `init_db()` 新增 22 个索引
- 覆盖: holdings / transactions / watchlist / ai_messages / price_alerts / review_reports / screener_* / backtest_results / dca_plans / dividends / ai_duel_* / kol_*
- 验证: 11/11 核心查询全部 USING INDEX，零全表扫描

### 安全

**安全响应头 (S08)**
- `backend/main.py` 新增 `security_headers_middleware`
- 7 项头: HSTS / X-Content-Type-Options / X-Frame-Options / X-XSS-Protection / Referrer-Policy / Permissions-Policy / Content-Security-Policy
- 验证: 200/401/API Docs 三种场景全部返回安全头

### 工程质量

**curl → httpx (U05)**
- `backend/services/utils.py` `run_curl()` 从 `subprocess.run(curl)` 重写为 `httpx.get()`
- 新增 `run_curl_async()` 异步版本供未来使用
- 验证: 全球指数 + 基金净值 + 新闻搜索 + K线 全部正常

**passlib → bcrypt (U07)**
- `backend/database.py` + `backend/routers/auth.py` 两处替换
- `bcrypt.verify()` → `_bcrypt.checkpw()` / `bcrypt.hash()` → `_bcrypt.hashpw()`
- `requirements.txt` 删除 `passlib[bcrypt]>=1.7`
- 验证: passlib 已卸载，登录/错误密码 全部正常

**random.seed(42) → Random 实例 (P07)**
- `backend/services/quant_service.py:503` 修复
- `random.seed(42)` (污染全局) → `rng = random.Random(); rng.seed()` (独立实例)
- 验证: 5 次模拟结果各不相同，测试 3/3 通过

**依赖版本锁定 (P10)**
- `backend/requirements.txt`: 14 个 `>=` → `==`，新增 `requests==2.32.2` + `feedparser==6.0.12`
- `frontend/package.json`: 28 个 `^` → 精确版本
- 验证: pip install --dry-run 全部满足，npm ls 无错误

**统一认证守卫 (T01)**
- 新建 `frontend/src/proxy.ts` (Next.js 16 proxy 中间件)
- cookie 检查 → 无 token 重定向 /login → 有 token 放行
- 12 个页面删除 `useEffect + isAuthenticated()` 重复代码 (~30 行)
- `frontend/src/lib/auth.ts` `setAuth()`/`clearAuth()` 同步写 cookie
- 验证: 307/200 三种路由场景正确，next build 通过

**消除裸 except pass (P08)**
- 两轮修复: 18 个文件 / 71 处
- 全部替换为 `logger.warning()` 或 `logger.debug()` + 上下文消息
- `parse_ai_json()` 的 `json.JSONDecodeError: pass` 添加注释说明降级意图
- 验证: `grep` 零残留，132/133 测试通过

**前端 any 类型消除 (T03)**
- 5 个页面: page.tsx / duel / screener / settings / quant
- 16 处 `any` 全部替换为明确类型 + 3 个新 interface
- 删除 2 条 eslint-disable 注释
- 验证: `grep` 零残留，`next build` Compiled successfully

**O(n²) 性能 Bug (P06)**
- `backend/services/screener_service.py:510`
- `stock_name_map` 从循环内移到循环外一次性构建
- 验证: 500 只股票打分 8.9ms → 0.1ms (75x 加速)

### 项目更新
- 新增 `D:\stocks\reports\stockai-status-2026-06-21.txt` — 完整项目状态报告
- 新增 `D:\some-oss\README.txt` — 开源缝合素材库目录说明

---

## 2026-06-18 — K 线图表升级（lightweight-charts）+ TradingView 集成

### 新功能

**持仓详情抽屉 — K 线图表**
- `backend/routers/holdings.py` 新增 `GET /api/stocks/kline/{code}?period=5d|1m|3m|6m` 端点
  - 直连腾讯财经 K 线 API，返回 OHLCV + MA5/MA10/MA20
  - 支持 5 日 / 日K(22天) / 周K(聚合) / 月K(聚合) 四种周期
- `backend/services/akshare_adapter.py` 修复：`get_kline()` 补充成交量字段（`k[5]`），之前遗漏导致全为 0
- `frontend/src/components/data-table.tsx` — `StockDetailDrawer` 重写
  - 点击持仓名称 → 右侧抽屉弹出 K 线蜡烛图 + 成交量柱
  - 图表顶部摘要：现价/成本/持仓/盈亏
  - 周期切换标签：5日 | 日K | 周K | 月K
  - MA5(琥珀)/MA10(紫)/MA20(青) 均线叠加
  - 鼠标悬停显示开/高/低/收/量

**K 线图表升级 — lightweight-charts（TradingView）**
- 新增 `frontend/src/components/KlineChart.tsx`（新建组件）
  - 替换 recharts `ComposedChart` + 自定义 Bar shape → TradingView `lightweight-charts@5.2.0`
  - 内置 CandlestickSeries（蜡烛图）+ HistogramSeries（成交量）+ LineSeries（MA5/10/20）
  - 原生 ResizeObserver 支持，Drawer 打开时自动检测正确尺寸
  - v5 API：`chart.addSeries(CandlestickSeries, options)`
- `frontend/src/components/stock-chart-drawer.tsx` — 同上替换
- 删除了 `data-table.tsx` 中 60+ 行废弃代码（`KlineBar`/`BarShapeProps`/`KlineTooltip`/`toBars`/`renderCandle`/`renderVolume`）
- **根因修复**：recharts `ResponsiveContainer` 在 shadcn Drawer hidden 状态下初始化时返回宽高 -1，导致 chart 初始化失败

**Accessibility 修复**
- `DrawerContent` 添加 `DrawerDescription`（sr-only），消除 React a11y 警告

### Bug 修复

**持仓概览显示问题**
- Bug #21: 持仓名称显示为录入时的名字（如 "rainbow"） → 优先使用实时行情 API 返回的名称
- Bug #22: "持仓占比" 标签名误导 + 用 `Math.round(市值/成本-1)` 独立计算导致精度丢失 → 标签改为"总收益率"，直接使用后端 `total_pnl_pct`（已扣预估卖出费）

### 技术依赖

- `lightweight-charts@^5.2.0` — TradingView 开源金融图表库（MIT）
  - 参考：https://tradingview.github.io/lightweight-charts/
  - TradingView Pine Script 指标生态丰富，后续可对接更多指标

### 已知问题

- K 线图表：鼠标悬停 OHLCV 数字显示可进一步优化（lightweight-charts crosshair label）
- 成交量下方未显示具体数字，只有柱状高度
- 分钟级 K 线数据源未接入（东财 `klt=1/5/15/30/60` 未接入）

---

## 2026-06-17 — 持仓删除功能 + 盈亏对齐同花顺

### Bug 修复 (2 个)

**全局**
- Bug #19: Next.js API 代理端口错误 — `next.config.ts` 将 `/api/*` 转发到 `localhost:3002`（空端口），导致所有前端 API 请求失败。改为 `localhost:3000`。
- Bug #20: 持仓删除功能缺失 — `page.tsx` 的 `onDelete` 回调只有 `alert("删除 暂未实现")`。加入完整删除链路：AlertDialog 确认 → `DELETE /api/stocks/holdings/{id}` → SWR 乐观更新。

### 新功能

**盈亏对齐同花顺**
- `backend/routers/holdings.py` 新增 `_estimate_sell_fee()` 函数，预估卖出费用（佣金 + 印花税 0.05% + 过户费 0.002%）
- 盈亏公式改为同花顺口径：`PnL = (现价 - 成本价) × 数量 - 预估卖出费`
- 盈亏% 改为：`PnL / 总成本 × 100%`（之前是 `现价/成本 - 1`）
- 汇总端也改为逐项 net PnL 求和，不再用总市值减总成本
- 验证结果：彩虹股份 400 股，StockAI vs 同花顺 → 盈亏 ¥308.37 vs ¥308.18（差 ¥0.19 来自成本价小数位精度）

**持仓删除**
- `frontend/src/app/page.tsx`：引入 AlertDialog 确认弹窗 + `handleDelete` 调用 `DELETE /api/stocks/holdings/{id}`
- SWR 乐观更新：删除后立即从缓存移除该行，不等网络返回
- `HomeHolding` 类型增加 `id` 字段，`tableData` 增加 `holdingId` 传递真实数据库 ID

### 费率验证

- 核查同花顺交割单：佣金 5 元/笔（万 2.5 兜底）、印花税仅卖出、过户费未单独列
- StockAI 默认费率与券商一致：`commission_rate=0.00025, commission_min=5.0`

### 已知问题

- 端口 3000 僵尸进程（PID 3476）：Windows TCP 端点泄露，进程已死但端口被内核卡住。`taskkill`/`Stop-Process`/`wmic`/管理员权限均无法释放，需重启系统。当前临时用 3008 端口。

---

## 2026-06-12 ~ 2026-06-13 — Bug 修复 + 功能增强

### Bug 修复 (6 个)

**自选股**
- Bug #1: ETF/基金现价小数位 — `fund→4, etf→3, stock→2`，添加 `decimals()` 辅助函数
- Bug #2: 行情字段映射错误 — `price ?? change ?? 0` 导致涨跌额当现价，改为独立 null 检查
- Bug #3: 添加自选后数据覆盖 — quotes 失败时覆盖已有数据，改为过滤 error + 只在有效值才覆盖
- Bug #6: 沪市 ETF 符号映射 — `_symbol()` 漏了 51/56/58 前缀，导致请求到 `sz` 接口返回空数据

**交易记录**
- Bug #4: 添加交易失败 — 前端 `trade_date` vs 后端 `traded_at` 字段名不匹配

**持仓概览**
- 现价/成本/总资产/今日盈亏/盈亏统一显示两位小数
- PnL 列从 `Math.round()` 改为 `toFixed(2)`

**量化分析**
- Bug #5: ETF 行情假数据 — 腾讯 API 对部分 ETF 返回 name="北京2474" price=100.0，加检测+兜底
- Bug #10: 技术指标显示 "undefined" — MA/MACD/KDJ 是多键对象，前端不当读 `val.value`
- Bug #11: 组合风险指标全显示 "--" — Sharpe/回撤/波动率被绑在基准数据上，分离计算
- Bug #12: Beta 始终为 None — 沪深 300 指数无法从 K 线源获取，改用 510300 ETF 代理
- Bug #14: 回测/策略对比字段名不匹配 — `dca_return`→`total_return`, `return_pct`→`return`
- Bug #15: 蒙特卡洛亏损概率 "--" — `loss_prob`→`prob_loss`, `loss_15_pct`→`prob_loss_15pct`
- KPI 百分比修正：回撤/波动率 × 100 显示

**AI 选股**
- Bug #16: 扫描后无结果 — `/results` 返回 `{candidates:[...]}` 但前端当数组处理
- Bug #17: 页面崩溃 — `top_factors` 是对象数组，直接渲染 `{f}` 报 React 错误
- Bug #18: 名称/行业为空 — `_process_single_stock` 不从 stock_list 取名字，加兜底逻辑
- 评分显示 `toFixed(0)` → `toFixed(1)`

**全局 UI**
- 全站 `<select>` 下拉框 `bg-transparent` → `bg-background text-foreground`（暗色模式可见）

### 新功能

**持仓分析 — 行业分布饼图**
- `frontend/src/components/sector-pie-chart.tsx` — recharts 环形饼图
- `page.tsx` 集成：调用 `/api/stocks/diversification`，KPI 和图表之间展示
- 暗色友好 12 色调色板，悬停显示行业名/占比/市值

**手续费追踪**
- `backend/services/utils.py` — `calc_fee()` + `FeeConfig`：stock/etf 自动计算佣金/印花税/过户费
- 佣金率可配置：`settings` 表存储，设置页面 UI，`GET/PUT /api/settings/fee-config`
- 费用计入 amount（买入 +fee，卖出 -fee），自动流入成本重算/PnL/XIRR
- `POST /api/stocks/recalc-fees` — 一键重算所有历史交易手续费并更新持仓成本
- 交易页面：佣金列 + 自动/手动切换 + 总佣金 KPI 卡片

**总资产走势图真实数据**
- `GET /api/stocks/holdings/history` — 累计成本日线 + 当前市值
- `ChartAreaInteractive` 重写：两条线（成本灰虚线 + 市值红实线），真实日期

**KOL 大佬观点 — 代理支持**
- `backend/services/kol_crawler.py` — `_get_proxy()` 从环境变量/`settings` 表读取代理
- `PUT /api/kol/proxy` — 设置/清除爬虫代理
- `PUT /api/kol/proxy` — 获取当前代理配置

### 技术改进
- 复盘页面：修复 `total_trades` 只统计卖出导致冷启动；generate 后不再重复 `fetchLatest` 闪烁
- 复盘门槛：5→3 笔交易即可生成
- `useRef` TS 修复：`useRef<ReturnType<typeof setTimeout>>(null)`
- 数据库迁移：`transactions` 表加 `fee` 列 ALTER TABLE 兜底

---

## 2026-06-12 — Next.js + shadcn/ui 前端重构

### 项目初始化
- `npx create-next-app@latest frontend-next` — 创建 Next.js 16 (App Router) 项目
- `npx shadcn@latest init --preset b3ZNO4HQhu` — 初始化 shadcn/ui 主题 (oklch 中性色)
- 配置 Tailwind CSS 4 `@theme inline` 字体：系统中文字体栈 + JetBrains Mono
- 默认暗色模式 (`<html class="dark">`)
- `--radius: 0` 全局直角风格
- `next.config.ts` 添加 `/api/*` → `localhost:3000` 代理

### 侧边栏
- 安装 `sidebar` `collapsible` `tooltip` shadcn 组件
- 创建 `app-sidebar.tsx`：12 项中文导航，3 折叠组 (投资/分析/工具)
- `SidebarProvider` + `TooltipProvider` 包裹根布局
- `app-layout.tsx` 客户端布局组件，登录页自动隐藏侧边栏
- `usePathname()` 自动高亮当前路由

### 首页：持仓概览
- 融合 dashboard-01 模板的 SectionCards → ChartAreaInteractive → DataTable 三段式布局
- 安装 `card` `button` `input` `label` `separator` `badge` `table` `dropdown-menu` `checkbox` `drawer` `tabs` `select` `toggle-group` `breadcrumb` `avatar` `chart` 等组件
- KPI 卡片 (总资产/今日盈亏/持仓数量/持仓占比)
- recharts 面积图 (总资产走势，红色)
- DataTable 持仓表格 (可拖拽排序/分页/列显隐/详情抽屉)，红涨绿跌

### 大盘指数 `/market`
- 对接 `GET /api/stocks/indices/global`
- 按地区分组 (中国/美国/欧洲/亚太)，响应式网格 (1-4 列)
- 指数卡片：名称/代码/现价/涨跌额/涨跌幅，红涨绿跌
- 30 秒自动刷新 + 手动刷新按钮
- 骨架屏加载 + 错误重试

### 全球资讯 `/global-news`
- 对接 `GET /api/stocks/news/global/{region}`
- SVG 世界地图 (深海色背景 + 经纬网 + 大陆点阵)
- 16 个金融中心城市点 (脉冲动画 + 标签)
- 资本流动曲线连线
- 顶部地区快捷标签栏 + 右侧新闻面板
- 点击新闻外链跳转

### AI 复盘 `/review`
- 对接 `POST /api/stocks/review/structured` + `GET /api/stocks/reviews`
- 3 列统计卡片 (总盈亏/交易次数/综合评分)
- AI 洞察紫色左边框卡片
- 交易维度分析折叠面板 (高/中/低评分彩色标签)
- 改进建议卡片 (查看理由/收起理由切换)
- 历史报告下拉选择器

### 量化分析 `/quant`
- 对接 `GET /api/quant/stock-insight/{code}` `/api/quant/portfolio-risk` `/api/quant/backtest` `/api/quant/compare` `/api/quant/monte-carlo`
- 股票输入 + 周期选择 → K线图 (recharts AreaChart)
- 技术指标网格 (MA/MACD/KDJ/RSI + 信号标签)
- 基本面因子行 (PE/ROE/EPS/市值/行业)
- 组合风险 Tab：Sharpe/最大回撤/波动率/Beta + 相关性标签
- 策略回测 Tab：定投回测 + 4 策略对比
- 蒙特卡洛 Tab：模拟参数 + 终值分布柱状图 (红涨绿跌)

### AI 选股 `/screener`
- 对接 `POST /api/screener/run` `GET /api/screener/results` `POST /api/screener/ai-screen` `POST /api/screener/backtest/batch` watchlist CRUD
- 操作栏：开始扫描/进度条/AI精选/一键流程
- 左列：多因子候选池表格 (评分条+因子标签+回测+加入盯盘)
- 右列：AI 精选卡片 (紫色推理文本) + 盯盘列表 (删除)
- 扫描进度轮询 (2 秒间隔)

### 大佬观点 `/kol`
- 对接 `GET /api/kol/accounts` `POST /api/kol/crawl` `GET /api/kol/briefs/latest` `POST /api/kol/briefs/generate`
- 操作栏：刷新帖子(爬取)/生成日报/添加账号
- 追踪账号标签条 (删除按钮 + 停用账号划线)
- 添加账号表单 (X用户名/显示名/分类)
- AI 日报卡片：摘要/情绪柱 (牛/中/熊)/热议话题/牛熊观点/提及股票/金句引用

### 交易记录 `/transactions`
- 对接 `GET/POST/PUT/DELETE /api/stocks/transactions`
- 4 KPI 统计卡片 (总交易/买入额/卖出额/净额)
- 添加/编辑表单 (代码/名称/类型/方向/价格/数量/日期/备注)
- 交易表格 (日期/股票/方向标签/价格/数量/金额/备注)
- AI 复盘按钮 (紫色左边框结果卡片)

### AI 对话 `/ai-assistant`
- 对接 `GET /api/agents/agents` `POST /api/ai/chat`
- Agent 下拉选择器 + 工具标签
- 5 个快捷指令标签 (分析持仓/交易复盘/定投建议/市场概览/持仓新闻)
- 聊天气泡 (用户/助手/错误/加载中)
- 对话持久化 (conversationId)

### Agent 工坊 `/skills`
- 对接 `GET/POST/PUT/DELETE /api/agents/agents` `GET/POST /api/agents/{id}/memory`
- Agent 卡片网格 (名称/描述/工具标签/操作按钮)
- 创建/编辑表单 (名称/描述/系统提示词/工具勾选)
- 记忆面板 (紫色左边框，时间戳条目，添加记忆输入框)

### 设置 `/settings`
- 对接 `GET/PUT /api/settings/ai-configs` `GET/PUT /api/settings/smtp` `POST /api/settings/smtp/test`
- 6 家 AI 供应商配置 (MiniMax/DeepSeek/OpenAI/Claude/小米/自定义)
- 每供应商：API Key 密码框 + Model 输入 + Base URL 输入
- SMTP 邮件配置 (服务器/端口/邮箱/密码/用户名)
- 测试发送 + 退出登录按钮

### 自选股 `/watchlist`
- 对接 `GET/POST/DELETE /api/stocks/watchlist` `GET /api/stocks/lookup/{code}` `POST /api/stocks/quotes`
- 代码自动查询 (500ms 防抖) + 市场/类型自动检测
- 批量行情报价 (30 秒自动刷新)
- 表格：代码/名称/现价/涨跌幅/涨跌额/成交量/最高/最低
- 操作：加入持仓(数量+成本价弹窗) / 跳转量化分析 / 移除(AlertDialog确认)

### 登录 `/login`
- 对接 `POST /api/auth/login` JWT 认证
- `lib/auth.ts` 封装 Token 管理 + `apiGet`/`apiPost` 认证请求
- 未登录自动跳转 `/login`

### 架构变更
- 后端去掉 `StaticFiles` 挂载 → 纯 API 服务器 (端口 3000)
- `frontend-next/` → `frontend/` (正式上位，旧 HTML/JS 前端删除)
- `start.bat` 升级为双服务器控制面板 (后端+前端)
- `next.config.ts` 添加 `devIndicators: false` 隐藏开发标记

### 项目清理
- 删除 `__pycache__/` × 3、`.pytest_cache/`、`.next/` 构建缓存
- 删除空目录 `backend/config/` `routes/` `models/`、`skills/`
- 删除测试脚本 `test_playwright.py` `test_twikit.py` `test_x_api.py` `extract_x_queries.py`
- 删除模板残留 `frontend/src/app/dashboard/`
- 删除调试文件 `x_response_debug.json`、`BRANCH=main/`
- Docker 文件归档到 `docker/`
- Python 配置移到 `backend/` (pytest.ini, requirements-dev.txt, .env.example)
- 归档文档到 `docs/` (PROJECT_PLAN.md, TODOS.md)
- 删除 `SKILLS.md`、frontend 模板 README/AGENTS/CLAUDE

### 文档更新
- `DESIGN.md` — 全面更新 (Next.js + shadcn/ui 架构、Tailwind CSS 4、组件模式、决策日志)
- `README.md` — 更新项目结构、启动方式、路由表、技术栈
- `CHANGELOG.md` — 本项目日志 (新建)

### 已知问题 (待修)
- 自选股：ETF/基金现价小数位不准确，行情数据字段映射错误
- 交易记录：添加交易功能有问题
- 性能：每次页面切换数据重新加载，需引入 SWR 缓存

---

## 2026-05-20 ~ 2026-06-10 — 原始项目搭建

### MVP 阶段
- FastAPI 后端骨架 (JWT 认证、SQLite 数据库)
- Vanilla JS/HTML/CSS 前端 (12 个页面)
- AI 对话 (MiniMax/DeepSeek/OpenAI/Claude/小米)
- A股行情数据 (腾讯财经/AKShare/新浪)
- 量化分析引擎 (Sharpe/MaxDD/Beta/DCA/蒙特卡洛)
- AI 策略对抗 (多 AI 选股 PK)
- Agent 系统 (自定义 Agent + 记忆)
- 多因子选股扫描
- 大佬观点 X/Twitter 追踪
- Docker 部署配置
