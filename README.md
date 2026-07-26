<div align="center">

# StockAI

### A 股 AI 量化选股 · 研究→决策证据闭环

**55 因子 · 13 策略 · 5 角色多 Agent · 自动量化 Pipeline · 后端监视器**

![Version](https://img.shields.io/badge/version-v3.11-success?style=flat-square)
![Python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?style=flat-square&logo=next.js&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?style=flat-square&logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

[English](stockai-project-docs/README.en.md) · [中文](#) · [文档导航](INDEX.md)

</div>

---

## 🎯 TL;DR

StockAI 是一个**纯本地化**的 A 股量化工具箱,定位**预测 + 回测**,不接实时交易。

- **多因子选股**: 55 因子(9 大类) + IC 加权打分 + AI 二次精选 + 5 角色多空辩论
- **策略回测**: 13 YAML 策略模板 + 参数优化 + 滑点/成本模型 + 过拟合警告
- **证据闭环**: v3.11 新增 — 三轴状态机 + OOS 快照 + 影子组合 + 审批收件箱 + 灰度 flag,**所有决策可追溯**
- **自动 Pipeline**: 每日收盘后 cron 跑 GP→ML→衰减→数据健康→简报推送
- **后端监视器**: Electron 桌面 app,实时观察 stockai 后端进程 / 日志 / 数据库

> 📖 完整文档: [stockai-project-docs/](stockai-project-docs/) · 📋 监视器: [monitor-desktop/](monitor-desktop/)

---

## 🏗️ 架构一览

```
┌────────────────────────────────────────────────────────────────────┐
│                    StockAI v3.11 系统架构                            │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ① 研究层 (R)              ② 决策层 (D)            ③ 执行层 (E)   │
│   ┌──────────────┐          ┌──────────────┐        ┌───────────┐ │
│   │ 55 因子计算  │          │ 多 Agent     │        │ 影子组合  │ │
│   │ GP/ML 挖掘   │  ──────► │ 多空辩论     │ ─────► │ T+1 模拟  │ │
│   │ IC/相关性    │   信号   │ 置信度评分   │  决策  │ 整手/缺价 │ │
│   │ 散点图       │          │ 风险一票否决 │        │ 单飞锁    │ │
│   └──────────────┘          └──────────────┘        └───────────┘ │
│         │                          │                     │         │
│         ▼                          ▼                     ▼         │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │              SQLite (WAL 模式, 25+ 表)                     │    │
│   │   experiments / snapshots / shadow_portfolio / proposals    │    │
│   └──────────────────────────────────────────────────────────┘    │
│                                                                     │
│   ④ Pipeline: cron 18:00 → GP→ML→衰减→数据健康→简报推送 (T+1)      │
│   ⑤ 监控: Electron 监视器(进程/日志/DB,只读不写)                   │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## ✨ 核心能力

| 模块 | 描述 |
|------|------|
| 🔍 **AI 选股** | 全市场多因子扫描 → IC 加权 → AI 精选 → 板块过滤 → 回测 → 盯盘 |
| 🎯 **条件选股** | L1-L4 四层过滤 + 13 YAML 策略 + 参数可调 + 来源说明 |
| 🎛️ **参数优化** | 网格搜索(上限 300 组),按最大回撤→夏普排序 |
| 📊 **策略回测** | 18 模板 + 手续费自动计入 + 买卖点 K 线标注 + 过拟合警告 |
| 🤖 **多 Agent 分析** | 5 角色多空辩论 → 结构化决策(买入/持有/卖出+置信度) |
| 🧠 **交易记忆** | 决策→验证→反思→注入 自动闭环,策略维度追踪 |
| 📋 **AI 月报** | 月度聚合 → AI 结构化报告 + 上月对比诊断 |
| 🛡️ **交易纪律** | 买入前强制校验 + 连亏保护 3 级 + 行动建议 |
| 🔬 **因子实验室** | IC/相关性/散点 + GP 遗传编程 + LightGBM ML 因子 |
| 🧠 **AI 对话** | SSE 流式响应,5 供应商独立路由(Claude/DeepSeek/OpenAI/MiniMax/Xiaomi) |
| 📡 **数据源** | Futu→新浪→AKShare→Baostock fallback,环境变量切换 |
| 🖥️ **后端监视器** | Electron 桌面 app · 5 模块 · 只读 · **详见 [monitor-desktop/](monitor-desktop/)** |

---

## 🆕 v3.11 — 研究→决策证据闭环

5 个核心模块协同,实现**决策可追溯 + 反事实可对比**:

| 模块 | 作用 | 关键能力 |
|------|------|---------|
| **T1 实验账本** | 因子候选的全生命周期管理 | 三轴状态机 (lifecycle/portfolio_role/proposal) + 版本 CAS + append-only 审计 |
| **T2 OOS 快照** | 冻结假设,防数据穿越 | snapshot_hash + point-in-time replay + leakage 检测 |
| **T3 影子组合** | 收盘后模拟实盘 | T+1 执行 + 整手(100 股) + 缺价 blocked + UNIQUE 防重复 |
| **T4 审批收件箱** | 人工最终决策 | TTL lease + 三层 CAS + counterfactual 复盘 |
| **T5 灰度开关** | 安全渐进上线 | 5 个 feature flag (默认 OFF) + 一键回 OFF + notification_log 独立审计 |

> 跑通后,任何一笔影子组合决策都能追溯到:因子表达式 → 历史回测 → OOS 验证 → 多 Agent 投票 → 人工审批 → 实际表现 → 反思注入。详见 [CHANGELOG.md](stockai-project-docs/CHANGELOG.md) 2026-07-25 段。

---

## 🔬 因子体系(55 个 / 9 类)

<details>
<summary><b>展开 9 类因子清单</b></summary>

| 类别 | 数量 | 因子 |
|------|------|------|
| 价格 | 9 | MA5/10/20/60, PRICE_POS, HIGH_LOW_RATIO, CLOSE_OPEN_RATIO, TYPICAL_PRICE, WEIGHTED_CLOSE |
| 成交量 | 6 | VOL_MA5/10/20, VOL_RATIO, VOL_STD, PRICE_VOLUME |
| 技术指标 | 5 | RSI, MACD, BOLL_UPPER, BOLL_LOWER, BOLL_POSITION |
| 动量 | 9 | RET_5D/20D/60D, MOMENTUM_5/10/20, ACCELERATION, TREND_STRENGTH, MOMENTUM_COMPOSITE |
| 波动率 | 8 | VOLATILITY_5/20, VOLATILITY_RATIO, RANGE_VOLATILITY, ATR, DOWNSIDE_VOL, BB_WIDTH, HV_20 |
| 量价 | 3 | TURNOVER_RATE, OBV_DIVERGENCE, AVG_AMOUNT |
| 基本面 | 11 | PE, PB, ROE, EPS_GROWTH, MARKET_CAP, DIVIDEND_YIELD, PS_TTM, DEBT_RATIO, GROSS_MARGIN, REVENUE_GROWTH, NET_PROFIT_GROWTH |
| 情绪 | 2 | STRENGTH_20D, MOMENTUM_COMPOSITE_2 |
| 资金 | 2 | NORTH_FLOW(北向), INST_CHANGE(机构持仓变动) |

</details>

---

## 📡 数据源

```
A 股:  Futu OpenD (实时) → 新浪 → AKShare → Baostock (fallback 链)
港股:  新浪 (行情) + AKShare (K 线/基本面)
美股:  AKShare
ETF:   东方财富/腾讯 (主) + 天天基金 (净值兜底)
指数:  东方财富 ulist 一次拉全 15 个全球指数
AI:    5 供应商独立路由(7 功能 × 5 模型)
图表:  TradingView lightweight-charts v5
```

---

## 🚀 快速启动

### Windows(推荐)

```bat
D:\stocks\start.bat
```

菜单 `[3]` 一键启动后端 (3000) + 前端 (3001)。后端 startup 自动接入:DCA 提醒 / 止损检查 / Futu intraday 同步 / Futu nightly 同步 / 交易记忆解析。

### 手动

```bash
# 后端 (端口 3000)
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload --env-file .env

# 前端 (端口 3001)
cd frontend
npm install
npm run dev

# 浏览器打开 http://localhost:3001
```

### 后端监视器

```bat
cd D:\stocks\monitor-desktop
run.bat
```

独立 Electron 桌面 app,只读观察后端进程 + 访问日志 + 数据库结构。

---

## 🛣️ 页面路由

| 路由 | 说明 |
|------|------|
| `/` | 持仓概览 — KPI 卡片 + 走势图 + 行业饼图 |
| `/browse` | 全市场浏览 — 5530 只股票按板块分组 + 完整性标签 + Sparkline |
| `/quant` | 量化分析 — 个股透视 + 55 因子雷达 + 策略回测 + 蒙特卡洛 + F10 买卖点 |
| `/screener` | AI 选股 — 多因子扫描 + AI 精选 + 5 Agent 验证 + 候选警告 |
| `/screener/condition` | 条件选股 — 四层过滤 + 13 YAML 策略 |
| `/factor-lab` | 因子实验室 — IC/相关性/散点/GP/ML + 衰减评分 |
| **`/pipeline`** | **v3.11 收件箱** — 待审批/已通过/已拒绝/已过期 + lease 倒计时 |
| `/watchlist` | 自选股 — 实时行情 + 批量报价 |
| `/market` | 大盘指数 — 全球 15 指数 |
| `/transactions` | 交易记录 CRUD |
| `/ai-assistant` | AI 对话 — SSE 流式 |
| `/settings` | AI Key + 通知配置 |

---

## ⚙️ 环境变量(无真实密钥,仅占位符)

```bash
ADMIN_EMAIL=admin@stockai.com
ADMIN_PASSWORD=<你的密码>

JWT_SECRET=<64 位 hex>          # 必填
ENCRYPTION_KEY=<64 位 hex>      # 必填
CORS_ORIGINS=http://localhost:3001  # 必填

DEEPSEEK_API_KEY=sk-xxx         # 至少配一个
CLAUDE_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
MINIMAX_API_KEY=xxx
XIAOMI_API_KEY=xxx

WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

> ⚠️ `.env` 已在 `.gitignore` 内,**永不提交**。占位符必须替换为真实值。

---

## 🏗️ 项目结构

```
stocks/
├── frontend/                  # Next.js 16 + React 19 + Tailwind 4 + shadcn/ui
├── backend/                   # FastAPI + 12 路由 + 40 服务
│   ├── routers/               # API endpoints
│   ├── services/              # 业务服务 + 数据源 Provider 抽象
│   ├── strategies/            # 13 YAML 策略模板
│   └── sync_kline_*.py        # K 线同步入口
├── database/                  # SQLite (WAL 模式, 25+ 表)
├── tests/                     # pytest 回归
├── monitor-desktop/           # 🖥️ 后端监视器 (Electron + Vite + React)
├── stockai-project-docs/      # 📘 项目文档
├── monitor-desktop-docs/      # 📘 监视器文档
├── CLAUDE.md                  # Claude Code 入会文档
├── INDEX.md                   # 文档导航
└── start.bat                  # 一键启动 (Windows)
```

---

## 📝 版本历史

| 版本 | 日期 | 主题 |
|------|------|------|
| **v3.11** | 2026-07-25 | 研究→决策证据闭环(9 step 交付, 187 测试) |
| v3.10.4 | 2026-07-24 | /quotes 性能 50× + K 线测试 |
| v3.10 | 2026-07-23 | 🆕 自动量化 Pipeline(cron + 简报 + 推送) |
| v3.9 | 2026-07-20 | 🆕 /browse 全市场 + 因子实验室 5 Tab |
| v3.6 | 2026-07-01 | Futu + 工程 100% + TypeScript 零 any |
| v3.0 | 2026-06-04 | AI 选股 MVP |

> 📖 完整变更: [CHANGELOG.md](stockai-project-docs/CHANGELOG.md)

---

## 📂 文档导航

| 入口 | 说明 |
|------|------|
| 🧭 [INDEX.md](INDEX.md) | 文档总入口 |
| 📘 [stockai-project-docs/](stockai-project-docs/) | 项目文档(详细 README/CHANGELOG/DESIGN/...) |
| 🖥️ [monitor-desktop-docs/](monitor-desktop-docs/) | 监视器文档(PLAN/DAILY-LOG) |
| 🚀 [V4-PLAN.md](stockai-project-docs/V4-PLAN.md) | v4.0 大更新计划 |

---

## 🛡️ 安全与隐私

- `.env` / `*.db` / `*.db-wal` / `*.log` 全部 `.gitignore`,**仓库无密钥泄露**
- AI 失败抛 `AIServiceError` (provider_name + function_key),全局 handler 返 503
- JWT 通过 `ContextVar(_current_user_id)` 传递,**禁止硬编码 user_id**

---

<div align="center">

**[⭐ 给个 Star](https://github.com/L71615/stockai)** · **[📖 阅读文档](stockai-project-docs/)** · **[🐛 提 Issue](https://github.com/L71615/stockai/issues)**

</div>