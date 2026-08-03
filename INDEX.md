# StockAI — 项目根目录入口

> 欢迎来到 StockAI 项目。本文件是根目录入口,导航所有文档。

---

## 📁 文档结构(2 个文件夹 + 2 个根目录入口)

```
D:\stocks\
├── README.md                       ← 🌍 GitHub 仓库主页(英文 badges + 中文简介)
├── INDEX.md                        ← 🧭 本文件(开发者导航)
├── CLAUDE.md                       ← 🤖 Claude Code 入会必读
│
├── stockai-project-docs/           ← 📘 StockAI 项目 MD
│   ├── README.md                   ← 项目主入口(与根目录 README 同步)
│   ├── README.en.md                ← English(英文版)
│   ├── CHANGELOG.md                ← 完整变更日志
│   ├── DESIGN.md                   ← 设计系统(权威)
│   ├── TODOS.md                    ← 待办
│   ├── AGENTS.md                   ← Agent 工作流
│   ├── V4-PLAN.md                  ← ✅ v4.0+v4.1+v4.2+v5.0-alpha 已发布 / v5.0-beta 候选
│   ├── RELEASE-NOTES-v4.0.md       ← v4.0 release notes
│   ├── RELEASE-NOTES-v4.1.md       ← v4.1 release notes
│   ├── RELEASE-NOTES-v4.2.md       ← v4.2 M1 release notes
│   ├── RELEASE-NOTES-v4.2-m2.md    ← v4.2 M2 release notes
│   └── RELEASE-NOTES-v5.0.md       ← v5.0-alpha release notes
│
├── docs/                           ← 📦 历史归档 + 路线图(早期内容)
│   ├── ROADMAP.md                  ← 路线图(v3.6 时代,历史)
│   ├── RUNBOOK.md                  ← 运行手册(legacy)
│   ├── ARCHIVE.md                  ← 归档说明
│   ├── README.md                   ← docs 目录入口
│   ├── fees-audit.md               ← 手续费审计
│   ├── designs/                    ← 设计稿
│   └── superpowers/                ← 旧 spec
│
└── monitor-desktop-docs/           ← 🖥️ 后端监视器 MD
    ├── PLAN.md                     ← 监视器计划(技术栈/UI/10 决策)
    └── DAILY-LOG.md                ← 监视器每日改动日志
```

---

## 🎯 项目说明

### StockAI 主项目

- **类型**: A 股量化研究 + 回测 + 预测
- **后端**: Python FastAPI (端口 3000)
- **前端**: Next.js 16 (端口 3001)
- **数据库**: SQLite (WAL 模式)
- **当前版本**: **v4.2.1** (2026-08-03 tag,M1 + M2 打包)
- **下一大版本**: v5.0-beta(WS 推送 / 分钟级 K 线 / 多用户 / 通知集成)
- **核心能力**: v5.0-alpha 全量 + **v4.2 新增**:
  - **M1**: T+1 watcher 6 态机(OSS 风格) + transition() 守卫 + t1_order_events 事件溯源 + partial_filled 字段
  - **M2**: factor_service 55 因子分钟级对齐 + compute_minute_factors() + minute_factor_cache 5m TTL + REST `/api/realtime/factor/{code}/minute` + 前端 hook/组件
  - 详见 [`RELEASE-NOTES-v4.2.md`](stockai-project-docs/RELEASE-NOTES-v4.2.md) + [`RELEASE-NOTES-v4.2-m2.md`](stockai-project-docs/RELEASE-NOTES-v4.2-m2.md) + [`RELEASE-NOTES-v5.0.md`](stockai-project-docs/RELEASE-NOTES-v5.0.md)
- **项目入口**: `stockai-project-docs/README.md`
- **GitHub 主页**: `README.md` (根)

### 后端监视器(独立子项目)

- **类型**: Electron 桌面 app,**纯观察,deep freeze**
- **位置**: `D:\stocks\monitor-desktop/`(代码) + `monitor-desktop-docs/`(文档)
- **当前版本**: v0.1.0
- **特点**: 独立 gitignore,**对 stockai 0 改动**
- **计划**: `monitor-desktop-docs/PLAN.md`
- **每日改动**: `monitor-desktop-docs/DAILY-LOG.md`

---

## 🚀 快速索引

