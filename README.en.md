# StockAI v3.9 — AI Quant Stock Screening & Investment Decision Platform

> 55-factor multi-factor screening · 13 strategy templates · parameter optimization · strategy comparison · AI monthly reports · trading memory loop · loss-streak protection · hot sector panel · sector filtering
>
> A quant toolbox for A-share investors. Data-driven, AI-enhanced.

> [中文](README.md) · English

---

## 📑 Table of Contents

- [🎯 Core Capabilities](#-core-capabilities)
- [🔬 Factor System (55)](#-factor-system-55)
- [📡 Data Sources](#-data-sources)
- [🏗 Project Structure](#-project-structure)
- [🚀 Quick Start](#-quick-start)
- [🛣 Pages & Routes](#-pages--routes)
- [⚙️ Environment Variables](#️-environment-variables)
- [📝 Version History](#-version-history)

---

## 🎯 Core Capabilities

| Module | Features |
|------|------|
| 🔍 **AI Stock Screening** | Full-market multi-factor scan (55 factors) → IC-weighted scoring → AI second-round pick → sector filter (default Shanghai/Shenzhen main boards) → strategy backtest → watchlist |
| 🎯 **Conditional Screening** | Four-layer filtering (L1–L4), 13 strategy templates, YAML strategy engine, AND/OR combinations, per-strategy tunable params + source attribution |
| 🎛️ **Parameter Optimization** | Grid search for optimal params (up to 300 combos), sorted by max drawdown → Sharpe, one-click apply to backtest |
| ⚖️ **Strategy Comparison** | Multi-strategy side-by-side backtest ranking (trade count / win rate / Sharpe / drawdown / total return) |
| 📊 **Strategy Backtest** | 18 strategy templates (13 YAML + 5 built-in), screen → simulated trading → performance report (Sharpe / max drawdown / win rate / Calmar), auto fees, buy/sell markers, overfit warnings |
| 🤖 **Multi-Agent Analysis** | 5-role bull/bear debate (technical + fundamental → bull + bear → judge), structured decisions (buy/hold/sell + confidence), auto-injected trading memory + strategy history |
| 🧠 **Trading Memory** | Decision → verify → reflect → inject automated loop, strategy-dimension tracking (each trade records trigger strategy), auto-cited in AI analysis |
| 📋 **AI Monthly Report** | Monthly trade aggregation → AI structured report (overall score / biggest win / biggest loss / strategy PK / improvement suggestions), month-over-month diagnosis (improving/regressing/flat) |
| 🛡️ **Trading Discipline** | Pre-trade enforcement (stop-loss check / position limit / no chasing limit-ups), loss-streak protection (3-level warning + loss breakdown + action recommendations) |
| 🔥 **Hot Sector Panel** | Homepage sector fund-flow TOP5 + northbound capital holdings TOP5, 5-minute auto refresh |
| 🔌 **Data Source Abstraction** | Config-driven multi-source fallback (Futu → Sina → AKShare → Baostock), env-var toggle, plug-and-play new providers |
| 📈 **Quant Analysis** | Per-stock K-line (5 indicators + explainer) + 55-factor panoramic view (9 categories + radar) + portfolio risk metrics (Sharpe/drawdown/volatility/Beta) / Monte Carlo |
| 💬 **AI Chat** | SSE streaming, DeepSeek / MiniMax / OpenAI / Claude multi-vendor, function-independent configuration |
| 🔔 **Notifications** | WeChat Work / Telegram / Email, watchlist anomaly auto-push |
| 💼 **Portfolio Management** | Real-time P&L + diversification pie + auto industry classification (20+ sectors) |
| 📉 **K-Line Chart** | TradingView lightweight-charts candlesticks, MA/BOLL/MACD/RSI/KDJ 5 indicators + Turtle channel + indicator explainer |
| 📡 **Futu Market Feed** | A-share `quote / minute / daily` via Futu OpenD, daily sync to `historical_kline` |
| 🔄 **Futu Sync System** | `watchlist + holdings` batch targets, `intraday` / `nightly` sync, persisted with alert support |

---

## 🔬 Factor System (55)

| Category | Count | Factors |
|------|------|------|
| Price | 9 | MA5, MA10, MA20, MA60, PRICE_POS, HIGH_LOW_RATIO, CLOSE_OPEN_RATIO, TYPICAL_PRICE, WEIGHTED_CLOSE |
| Volume | 6 | VOL_MA5, VOL_MA10, VOL_MA20, VOL_RATIO, VOL_STD, PRICE_VOLUME |
| Technical | 5 | RSI, MACD, BOLL_UPPER, BOLL_LOWER, BOLL_POSITION |
| Momentum | 9 | RET_5D, RET_20D, RET_60D, MOMENTUM_5/10/20, ACCELERATION, TREND_STRENGTH, MOMENTUM_COMPOSITE |
| Volatility | 8 | VOLATILITY_5, VOLATILITY_20, VOLATILITY_RATIO, RANGE_VOLATILITY, ATR, DOWNSIDE_VOL, BB_WIDTH, HV_20 |
| Volume-Price | 3 | TURNOVER_RATE, OBV_DIVERGENCE, AVG_AMOUNT |
| Fundamental | 11 | PE, PB, ROE, EPS_GROWTH, MARKET_CAP, DIVIDEND_YIELD, PS_TTM, DEBT_RATIO, GROSS_MARGIN, REVENUE_GROWTH, NET_PROFIT_GROWTH |
| Sentiment | 2 | STRENGTH_20D, MOMENTUM_COMPOSITE_2 |
| Capital Flow | 2 | NORTH_FLOW (northbound), INST_CHANGE (institutional holding change) |

- All factors done=55, pending=0 (2 sentiment factors removed due to Xueqiu API unavailability)
- Each factor scored 0–100 against A-share rational thresholds, with positive/negative reversal support
- PE/PB computed live from AKShare `eps`/`bvps` + live `price`
- PB sourced from Baostock's real `pbMRQ` (not back-calculated from PE × ROE)
- Quarterly reports auto-annualized: Q4 → Q1 with rolling fallback
- Fundamentals: `gpMargin` (gross margin), `debt_ratio`, `prev_revenue`/`net_profit` (YoY growth)

---

## 📡 Data Sources

```text
Real-time quotes:  A-share (Futu preferred → Tencent/Eastmoney fallback) + HK (Sina) + Funds (Eastmoney)
Historical K-line: A-share (Futu daily preferred → Sina/Tencent/Eastmoney/Baostock fallback)
1-min chart:        A-share 1m via Futu
Global indices:    Tencent (7) + Sina (4) = 11/15 coverage
Fundamentals:      AKShare (Tonghuashun stock_financial_abstract_ths) + Baostock fallback (PE/PB/ROE/EPS/market cap/industry/dividend)
Capital flow:      AKShare (northbound stock_hsgt_individual_em + institutional stock_institute_hold_detail)
AI:                MiniMax / DeepSeek / Claude / OpenAI / Xiaomi (7 functions × 5 vendors, independent config)
Charts:            lightweight-charts v5.2 (TradingView open-source)
Sync layer:        futu_raw_quote / futu_raw_kline + daily sync to historical_kline
```

---

## 🏗 Project Structure

```text
stocks/
├── frontend/                    # Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4
│   └── src/app/                 # 8 pages
├── backend/                     # Python FastAPI
│   ├── routers/                 # 11 API routers
│   ├── services/                # 30+ business services (futu_client / futu_ingest_service / futu_sync_service, etc.)
│   │   └── providers/           # Data-source Provider abstraction (akshare / baostock / tushare + Chain fallback)
│   ├── strategies/              # 13 conditional-screening strategy YAMLs
│   ├── sync_kline_full.py       # Full-market historical K-line incremental sync entry
│   └── sync_kline_priority.py   # Watchlist + holdings priority sync entry
├── database/                    # SQLite (WAL mode, 20+ tables, including futu_raw_* and futu_sync_* state tables)
├── tests/                       # pytest (Futu client / ingest / sync / quant regression suites)
└── scripts/                     # Utility scripts (import, sync, etc.)
```

---

## 🚀 Quick Start

### Recommended: Control Panel Launcher

```bat
D:\stocks\start.bat
```

What it does:
- Starts backend API on port 3000
- Starts frontend Next.js on port 3001
- Backend `startup` hook automatically spawns:
  - DCA reminder thread
  - Stop-loss check thread
  - Futu `intraday` sync thread
  - Futu `nightly` sync thread

### Manual Start

```bash
# Backend (port 3000)
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload --env-file .env

# Frontend (port 3001)
cd frontend
npm install
npm run dev

# Open http://localhost:3001 in browser
```

### Futu Single-Stock / Batch Sync Scripts

```bash
# Single stock
python backend/scripts/sync_futu_data.py --code 600519 --type quote
python backend/scripts/sync_futu_data.py --code 600519 --type minute --count 60
python backend/scripts/sync_futu_data.py --code 600519 --type daily --count 30

# Batch
python backend/scripts/sync_futu_data.py --mode intraday --scope watchlist+holdings
python backend/scripts/sync_futu_data.py --mode nightly --scope watchlist+holdings
```

---

## 🛣 Pages & Routes

| Group | Page | Route | Description |
|------|------|------|------|
| Investing | Portfolio Overview | `/` | KPI cards + trend chart + industry pie + holdings table |
| Investing | Watchlist | `/watchlist` | Real-time quotes + batch pricing |
| Investing | Market Indices | `/market` | 15 global indices |
| Analysis | Quant Analysis | `/quant` | Per-stock view / factor panel (9 categories, 55 factors + radar) / strategy backtest / Monte Carlo |
| Analysis | Conditional Screening | `/screener/condition` | Four-layer filter (L1–L4) + 14 preset strategies + YAML engine |
| Analysis | AI Stock Screening | `/screener` | Multi-factor scan + AI shortlist + strategy backtest + watchlist |
| Tools | Transactions | `/transactions` | Trade CRUD |
| Tools | AI Chat | `/ai-assistant` | Multi-model SSE streaming chat |
| Tools | Settings | `/settings` | AI keys (function → vendor map) + notification config |

---

## ⚙️ Environment Variables

```bash
# Admin
ADMIN_EMAIL=admin@stockai.com
ADMIN_PASSWORD=your_password

# Security (required)
JWT_SECRET=your_64_char_hex_secret
ENCRYPTION_KEY=your_64_char_hex_key

# AI (at least one required)
DEEPSEEK_API_KEY=sk-xxx
MINIMAX_API_KEY=xxx
CLAUDE_API_KEY=sk-ant-xxx

# Futu (local OpenD)
# Install and start Futu OpenD first; defaults to 127.0.0.1:11111
# Python dependency already includes futu-api==10.8.6808

# Notifications (optional)
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
NOTIFY_ENABLED=true
```

---

## 📝 Version History

- **v3.9** (2026-07-16): Login JSON-parse hardening (`res.text` + try/parse) + dual-header UI refactor (DESIGN.md §Navigation compliance) + Top header version display + `APP_VERSION` centralized in `frontend/src/lib/version.ts` + Tushare token hardcoded default removed (env required) + data-source Provider abstraction (`backend/services/providers/`: akshare/baostock/tushare + Chain fallback) + full / priority K-line sync scripts (`sync_kline_full.py` / `sync_kline_priority.py`)
- **v3.8** (2026-07-09): Strategy system upgrade (13 strategies, tunable params + source) + parameter optimizer (grid search) + strategy comparison (side-by-side) + backtest enhancements (fees / overfit warnings / buy-sell markers / signal reasons) + AI monthly reports + month-over-month diagnosis + trading-memory strategy dimension + loss-streak protection (3-level warning) + hot sector panel (sector flow + northbound) + sector filter (main board default) + bug fixes (`run_multi_agent_screen` etc.). 33 files, +2983/−115 lines
- **v3.7** (2026-07-03): Strategy backtest engine + multi-agent analysis + trading memory system + data-source abstraction + trading discipline enforcement + AI settings fix + performance optimizations (screener poll fix / DataTable 3→1× / batch quotes / SWR dedup / Futu skip). 23 files, +1970/−1639 lines
- **v3.6** (2026-07-01): Futu Phase A + P1 — A-share `quote / minute / daily` via Futu OpenD, added `futu_raw_quote` / `futu_raw_kline`, daily sync to `historical_kline`, existing quote / daily / 1m charts prefer Futu; added `futu_sync_service`, `futu_sync_runs` / `futu_sync_run_items`, `intraday` / `nightly` batch sync, alert logic and scheduler triggers
- **v3.6** (2026-07-01): P1 engineering quality 100% — auth decoupling (ContextVar JWT, 24 hardcoded IDs cleared) + AI exception system (5-tier hierarchy) + K-line crosshair label + volume formatting + connection pool (`busy_timeout`) + data-table split (730 → 4 files) + global exception handler + TypeScript zero `any`
- **v3.5** (2026-06-26): Conditional-screening four-layer filter (L1–L4) + factor cleanup (57 → 55, removed dead sentiment factors, fixed 5 thresholds) + K-line three-in-one fix (alignment + explainer + default simplified) + L3 two-stage refactor (AKShare fast-filter → Baostock precise-filter) + Baostock timeout protection + deprecated page cleanup (duel / kol / review / skills)
- **v3.5** (2026-06-23): AI settings page refactor (function → vendor mapping + connectivity test), Quant page interaction optimization (unified query button + factor AI explainer), root fix for Turbopack disposed error (proxy → middleware + predev), 12 call sites dispatch AI vendor by function
- **v3.4** (2026-06-22): Factor system 29 → 57 full implementation, price / volume / BOLL / ACCELERATION / volatility / fundamental factors live, Quant page redesign (Turtle integration + factor panel), AKShare compatibility fix, ATR normalization
- **v3.3** (2026-06-13): lightweight-charts K-line chart, sentiment factors + notifications + KOL page, Turtle trading rule integration
- **v3.2** (2026-06-06): 29 factors, HK + US stock quotes, multi-agent cross-validation screening, SWR cache layer, P0 security fixes
- **v3.1** (2026-06-05): AI adversarial system, global indices 11/15, fundamental factors, AI vendor unification
- **v3.0** (2026-06-04): AI stock screening multi-factor scan, portfolio management, Docker deployment