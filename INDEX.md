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
│   ├── V4-PLAN.md                  ← ✅ v4.0+v4.1 已发布 / v4.2 候选
│   ├── RELEASE-NOTES-v4.0.md       ← v4.0 release notes
│   └── RELEASE-NOTES-v4.1.md       ← v4.1 release notes
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
- **当前版本**: **v5.0-alpha M4** (2026-08-01,准实盘量化战略启动)
- **下一大版本**: v5.0-alpha M5(盘中 WebSocket 推送)
- **核心能力**: v4.1.1 全量 + **v5.0-alpha 新增**: 实时行情接入(M1)/ 盘中因子缓存 5m TTL(M2)/ 盘中信号扫描 + 手动确认下单(M3)/ **`/live` 仪表板前端(M4)**
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
| **✅ v4.0+v4.1 已发布 / v4.2 候选** | **`stockai-project-docs/V4-PLAN.md`** |
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

## 🛡️ 敏感信息策略

- `.env` / `*.db` / `*.db-wal` / `*.log` 全部 `.gitignore`
- README / CHANGELOG 中所有密钥仅用占位符(`<...>` / `xxx`)
- **永不 commit 真实密钥**,即使本地测试也要走环境变量

---

## 📝 文档历史

- **2026-07-26**: v4.0 计划完整敲定(D1-D4)— AI 选股智能化 + T+1/T+2 短线预测
- **2026-07-26**: README 三件套重写(高级版 + 合并 v3.11 重复项 + 英文同步) + 架构图删除
- **2026-07-26**: MD 文件分类整理 + 后端监视器 v0.1.0 引入