| 我想看... | 打开这个文件 |
|----------|--------------|
| GitHub 主页展示 | `README.md` (根) |
| 项目详细介绍(中文) | `stockai-project-docs/README.md` |
| English version | `stockai-project-docs/README.en.md` |
| 完整变更历史 | `stockai-project-docs/CHANGELOG.md` |
| 设计规范 | `stockai-project-docs/DESIGN.md` |
| 项目路线图 | `docs/ROADMAP.md` |
| 运行手册 | `stockai-project-docs/RUNBOOK.md` |
| 待办事项 | `stockai-project-docs/TODOS.md` |
| Agent 工作流 | `stockai-project-docs/AGENTS.md` |
| **✅ v4.0+v4.1+v4.2 已发布 / v5.0-beta 候选** | **`stockai-project-docs/V4-PLAN.md`** |
| **v4.2 M1 release notes** | **`stockai-project-docs/RELEASE-NOTES-v4.2.md`** |
| **v4.2 M2 release notes** | **`stockai-project-docs/RELEASE-NOTES-v4.2-m2.md`** |
| **v5.0-alpha release notes** | **`stockai-project-docs/RELEASE-NOTES-v5.0.md`** |
| 监视器计划 | `monitor-desktop-docs/PLAN.md` |
| 监视器改动 | `monitor-desktop-docs/DAILY-LOG.md` |
| 文档归档说明 | `stockai-project-docs/ARCHIVE.md` |

---

## 📂 目录约定

| 目录 | 用途 |
|------|------|
| `backend/` | StockAI 后端 FastAPI |
| `frontend/` | StockAI 前端 Next.js |
| `tests/` | StockAI 测试 |
| `docs/` | StockAI 文档(部分保留,已分离大部分到子目录) |
| `database/` | StockAI SQLite 数据库文件 |
| `scripts/` | StockAI 辅助脚本 |
| `reports/` | StockAI 运行报告(quant brief) |
| `stockai-project-docs/` | **Project MD 一类** |
| `monitor-desktop-docs/` | **Monitor MD 一类** |
| `monitor-desktop/` | 监视器代码(已 gitignore node_modules/dist 等) |

---

## 📋 同步清单(每次更新后)

**这是给 Claude Code 的备忘 — 任何对 stockai 主项目的改动都要同步:**

| 场景 | 需要同步的 MD |
|------|---------------|
| **新功能交付 / 大版本发布** | `README.md`(根)+ `stockai-project-docs/README.md` + `README.en.md` + `CHANGELOG.md` + `V4-PLAN.md`(状态更新) |
| **设计变更(配色 / 字体 / 组件)** | `stockai-project-docs/DESIGN.md` |
| **Bug 修复** | `stockai-project-docs/CHANGELOG.md` |
| **路线图更新** | `docs/ROADMAP.md` |
| **监视器改动** | `monitor-desktop-docs/PLAN.md`(状态) + `DAILY-LOG.md` |
| **启动 / 部署 / 故障排查** | `stockai-project-docs/RUNBOOK.md` |
| **新建 MD 文件 / 重构目录** | `INDEX.md`(本文件) |

**同步后必须做的事**: `git add` + `git commit` + `git push` 到 `main`,确认 GitHub 渲染正常。

---

## 🆕 v4.1.1 新增内容(2026-07-30 patch)

| 项 | 文件 | 说明 |
|----|------|------|
| YAML 策略注册中心 | `backend/services/strategy_registry.py` | 自动扫描 + 校验,加新策略无需改代码 |
| RSRS 阻力支撑因子 | `factor_service.factor_rsrs` | OSS 移植的经典 alpha |
| 仓位算法库 | `backend/services/risk_sizing.py` | Kelly / RiskParity / VolTarget |
| 风控守护 | `backend/services/risk_guard.py` | 4 规则纯函数评估器 |
| T+1 风控拦截 | `t1_watcher._evaluate_buy_risk` | 单仓位 > 30% 拒单 + 通知 |
| 因子退役 → 通知 | `factor_lifecycle._notify_lifecycle_changes` | 自动推送 |

**修复**:
- `_calc_impact_cost_bps` look-ahead bias(回测 2024 不再用 2026 真实 ADV)
- `_load_strategy_conditions` 路径不一致(registry 与 loader 共享 `yaml_path`)

**dev DB 5 年 seed**:
- `index_kline`: 180 → 7500 rows(2021-06 → 2026-07)
- `etf_kline`: scheduler 17:10 nightly 自动补

**OSS 学习来源**: `D:\some-oss\quant-trading-system`(commit `edfdd89`)

---

## 🆕 v4.2.1 新增内容(2026-08-03 — M1 + M2 打包 tag)

