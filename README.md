# StockAI v3.10 — AI 量化选股 + 自动量化 Pipeline

> 55 因子多因子选股 · 13 策略模板 · 参数优化 · 策略对比 · AI 月报 · 因子实验室(IC/相关性/GP/ML 联合训练) · **全市场浏览 /browse** · **数据运维（一键补齐 K 线）** · **🆕 量化 Pipeline（5 步 cron 编排 + 简报 + 推送）**
>
> A 股投资者的量化工具箱。数据驱动，AI 增强。

> 🌐 中文 · [English](README.en.md)

---

## 📑 目录

- [🎯 核心能力](#core-capabilities)
- [🔬 因子体系（55 个）](#factor-system)
- [📡 数据源](#data-sources)
- [🏗 项目结构](#project-structure)
- [🚀 快速启动](#quick-start)
- [🛣 页面路由](#pages-and-routes)
- [⚙️ 环境变量](#️-environment-variables)
- [📝 版本历史](#version-history)

---

## <a id="core-capabilities"></a>🎯 核心能力

| 模块 | 功能 |
|------|------|
| 🔍 **AI 选股** | 全市场多因子扫描（55 因子）→ IC 加权打分 → AI 二次精选 → 板块过滤(默认沪深主板) → 策略回测 → 盯盘 |
| 🎯 **条件选股** | 四层过滤架构(L1-L4)，13 个策略模板，YAML 策略引擎，AND/OR 组合，每策略可调参数+来源说明 |
| 🎛️ **参数优化** | 网格搜索最优参数组合（上限300组），按最大回撤→夏普排序，一键应用到回测 |
| 🌐 **全市场浏览** | `/browse` 新增 — 5530 只股票按板块分组、Sparkline 走势、完整性标签、一键加自选 / 跑回测 |
| 🛠️ **数据运维** | K 线新鲜度仪表盘（akshare A 股交易日历）+ 一键补齐（scope=missing/stale/sector/all）+ 同步进度可查 |
| ⚖️ **策略对比** | 多策略独立回测并排排名（交易数/胜率/夏普/回撤/总收益） |
| 📊 **策略回测** | 18 个策略模板(13 YAML + 5 内置)，选股→模拟交易→绩效报告(夏普/最大回撤/胜率/卡玛)，手续费自动计入，买卖点K线标注，过拟合警告 |
| 🤖 **多 Agent 分析** | 5 角色多空辩论(技术面+基本面→多头+空头→裁判)，结构化决策输出(买入/持有/卖出+置信度)，自动注入交易记忆+策略历史 |
| 🧠 **交易记忆** | 决策→验证→反思→注入 自动闭环，策略维度追踪(每笔交易记录触发策略)，AI 分析时自动引用 |
| 📋 **AI 月报** | 当月交易聚合→AI 结构化报告(总成绩/赚最多/亏最多/策略PK/改进建议)，上月对比诊断(进步/退步) |
| 🛡 **交易纪律** | 买入前强制校验(止损检查+仓位限制+追涨停禁止)，连亏保护(3级警告+亏损明细+行动建议) |
| 🔌 **数据源抽象** | 配置驱动多源 fallback(Futu→新浪→AKShare→Baostock)，环境变量一键切换，新数据源插拔式接入 |
| 📊 **量化分析** | 个股 K 线(5 指标+讲解栏) + 55 因子全景透视(9 类+雷达图) + 组合风险指标(Sharpe/回撤/波动率/Beta) / 蒙特卡洛 |
| 🔬 **因子实验室** | IC 分析(因子预测能力) + 相关性矩阵(剔除冗余因子) + 散点图(因子vs收益) + GP 遗传编程挖掘新因子 + LightGBM ML 因子生成(测试集 IR=0.45) |
| 🧠 **AI 对话** | SSE 流式响应，DeepSeek/MiniMax/OpenAI/Claude 多供应商，功能独立配置 |
| 🔔 **通知推送** | 企业微信 / Telegram / 邮件，盯盘异动自动推送 |
| 💼 **持仓管理** | 实时盈亏 + 分散度饼图 + 行业自动分类（20+ 板块） |
| 📉 **K 线图表** | TradingView lightweight-charts 蜡烛图，MA/BOLL/MACD/RSI/KDJ 五指标 + 海龟通道线 + 指标讲解栏 |
| 📡 **Futu 行情接入** | A 股 `quote / minute / daily` 接入 Futu OpenD，日线同步 `historical_kline` |
| 🔄 **Futu 同步系统** | `watchlist + holdings` 批量目标，`intraday` / `nightly` 同步，落库并支持告警 |

## <a id="factor-system"></a>🔬 因子体系（55 个）

| 类别 | 数量 | 因子 |
|------|------|------|
| 价格 | 9 | MA5, MA10, MA20, MA60, PRICE_POS, HIGH_LOW_RATIO, CLOSE_OPEN_RATIO, TYPICAL_PRICE, WEIGHTED_CLOSE |
| 成交量 | 6 | VOL_MA5, VOL_MA10, VOL_MA20, VOL_RATIO, VOL_STD, PRICE_VOLUME |
| 技术指标 | 5 | RSI, MACD, BOLL_UPPER, BOLL_LOWER, BOLL_POSITION |
| 动量 | 9 | RET_5D, RET_20D, RET_60D, MOMENTUM_5/10/20, ACCELERATION, TREND_STRENGTH, MOMENTUM_COMPOSITE |
| 波动率 | 8 | VOLATILITY_5, VOLATILITY_20, VOLATILITY_RATIO, RANGE_VOLATILITY, ATR, DOWNSIDE_VOL, BB_WIDTH, HV_20 |
| 量价 | 3 | TURNOVER_RATE, OBV_DIVERGENCE, AVG_AMOUNT |
| 基本面 | 11 | PE, PB, ROE, EPS_GROWTH, MARKET_CAP, DIVIDEND_YIELD, PS_TTM, DEBT_RATIO, GROSS_MARGIN, REVENUE_GROWTH, NET_PROFIT_GROWTH |
| 情绪 | 2 | STRENGTH_20D, MOMENTUM_COMPOSITE_2 |
| 资金 | 2 | NORTH_FLOW(北向), INST_CHANGE(机构持仓变动) |

- 全部因子 done=55, pending=0（社交类 2 因子因雪球 API 不可用已移除）
- 每个因子基于 A 股合理阈值 0-100 打分，含正向/负向反转
- PE/PB 由 AKShare `eps`/`bvps` + 行情 `price` 现场计算
- PB 来源：Baostock 真实 pbMRQ（非 PE×ROE 反推）
- 季报自动年化：Q4→Q1 逐季回退
- 基本面：gpMargin(毛利率)、debt_ratio(资产负债率)、prev_revenue/net_profit(同比增速)

## <a id="data-sources"></a>📡 数据源

供应商优先级由 `backend/services/vendor_config.py` 集中管理，环境变量 `VENDOR_*` 可覆盖（详见源码注释）。

```text
A 股:
  实时行情:    Futu OpenD → AKShare fallback            (vendor_config: realtime_quote)
  批量报价:    AKShare (内部调腾讯/东财行情接口)            (vendor_config: batch_quotes)
  日 K 线:    Futu 日线优先 → 新浪 → AKShare → Baostock fallback
              (vendor_config: daily_kline; 旧链路 technical.py:_fetch_a_share_daily_legacy 已弃用)
  1m K 线:    仅 Futu (无 fallback)                      (vendor_config: minute_kline)
  基本面:      AKShare(同花顺 stock_financial_abstract_ths) → Baostock 兜底 (PE/PB/ROE/EPS/市值/行业/分红)

港股:
  实时行情:    新浪 (sina_adapter.get_hk_quote)
  K 线:       AKShare (ak.stock_hk_hist, 仅此一源)
  基本面:      AKShare (akshare_adapter.get_hk_factors)

美股:
  实时行情:    AKShare (akshare_adapter.get_us_quote)
  K 线:       AKShare (ak.stock_us_hist)

ETF / 基金:
  净值兜底:    天天基金 (fundgz.1234567, 用于检测 ETF 假数据)
  主行情:     东方财富 / 腾讯 (与 A 股共用, ETF 假数据回退到天天基金)

全球指数 (15 个主要指数):
  主源:       东方财富 ulist API 一次拉全 15 个 (routers/stocks.py:398)
  补充:       AKShare / 新浪

资金流向:
  北向资金:    AKShare (ak.stock_hsgt_individual_em)
  机构持仓:    AKShare (ak.stock_institute_hold_detail)

AI 供应商 (config.py, 7 功能 × 5 供应商独立路由):
  MiniMax / DeepSeek / Claude / OpenAI / Xiaomi

图表:        lightweight-charts v5.2 (TradingView 开源)

同步层:
  Futu:       futu_raw_quote(实时) + futu_raw_kline(分钟) → nightly sync historical_kline(日线)
  Tushare:    Tushare MCP nightly 全市场日线 + daily_basic + trade_cal + stock_basic 批量同步
```

## <a id="project-structure"></a>🏗 项目结构

```text
stocks/
├── frontend/                    # Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4
│   └── src/app/                 # 8 个页面
├── backend/                     # Python FastAPI
│   ├── routers/                 # API 路由 (11 个)
│   ├── services/                # 业务服务 (30+ 个，含 futu_client / futu_ingest_service / futu_sync_service)
│   │   └── providers/           # 数据源 Provider 抽象 (akshare / baostock / tushare + Chain fallback)
│   ├── strategies/              # 条件选股策略 YAML (13 个)
│   ├── sync_kline_full.py       # 全市场历史 K 线增量同步入口
│   └── sync_kline_priority.py   # 自选股+持仓优先同步入口
├── database/                    # SQLite (WAL 模式, 20+ 表，含 futu_raw_* 与 futu_sync_* 状态表)
├── tests/                       # pytest（Futu client / ingest / sync / quant 等回归）
└── scripts/                     # 工具脚本（导入、同步等）
```

## <a id="quick-start"></a>🚀 快速启动

### 推荐：控制面板启动

```bat
D:\stocks\start.bat
```

作用：
- 启动后端 API（3000）
- 启动前端 Next.js（3001）
- 后端 startup 会自动接入：
  - DCA 提醒线程
  - 止损检查线程
  - Futu `intraday` 同步线程
  - Futu `nightly` 同步线程

### 手动启动

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

### Futu 单股 / 批量同步脚本

```bash
# 单股
python backend/scripts/sync_futu_data.py --code 600519 --type quote
python backend/scripts/sync_futu_data.py --code 600519 --type minute --count 60
python backend/scripts/sync_futu_data.py --code 600519 --type daily --count 30

# 批量
python backend/scripts/sync_futu_data.py --mode intraday --scope watchlist+holdings
python backend/scripts/sync_futu_data.py --mode nightly --scope watchlist+holdings
```

## <a id="pages-and-routes"></a>🛣 页面路由

| 分组 | 页面 | 路由 | 说明 |
|------|------|------|------|
| 投资 | 持仓概览 | `/` | KPI 卡片 + 走势图 + 行业饼图 + 持仓表 |
| 投资 | 自选股 | `/watchlist` | 实时行情 + 批量报价 |
| 投资 | **股票浏览** | `/browse` | **🆕 v3.9** 全市场浏览 — 5530 只股票按板块分组 + 完整性标签 + Sparkline + 行业涨幅榜 + 一键补齐 |
| 投资 | 大盘指数 | `/market` | 全球 15 指数 |
| 分析 | 量化分析 | `/quant` | 个股透视 / 因子面板(9类55因子+雷达图) / 策略回测 / 蒙特卡洛 / **🆕 F10 K 线买卖点标注** |
| 分析 | 条件选股 | `/screener/condition` | 四层过滤(L1-L4) + 14 预设策略 + YAML 引擎 |
| 分析 | AI 选股 | `/screener` | 多因子扫描 + AI 精选 + 策略回测 + 盯盘 + **🆕 候选警告 (factor_warnings)** |
| 分析 | 因子实验室 | `/factor-lab` | 5 Tab: IC/相关性/散点/GP 挖掘/ML 挖掘 + **🆕 GP+ML 联合训练 (+13.69% IR lift)** + **🆕 衰减评分 (decay_score)** |
| 工具 | 交易记录 | `/transactions` | 交易 CRUD |
| 工具 | AI 对话 | `/ai-assistant` | 多模型 SSE 流式对话 |
| 工具 | 设置 | `/settings` | AI Key(功能→供应商映射表) + 通知配置 |

## <a id="environment-variables"></a>⚙️ 环境变量

```bash
# 管理员
ADMIN_EMAIL=admin@stockai.com
ADMIN_PASSWORD=your_password

# 安全 (必填)
JWT_SECRET=your_64_char_hex_secret
ENCRYPTION_KEY=your_64_char_hex_key

# AI (至少配一个)
DEEPSEEK_API_KEY=sk-xxx
MINIMAX_API_KEY=xxx
CLAUDE_API_KEY=sk-ant-xxx

# Futu (本地 OpenD)
# 先安装并启动 Futu OpenD，默认本机 127.0.0.1:11111
# Python 依赖已包含 futu-api==10.8.6808

# 通知 (可选)
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
NOTIFY_ENABLED=true
```

## <a id="version-history"></a>📝 版本历史

| 版本 | 日期 | 主题 | 亮点 |
|------|------|------|------|
| **v3.10.2** | 2026-07-23 | Pipeline hotfix + UI | GP 表达式修复 · 状态汇总 race condition · /browse 板块下拉补齐 · freshness 30s 自动刷新 |
| **v3.10.1** | 2026-07-23 | Pipeline 端到端 | 5 步 pipeline 5 项 bug 一次性修, 跑通简报推送 |
| **v3.10** | 2026-07-23 | 🆕 自动量化 Pipeline | cron 自动跑 GP→ML→过拟合→衰减→简报, 邮件/Telegram 推送 |
| **v3.9.1** | 2026-07-20 | /browse 6 项 hotfix | ⭐ A 股交易日历 (fresh 0%→94.1%) · 批量加自选 404→200 |
| **v3.9** | 2026-07-20 | 🆕 全市场浏览 + 量化突破 | /browse · 因子实验室 5 Tab · GP+ML 联合 +13.69% · 回测保护 · F10 买卖点 |
| **v3.9 后续** | 2026-07-16 | 性能 + 因子实验室 | Tushare 提速 4× · 三层缓存 · 因子 5 Tab (IC/相关性/散点/GP/LightGBM) |
| **v3.8** | 2026-07-09 | 策略系统升级 | 13 策略 · 参数优化器 · 月报 · 连亏保护 3 级 |
| **v3.7** | 2026-07-03 | 回测引擎 + 多 Agent | 策略回测 · 5 角色多空辩论 · 交易记忆 · 数据源抽象 |
| **v3.6** | 2026-07-01 | Futu + 工程 100% | A 股接 Futu · 认证解耦 · AI 异常 5 级 · TypeScript 零 any |
| **v3.5** | 2026-06-26 | 条件选股重构 | L1-L4 四层过滤 · 因子清理 57→55 · L3 两阶段 · K 线三合一 |
| **v3.4** | 2026-06-22 | 因子 29→57 | 7 类因子实装 · 量化页改版 · 海龟集成 |
| **v3.3** | 2026-06-13 | K 线升级 | lightweight-charts · 社交因子 · 大佬观点 |
| **v3.2** | 2026-06-06 | 多市场 + P0 安全 | 港美股 · 多 Agent · SWR · 7 项 P0 安全 |
| **v3.1** | 2026-06-05 | AI 对抗 + 全球指数 | AI 对抗 · 11/15 指数 · AI 供应商统一 |
| **v3.0** | 2026-06-04 | AI 选股 MVP | 多因子扫描 · 持仓 · Docker |

> 📖 **完整变更**: [CHANGELOG.md](CHANGELOG.md) 含每次更新的 bug 修复细节 + 文件统计
