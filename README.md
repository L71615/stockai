<div align="center">

# StockAI

### A 股 AI 量化选股 · T+1 短线预测 + 研究→决策证据闭环

**64 因子 · 13 策略 · 8 角色多 Agent + Agent 工具调用 · 自动量化 Pipeline · T+1 模拟成交 · 反事实报告 · 多策略组合**

![Version](https://img.shields.io/badge/version-v4.1.1--patch3-success?style=flat-square)
![Python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?style=flat-square&logo=next.js&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?style=flat-square&logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

[English](stockai-project-docs/README.en.md) · [中文](#) · [文档导航](INDEX.md) · [v4.x 计划](stockai-project-docs/V4-PLAN.md)

</div>

---

## 🎯 TL;DR

StockAI v4.1 是一个**纯本地化**的 A 股量化工具箱,主线场景为 **T+1/T+2 短线预测**(前晚 22:00 跑 Pipeline → 次日开盘模拟成交 → 第三日卖出),辅以完整的因子回测 / 决策闭环 / 证据可视化。

**v4.1 三大主线 + v4.1.1 patch:**
- **决策闭环** — scheduler 22:00 守护 pipeline + 09:35 T+1 watcher + bulk-approve 单事务 + 反事实自动跟跑
- **真实基准** — index_kline (6 指数) + etf_kline (11 ETF) + 4 段 fallback (真实指数 → ETF → 历史代理 → 全市场等权)
- **漂移监控** — PSI/KL 阈值版本化 + experiment_runs gate + baseline_value 真实填值 + 严重通知
- **v4.1.1 patch** — YAML 策略自动注册 + RSRS 因子 + 4 种仓位算法 + 4 规则风控拦截 + 因子退役通知 + impact cost look-ahead 修复
- **v4.1.1 patch2** — 策略加载路径与 registry 一致 + dev DB 5 年一次性 seed (沪深300 等 6 指数 1250 行/指数)
- **v4.1.1 patch3** — 5 项 bug 修复: 量化页 input 同步方向 + shadow 净值曲线 cutoff off-by-one + drift_policy Phase 2A/2B fixture 隔离 + risk_guard 集成 test 回归 + v4.1 测试套件 168/168 全过

**核心能力**:
- **8 角色多 Agent + CoT 推理** + Agent 工具调用(Claude tool_use / OpenAI function_calling)
- **65 因子**(29 经典 + 35 Alpha158 + 1 RSRS 阻力支撑)
- **T+1 模拟成交 watcher**(状态机 pending_buy → bought → sold,写 holdings + transactions + **单仓位 > 30% 风控拦截**)
- **滑点 + 冲击成本**模型(B4 默认 10bps + B5 基于 ADV 平方根,截面日期 as_of_date 防 look-ahead)
- **反事实报告** (基于 `proposal_retrospectives`,无新表) + 个性化 prompt(A4)
- **证据闭环**(v3.11 + v4.0 + v4.1 增强): 三轴状态机 + OOS 快照 + **T+1 模拟成交 watcher** + 审批收件箱 + **反事实报告可视化** + 灰度 flag + **Drift PSI/KL**
- **后端监视器**: Electron 桌面 app,实时观察 stockai 后端进程 / 日志 / 数据库

> 📖 完整文档: [stockai-project-docs/](stockai-project-docs/) · 📋 监视器: [monitor-desktop/](monitor-desktop/)

---

## ✨ 核心能力

| 模块 | 描述 |
|------|------|
| 🧠 **8 角色多 Agent** | v4.0 A1 — 资金面/政策/做空 3 角色新增,3 轮编排(round1×4 + round2×3 + judge) |
| 🤖 **Agent 工具调用** | v4.0 A2 — Claude tool_use + OpenAI function_calling 双协议,4 工具(quote/factor/backtest/t1_cost) |
| 🔗 **CoT 推理** | v4.0 A3 — 5 步显式推理(关键信号→多空→风险→决策→信心),前端可折叠展示 |
| 🎯 **个性化 prompt** | v4.0 A4 — 从交易历史推断胜率/持仓/风险偏好,自动注入 8 个 system prompt |
| 🛒 **T+1 模拟成交** | v4.0 — 22:00 Pipeline → 09:30 watcher 真实模拟成交 + 第三日卖出 + 收益统计 |
| 📊 **64 因子** | v4.0 B1-B3 — 29 经典 + 35 Alpha158(K线/变化率/偏离/波动/价量/资金流) |
| 💰 **滑点 + 冲击成本** | v4.0 B4-B5 — 10bps 固定滑点 + ADV 平方根冲击模型 |
| 🎛️ **多策略组合** | v4.0 B6 — union/intersect/majority 3 模式 + trade_attribution |
| 📈 **IC 重新校准** | v4.0 — recalibrate_all_factors_ic() 一键排名 |
| 🔍 **AI 选股** | 全市场多因子扫描 → IC 加权 → AI 精选 → 板块过滤 → 回测 → 盯盘 |
| 🎯 **条件选股** | L1-L4 四层过滤 + 13 YAML 策略 + 参数可调 + 来源说明 |
| 📊 **策略回测** | 18 模板 + 滑点/冲击/手续费 自动计入 + 买卖点 K 线标注 + 过拟合警告 |
| 📋 **反事实报告** | v4.0 C1 — approved vs rejected 实际表现对比 + 每条 lesson |
| 🧠 **交易记忆** | 决策→验证→反思→注入 自动闭环,策略维度追踪 |
| 📋 **AI 月报** | 月度聚合 → AI 结构化报告 + 上月对比诊断 |
| 🛡️ **交易纪律** | 买入前强制校验 + 连亏保护 3 级 + 行动建议 |
| 🔬 **因子实验室** | IC/相关性/散点 + GP 遗传编程 + LightGBM ML 因子 |
| 🧠 **AI 对话** | SSE 流式响应,5 供应商独立路由(Claude/DeepSeek/OpenAI/MiniMax/Xiaomi) |
| 📡 **数据源** | Futu→新浪→AKShare→Baostock fallback,环境变量切换 |
| 🖥️ **后端监视器** | Electron 桌面 app · 5 模块 · 只读 · **详见 [monitor-desktop/](monitor-desktop/)** |
| 📋 **YAML 策略自动注册** | v4.1.1 — `strategy_registry.py` 单例 + mtime 失效 + validate,丢 YAML 进 `backend/strategies/` 自动出现 |
| 🛡️ **风控拦截** | v4.1.1 — `risk_guard.py` 4 规则纯函数 + `t1_watcher._evaluate_buy_risk` 单仓位 > 30% 拒单 + 通知 |
| 📐 **仓位算法** | v4.1.1 — `risk_sizing.py` Kelly / RiskParity / VolTarget + calc_win_rate_and_profit_factor |

---

## 🔁 研究→决策证据闭环(v3.11 基础 + v4.0 增强)

**v3.11 奠定的 5 个核心模块**,v4.0 在其上完整重构 + 增强,实现**决策可追溯 + 反事实可对比 + T+1 真实模拟成交**:

| 模块 | v3.11 基础 | v4.0 增强 |
|------|------------|----------|
| **T1 实验账本** | 三轴状态机 (lifecycle/portfolio_role/proposal) + 版本 CAS + append-only 审计 | 持续维护,作为因子/策略实验的账本 |
| **T2 OOS 快照** | snapshot_hash + point-in-time replay + leakage 检测 | IC 重新校准接口(因子排名一键出) |
| **T3 影子组合** | T+1 执行 + 整手(100 股) + 缺价 blocked + UNIQUE 防重复 | **完整重构为 T+1 模拟成交 watcher**(`t1_pending_orders` 状态机 pending_buy→bought→sold,滑点+冲击+T+1 成本全计入) |
| **T4 审批收件箱** | TTL lease + 三层 CAS + counterfactual 复盘 | **加 C1 反事实报告可视化**(`/pipeline` 新 Tab,approved vs rejected 实际表现对比) |
| **T5 灰度开关** | 5 个 feature flag (默认 OFF) + 一键回 OFF + notification_log 独立审计 | 持续维护,v4.0 新能力默认 OFF 走此机制 |

> 跑通后,任何一笔 T+1 模拟成交决策都能追溯到:**因子表达式 → IC 校准 → 多 Agent 投票(8 角色 + CoT + 工具调用 + 个性化)→ 反事实报告(approved vs rejected 实际表现)→ T+1 滑点+冲击+T+1 成本全计入 → 持仓→卖出→收益统计**。详见 [CHANGELOG.md](stockai-project-docs/CHANGELOG.md) v4.0 系列 + [RELEASE-NOTES-v4.0.md](stockai-project-docs/RELEASE-NOTES-v4.0.md)。

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
| **`/pipeline`** | **v4.0 收件箱 + 反事实** — 待审批/已通过/已拒绝/已过期 + lease 倒计时 + approved vs rejected 实际表现对比 Tab |
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
| **v4.1.1** | 2026-07-30 | patch: YAML 策略自动注册 + RSRS 因子 + 4 仓位算法 + 4 规则风控 + 因子退役通知 + impact cost look-ahead 修复 (63 新测试) |
| **v4.1** | 2026-07-30 | 决策闭环 + 真实基准(index_kline / etf_kline) + Drift PSI/KL 监控 (53 新测试) |
| **v4.0** | 2026-07-28 | T+1 短线预测主线 · 8 角色多 Agent + CoT + 工具调用 + 个性化 · 64 因子 · 滑点+冲击 · 多策略组合 · 反事实(193 新测试) |
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