| 项 | 文件 | 说明 |
|----|------|------|
| **M2 55 因子分钟级** | `factor_service.MINUTE_FACTOR_REGISTRY` | 5 元组 (fn, needs_vol, needs_hilo, needs_open, fn_volumes_only) |
| **`compute_minute_factors()`** | `factor_service.py` | 复用 55 个 `factor_xxx` 函数, 大写 key 自动归一化 |
| **`realtime_factor_minute.py`** | `services/` 新 | 5m TTL 缓存 + `compute_minute_factors_with_cache` + `fetch_recent_bars` |
| **`minute_factor_cache` 表** | `database.py` | 独立于 realtime_factor_cache, 后续 v5.0-rc 可独立调 TTL |
| **REST 3 端点** | `routers/realtime_factor_minute.py` 新 | GET `/api/realtime/factor/{code}/minute` + invalidate + factor-names |
| **前端 hook + 组件** | `hooks/use-realtime-minute-factor.ts` + `components/realtime-minute-factor-card.tsx` 新 | SWR 30s + 4 组核心因子卡片 |

**触发原因**:
v5.0-strategy.md §3.4 M5「实时因子计算(55 因子分钟级)」前置,M1 + M2 一起打 tag v4.2.1。

---

## 🆕 v4.2 M1 新增内容(2026-08-02 — T+1 watcher N 态机)

| 项 | 文件 | 说明 |
|----|------|------|
| **6 态状态机(OSS 风格)** | `t1_watcher.py` 6 状态常量 + `_ALLOWED_TRANSITIONS` | open / partial_filled / filled / closed / cancelled / rejected |
| **transition() 守卫函数** | `t1_watcher.transition()` | CAS 校验 + 白名单 + 同事务 audit 写入 |
| **事件溯源表** | `database.py` + `t1_order_events` 表 | append-only 审计,整条订单生命周期可回放 |
| **partial_filled 字段** | `t1_pending_orders` 加 `filled_shares` / `pending_shares` | bulk_approve 资金不足场景预留 |
| **迁移脚本** | `scripts/migrations/v4.2_m1_add_t1_order_events.sql` | dev DB 手动 apply 兼容 |
| **查询双谓词兼容** | `t1_watcher.process_pending_buys/sells` / `get_user_orders` / `summarize_user_pnl` | 老字面量 0 迁移,跨 deployment 不丢数据 |

**修复**:
- 4 处状态变更点( `cancel_order` / `_simulate_buy` / `_simulate_sell` / `_cancel_blocked_order`)全部走 transition(),统一审计入口
- `_cancel_blocked_order` 增加 `event_type='risk_blocked'` 写 audit,带 `metadata=risk_result`

**触发原因**:
v5.0-strategy.md §3.2「若 T+1 watcher N 态 和 因子分钟级 各需要 ≥ 1 周,先开 v4.2」,M1 完成,M2(因子分钟级)继续推进中。

---

## 🛡️ 敏感信息策略

- `.env` / `*.db` / `*.db-wal` / `*.log` 全部 `.gitignore`
- README / CHANGELOG 中所有密钥仅用占位符(`<...>` / `xxx`)
- **永不 commit 真实密钥**,即使本地测试也要走环境变量

---

## 📝 文档历史

- **2026-08-03**: v4.2 M2 文档同步 — RELEASE-NOTES-v4.2-m2.md 新建 + CLAUDE.md / INDEX.md / CHANGELOG.md 当前版本 v4.2.1
- **2026-08-02**: v4.2 M1 文档三件套同步(CLAUDE.md / INDEX.md / CHANGELOG.md 当前版本 + RELEASE-NOTES-v4.2.md 新建 + git tag v4.2)
- **2026-08-01**: v5.0-alpha 完成 + tag v5.0(M1-M4 共 69 测试)
- **2026-07-30**: v4.1.1 patch3(5 项 bug 修复)+ v4.1 测试套件 168/168 全过
- **2026-07-30**: v4.1 收尾(Phase 2A/2B — 真实基准 + Drift 监控)
- **2026-07-28**: v4.0 正式发布(8 角色多 Agent + CoT + 工具调用 + 64 因子)
- **2026-07-26**: v4.0 计划完整敲定(D1-D4)— AI 选股智能化 + T+1/T+2 短线预测
- **2026-07-26**: README 三件套重写(高级版 + 合并 v3.11 重复项 + 英文同步) + 架构图删除
- **2026-07-26**: MD 文件分类整理 + 后端监视器 v0.1.0 引入