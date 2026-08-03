<div align="center">

# StockAI

> ✅ **Current version: v4.2.1** (2026-08-03 tag) — T+1 watcher N-state (M1) + minute-level 55 factors (M2)
> Plus **v5.0-alpha completed** (2026-08-01 tag, M1-M4 / 69 tests)
> Next phase: v5.0-beta (WebSocket push / minute K-line / multi-user / notification)
> See [`RELEASE-NOTES-v4.2.md`](RELEASE-NOTES-v4.2.md) + [`RELEASE-NOTES-v4.2-m2.md`](RELEASE-NOTES-v4.2-m2.md) + [`RELEASE-NOTES-v5.0.md`](RELEASE-NOTES-v5.0.md)

### A-Share AI Quant Screener · T+1 Short-term Forecast + Research → Decision Evidence Loop + Quasi-Live Quant

**55 factors · 13 strategies · 8-role multi-agent + agent tool calls · Auto Quant Pipeline · T+1 simulated fills · Counterfactual reports · Multi-strategy portfolio · Real-time intraday factors**

![Version](https://img.shields.io/badge/version-v4.2.1-success?style=flat-square)
![Python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?style=flat-square&logo=next.js&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?style=flat-square&logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

[中文](README.md) · [English](#) · [Docs](../INDEX.md) · [Roadmap](V4-PLAN.md)

</div>

---

## 🎯 TL;DR

StockAI is a **purely local** A-share quant toolbox with two main scenarios:

- **T+1/T+2 short-term forecast** (v4.x main line) — Run pipeline at 22:00 → simulate fill at next open → sell on day 3
- **Real-time intraday quant** (v5.0-alpha main line) — In-trading-hours real-time quote + real-time factors + auto signal scanning + manual confirm + simulated fill

**v4.2.1 release (M1 + M2):**
- **M1** — T+1 watcher 6-state machine (OSS-style `open / partial_filled / filled / closed / cancelled / rejected`) + `transition()` guard function + `t1_order_events` event sourcing table + `partial_filled` field
- **M2** — `factor_service.MINUTE_FACTOR_REGISTRY` 55 factors + `compute_minute_factors()` + `minute_factor_cache` 5m TTL + REST `/api/realtime/factor/{code}/minute` + frontend hook/component

**v5.0-alpha (4 milestones completed):**
- **M1** — Real-time quote ingest (unified Tencent free API, intraday + post-market)
- **M2** — Factor cache 5m TTL + REST + frontend card
- **M3** — Signal scanning 5s/round + manual confirm order (`realtime_signal_scanner` singleton daemon, 7 default strategies)
- **M4** — `/live` dashboard (5 sections: real-time quote / PnL / signals / factors / pending orders)

**v4.1.1 patch (stable, reused by v4.2/v5.0):**
- YAML strategy auto-registry + RSRS factor + 4 sizing algorithms + 4-rule risk guard + factor retirement notify + impact cost look-ahead fix

**Core capabilities**:
- **8-role multi-agent + CoT reasoning** + agent tool calls (Claude tool_use / OpenAI function_calling)
- **55 factors** (29 classic + 35 Alpha158 + 1 RSRS resistance/support) — daily + minute dual-band
- **T+1 simulated fill watcher** 6-state machine + **single-position > 30% risk gate**
- **Slippage + market impact** models (B4 10bps + B5 ADV square-root, with `as_of_date` to prevent look-ahead)
- **Intraday signal scanning** 7 default strategies + manual confirm + `t1_watcher` linkage
- **Evidence loop**: tri-axis state machine + OOS snapshots + T+1 watcher + approval inbox + counterfactual + feature flags + Drift PSI/KL
- **Backend monitor**: Electron desktop app

> 📖 Full docs: [stockai-project-docs/](../) · 📋 Monitor: [monitor-desktop/](../monitor-desktop/)
- **Strategy backtest**: 13 YAML strategy templates + parameter optimization + slippage/cost model + overfit warnings
- **Evidence loop** (v3.11 + v4.0 enhanced): Three-axis state machine + OOS snapshot + shadow portfolio → T+1 simulated fill watcher + approval inbox + feature flags + counterfactual visualization — **every decision is traceable end-to-end**
- **Auto Pipeline**: Post-close cron runs GP→ML→decay→data-health→brief push
- **Backend monitor**: Electron desktop app, real-time view of processes / logs / database

> 📖 Full docs: [stockai-project-docs/](.) · 📋 Monitor: [monitor-desktop/](../monitor-desktop/)

---

## ✨ Core Capabilities

| Module | Description |
|--------|-------------|
| 🔍 **AI Screening** | Market-wide multi-factor scan → IC-weighted → AI selection → board filter → backtest → watchlist |
| 🎯 **Conditional Screener** | L1-L4 four-layer filter + 13 YAML strategies + tunable parameters + source notes |
| 🎛️ **Parameter Optimization** | Grid search (max 300 combos), sort by drawdown→Sharpe |
| 📊 **Strategy Backtest** | 18 templates + fee model + buy/sell K-line markers + overfit warnings |
| 🤖 **Multi-Agent Analysis** | 5-role bull/bear debate → structured decisions (buy/hold/sell + confidence) |
| 🧠 **Trading Memory** | Decision→validate→reflect→inject, strategy dimension tracking |
| 📋 **AI Monthly Report** | Monthly aggregation → AI structured report + prior month comparison |
| 🛡️ **Trading Discipline** | Pre-buy validation + 3-tier loss protection + action suggestions |
| 🔬 **Factor Lab** | IC/correlation/scatter + GP genetic programming + LightGBM ML factors |
| 🧠 **AI Chat** | SSE streaming, 5 vendors (Claude/DeepSeek/OpenAI/MiniMax/Xiaomi) |
| 📡 **Data Sources** | Futu→Sina→AKShare→Baostock fallback, env var switching |
| 🖥️ **Backend Monitor** | Electron desktop · 5 modules · read-only · see [monitor-desktop/](../monitor-desktop/) |

---

## 🔁 Research → Decision Evidence Loop (v3.11 Foundation + v4.0 Enhancements)

**v3.11 laid the 5-module foundation; v4.0 fully refactored and extended it** to deliver **traceable decisions + counterfactual comparison + T+1 simulated fills**:

| Module | v3.11 Foundation | v4.0 Enhancements |
|--------|-------------------|---------------------|
| **T1 Experiment Ledger** | Three-axis state machine + version CAS + append-only audit | Maintained; backbone for factor/strategy experiments |
| **T2 OOS Snapshot** | snapshot_hash + point-in-time replay + leakage detection | IC recalibration API (one-call factor ranking) |
| **T3 Shadow Portfolio** | T+1 execution + 100-lot round + blocked-on-missing-price + UNIQUE dedup | **Fully refactored into T+1 Simulated Fill Watcher** (`t1_pending_orders` state machine pending_buy→bought→sold, with slippage + market impact + T+1 cost) |
| **T4 Approval Inbox** | TTL lease + three-layer CAS + counterfactual review | **C1 Counterfactual Report Visualization** (new Tab in `/pipeline`, approved vs rejected actual performance comparison) |
| **T5 Feature Flags** | 5 feature flags (default OFF) + one-click revert + notification_log audit | Maintained; v4.0 new capabilities follow the same OFF-by-default policy |

> Once run, every T+1 simulated fill decision can be traced: **factor expression → IC recalibration → multi-agent vote (8 roles + CoT + tool calls + personalization) → counterfactual report (approved vs rejected actual performance) → T+1 slippage + market impact + holding cost → position → sell → PnL**. See [CHANGELOG.md](CHANGELOG.md) v4.0 series + [RELEASE-NOTES-v4.0.md](RELEASE-NOTES-v4.0.md).

---

## 🔬 Factor System (55 factors / 9 categories)

<details>
<summary><b>Expand 9 categories</b></summary>

| Category | Count | Factors |
|----------|------|---------|
| Price | 9 | MA5/10/20/60, PRICE_POS, HIGH_LOW_RATIO, CLOSE_OPEN_RATIO, TYPICAL_PRICE, WEIGHTED_CLOSE |
| Volume | 6 | VOL_MA5/10/20, VOL_RATIO, VOL_STD, PRICE_VOLUME |
| Technical | 5 | RSI, MACD, BOLL_UPPER, BOLL_LOWER, BOLL_POSITION |
| Momentum | 9 | RET_5D/20D/60D, MOMENTUM_5/10/20, ACCELERATION, TREND_STRENGTH, MOMENTUM_COMPOSITE |
| Volatility | 8 | VOLATILITY_5/20, VOLATILITY_RATIO, RANGE_VOLATILITY, ATR, DOWNSIDE_VOL, BB_WIDTH, HV_20 |
| Volume-Price | 3 | TURNOVER_RATE, OBV_DIVERGENCE, AVG_AMOUNT |
| Fundamentals | 11 | PE, PB, ROE, EPS_GROWTH, MARKET_CAP, DIVIDEND_YIELD, PS_TTM, DEBT_RATIO, GROSS_MARGIN, REVENUE_GROWTH, NET_PROFIT_GROWTH |
| Sentiment | 2 | STRENGTH_20D, MOMENTUM_COMPOSITE_2 |
| Capital Flow | 2 | NORTH_FLOW, INST_CHANGE |

</details>

---

## 📡 Data Sources

```
A-Share: Futu OpenD (realtime) → Sina → AKShare → Baostock (fallback chain)
HK:      Sina (quote) + AKShare (K-line / fundamentals)
US:      AKShare
ETF:     Eastmoney/Tencent (primary) + TtjjFund (NAV fallback)
Index:   Eastmoney ulist pulls 15 global indices at once
AI:      5 vendors, independent routing (7 functions × 5 models)
Charts:  TradingView lightweight-charts v5
```

---

## 🚀 Quick Start

### Windows (recommended)

```bat
D:\stocks\start.bat
```

Menu `[3]` starts backend (3000) + frontend (3001). Backend startup auto-spawns: DCA reminder / stop-loss check / Futu intraday sync / Futu nightly sync / trading memory parser.

### Manual

```bash
# Backend (port 3000)
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload --env-file .env

# Frontend (port 3001)
cd frontend
npm install
npm run dev

# Open http://localhost:3001
```

### Backend Monitor

```bat
cd D:\stocks\monitor-desktop
run.bat
```

Independent Electron desktop app, read-only view of backend processes / access logs / database.

---

## 🛣️ Page Routes

| Route | Description |
|-------|-------------|
| `/` | Portfolio overview — KPI cards + trend chart + sector pie |
| `/browse` | Market browser — 5530 stocks grouped by board + completeness tags + sparkline |
| `/quant` | Quant analysis — stock deep-dive + 55-factor radar + backtest + Monte Carlo + F10 markers |
| `/screener` | AI screener — multi-factor scan + AI selection + 5-agent validation + warnings |
| `/screener/condition` | Conditional screener — four-layer filter + 13 YAML strategies |
| `/factor-lab` | Factor lab — IC/correlation/scatter/GP/ML + decay scoring |
| **`/pipeline`** | **v4.0 Inbox + Counterfactual** — pending/approved/rejected/expired + lease countdown + approved vs rejected actual performance comparison Tab |
| `/watchlist` | Watchlist — realtime quote + batch quotes |
| `/market` | Market indices — 15 global indices |
| `/transactions` | Transaction CRUD |
| `/ai-assistant` | AI chat — SSE streaming |
| `/settings` | AI keys + notification config |

---

## ⚙️ Environment Variables (placeholders only, no real keys)

```bash
ADMIN_EMAIL=admin@stockai.com
ADMIN_PASSWORD=<your_password>

JWT_SECRET=<64-char hex>       # required
ENCRYPTION_KEY=<64-char hex>   # required
CORS_ORIGINS=http://localhost:3001  # required

DEEPSEEK_API_KEY=sk-xxx        # at least one
CLAUDE_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
MINIMAX_API_KEY=xxx
XIAOMI_API_KEY=xxx

WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

> ⚠️ `.env` is `.gitignore`'d, **never commit**. Replace all placeholders with real values at deploy.

---

## 🏗️ Project Structure

```
stocks/
├── frontend/                  # Next.js 16 + React 19 + Tailwind 4 + shadcn/ui
├── backend/                   # FastAPI + 12 routers + 40 services
│   ├── routers/               # API endpoints
│   ├── services/              # Business services + data source Provider abstraction
│   ├── strategies/            # 13 YAML strategy templates
│   └── sync_kline_*.py        # K-line sync entry points
├── database/                  # SQLite (WAL mode, 25+ tables)
├── tests/                     # pytest regression
├── monitor-desktop/           # 🖥️ Backend monitor (Electron + Vite + React)
├── stockai-project-docs/      # 📘 Project docs
├── monitor-desktop-docs/      # 📘 Monitor docs
├── CLAUDE.md                  # Claude Code onboarding
├── INDEX.md                   # Doc navigation
└── start.bat                  # One-click launch (Windows)
```

---

## 📝 Version History

| Version | Date | Theme |
|---------|------|-------|
| **v4.1.1** | 2026-07-30 | patch: YAML strategy auto-registry + RSRS factor + 4 sizing algorithms + 4-rule risk guard + factor retirement notify + impact cost look-ahead fix (63 new tests) |
| **v4.1** | 2026-07-30 | Decision loop + real benchmarks (index_kline / etf_kline) + Drift PSI/KL monitoring (53 new tests) |
| **v4.0** | 2026-07-28 | T+1 short-term forecast mainline · 8-role multi-agent + CoT + tool calls + personalization · 64 factors · slippage + market impact · multi-strategy portfolio · counterfactual (193 new tests) |
| **v3.11** | 2026-07-25 | Research→Decision Evidence Loop (9 steps delivered, 187 tests) |
| v3.10.4 | 2026-07-24 | /quotes perf 50× + K-line tests |
| v3.10 | 2026-07-23 | 🆕 Auto Quant Pipeline (cron + brief + push) |
| v3.9 | 2026-07-20 | 🆕 /browse market + factor lab 5 tabs |
| v3.6 | 2026-07-01 | Futu + engineering 100% + TypeScript zero `any` |
| v3.0 | 2026-06-04 | AI screener MVP |

> 📖 Full changelog: [CHANGELOG.md](CHANGELOG.md)

---

## 📂 Documentation

| Entry | Description |
|-------|-------------|
| 🧭 [INDEX.md](../INDEX.md) | Doc root entry |
| 📘 [stockai-project-docs/](.) | Project docs (README/CHANGELOG/DESIGN/...) |
| 🖥️ [monitor-desktop-docs/](../monitor-desktop-docs/) | Monitor docs (PLAN/DAILY-LOG) |
| 🚀 [V4-PLAN.md](V4-PLAN.md) | v4.0 roadmap |

---

## 🛡️ Security & Privacy

- `.env` / `*.db` / `*.db-wal` / `*.log` all `.gitignore`'d, **zero key leakage**
- AI failures raise `AIServiceError` (provider_name + function_key), global handler returns 503
- JWT via `ContextVar(_current_user_id)` — **no hardcoded user_id**

---

<div align="center">

**[⭐ Star](https://github.com/L71615/stockai)** · **[📖 Read Docs](.)** · **[🐛 Report Issue](https://github.com/L71615/stockai/issues)**

</div>