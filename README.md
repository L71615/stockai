# StockAI v3.11 — A 股 AI 量化选股 · 研究→决策证据闭环

> 55 因子多因子选股 · 13 策略模板 · 参数优化 · 策略对比 · AI 月报 · 因子实验室(IC/相关性/GP/ML 联合训练) · **全市场浏览 /browse** · **数据运维（一键补齐 K 线）** · **量化 Pipeline（5 步 cron 编排 + 简报 + 推送）** · **🆕 v3.11 研究→决策证据闭环（三轴状态机 + OOS 快照 + 影子组合 + 审批收件箱 + 复盘）** · **🆕 后端监视器 (Electron 桌面 app)**
>
> A 股投资者的量化工具箱。数据驱动，AI 增强，反事实可追溯。

> 🌐 中文 · [English](stockai-project-docs/README.en.md)

> 📑 完整文档导航: [INDEX.md](INDEX.md) · 📚 项目文档: [stockai-project-docs/](stockai-project-docs/) · 🖥️ 监视器计划: [monitor-desktop-docs/](monitor-desktop-docs/)

---

## 🎯 核心能力

| 模块 | 功能 |
|------|------|
| 🔍 **AI 选股** | 全市场多因子扫描（55 因子）→ IC 加权打分 → AI 二次精选 → 板块过滤(默认沪深主板) → 策略回测 → 盯盘 |
| 🎯 **条件选股** | 四层过滤架构(L1-L4)，13 个策略模板，YAML 策略引擎，AND/OR 组合，每策略可调参数+来源说明 |
| 🎛️ **参数优化** | 网格搜索最优参数组合（上限300组），按最大回撤→夏普排序，一键应用到回测 |
| 🌐 **全市场浏览** | `/browse` — 5530 只股票按板块分组、Sparkline 走势、完整性标签、一键加自选 / 跑回测 |
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
| 🆕 **v3.11 实验账本** | 三轴状态机 (lifecycle/portfolio_role/proposal) + 版本 CAS + append-only 审计 + 单飞锁 |
| 🆕 **v3.11 OOS 快照** | 冻结假设 (snapshot_hash) + point-in-time replay (不复用 historical_kline) + leakage 检测 |
| 🆕 **v3.11 影子组合** | 收盘后信号 → T+1 执行 + 整手(100 股) + 缺价 blocked + UNIQUE 防重复 |
| 🆕 **v3.11 审批收件箱** | `/pipeline` 默认 Tab + TTL lease + 三层 CAS + counterfactual 复盘 |
| 🆕 **v3.11 灰度开关** | 5 个 feature flag (默认 OFF) + 一键回 OFF + notification_log 独立审计 |
| 🖥 **后端监视器** | Electron 桌面 app · 5 模块 · 0 改动主项目 · 详见 [monitor-desktop/](monitor-desktop/) |

## 🔬 因子体系（55 个）

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

## 📡 数据源

```text
A 股:
  实时行情:    Futu OpenD → AKShare fallback            (vendor_config: realtime_quote)
  批量报价:    AKShare (内部调腾讯/东财行情接口)            (vendor_config: batch_quotes)
  日 K 线:    Futu 日线优先 → 新浪 → AKShare → Baostock fallback
  1m K 线:    仅 Futu (无 fallback)                      (vendor_config: minute_kline)
  基本面:      AKShare(同花顺) → Baostock 兜底 (PE/PB/ROE/EPS/市值/行业/分红)

港股:        新浪 (行情) + AKShare (K线 + 基本面)
美股:        AKShare
ETF:         东方财富/腾讯(主) + 天天基金(净值兜底)
全球指数 (15 个): 东方财富 ulist API 一次拉全 15 个

AI 供应商 (config.py, 7 功能 × 5 供应商独立路由):
  MiniMax / DeepSeek / Claude / OpenAI / Xiaomi

图表:        lightweight-charts v5.2 (TradingView 开源)
```

## 🏗 项目结构

```text
stocks/
├── frontend/                    # Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4
├── backend/                     # Python FastAPI
│   ├── routers/                 # API 路由 (12 个)
│   ├── services/                # 业务服务 (40+ 个)
│   ├── strategies/              # 条件选股策略 YAML (13 个)
│   └── sync_kline_*.py          # 历史 K 线同步入口
├── database/                    # SQLite (WAL 模式)
├── tests/                       # pytest 回归测试
├── scripts/                     # 工具脚本
├── stockai-project-docs/        # 📘 项目文档 (README/CHANGELOG/DESIGN/...)
├── monitor-desktop/             # 🖥️ 后端监视器 (Electron + Vite + React)
├── monitor-desktop-docs/        # 📘 监视器文档 (PLAN/DAILY-LOG)
├── CLAUDE.md                    # Claude Code 入会文档
├── INDEX.md                     # 文档导航
└── start.bat                    # 一键启动 (Windows)
```

## 🚀 快速启动

### 推荐：Windows 控制面板

```bat
D:\stocks\start.bat
```

菜单选项 3 = 启动全部（后端 + 前端）。后端 startup 会自动接入：DCA 提醒、止损检查、Futu intraday 同步、Futu nightly 同步、交易记忆解析。

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

### 启动后端监视器

```bat
cd D:\stocks\monitor-desktop
run.bat
```

独立桌面 app,只读观察后端进程 + 访问日志 + 数据库结构,**Deep Freeze 操作**(不污染主项目)。

## 🛣 页面路由

| 分组 | 页面 | 路由 | 说明 |
|------|------|------|------|
| 投资 | 持仓概览 | `/` | KPI 卡片 + 走势图 + 行业饼图 + 持仓表 |
| 投资 | 自选股 | `/watchlist` | 实时行情 + 批量报价 |
| 投资 | **股票浏览** | `/browse` | **v3.9** 全市场浏览 — 5530 只股票按板块分组 |
| 投资 | 大盘指数 | `/market` | 全球 15 指数 |
| 分析 | 量化分析 | `/quant` | 个股透视 + 因子面板(9类55因子+雷达图) + 策略回测 + 蒙特卡洛 + F10 买卖点标注 |
| 分析 | 条件选股 | `/screener/condition` | 四层过滤(L1-L4) + 13 预设策略 + YAML 引擎 |
| 分析 | AI 选股 | `/screener` | 多因子扫描 + AI 精选 + 策略回测 + 盯盘 + 候选警告 |
| 分析 | 因子实验室 | `/factor-lab` | 5 Tab: IC/相关性/散点/GP 挖掘/ML 挖掘 + 衰减评分 |
| 🆕 v3.11 | **Pipeline 收件箱** | `/pipeline` | **默认 Tab**: 待审批/已通过/已拒绝/已过期 + lease 倒计时 + 三轴状态 CAS + 第 2 Tab: 运行 |
| 工具 | 交易记录 | `/transactions` | 交易 CRUD |
| 工具 | AI 对话 | `/ai-assistant` | 多模型 SSE 流式对话 |
| 工具 | 设置 | `/settings` | AI Key(功能→供应商映射表) + 通知配置 |

## ⚙️ 环境变量

```bash
# 管理员
ADMIN_EMAIL=admin@stockai.com
ADMIN_PASSWORD=<你的密码>

# 安全 (必填,缺失会启动失败)
JWT_SECRET=<64 位 hex>
ENCRYPTION_KEY=<64 位 hex>

# CORS 白名单 (必填)
CORS_ORIGINS=http://localhost:3001

# AI (至少配一个)
DEEPSEEK_API_KEY=sk-xxx
MINIMAX_API_KEY=xxx
CLAUDE_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
XIAOMI_API_KEY=xxx

# 通知 (可选)
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

> ⚠️ **敏感信息警示**: `.env` 已在 `.gitignore` 内,**永不提交**。本仓库所有密钥占位符(`xxx` / `your_password` 等)都是示例,部署时**必须替换为真实值**。

## 📝 版本历史

| 版本 | 日期 | 主题 | 亮点 |
|------|------|------|------|
| **v3.11** | 2026-07-25 | 研究→决策证据闭环 | 9 个 step 全部交付: T1三轴状态机+T2 OOS快照+T3策略层+T4影子组合+T5审批CAS+T6 /pipeline收件箱+T7故障注入+T8灰度flag+T9复盘counterfactual · 187 测试 + 1 编译 · Gate 1 路径走通 · append-only 证据链完整 · RUNBOOK 一键回滚 |
| **v3.10.4** | 2026-07-24 | /quotes 性能 + 测试 | N+1→单次IN查询 (50×加速) · codes 上限防DoS · 删70行死代码 · /pipeline warnings 折叠展开 · K线 fix 6 个单元测试 |
| **v3.10** | 2026-07-23 | 🆕 自动量化 Pipeline | cron 自动跑 GP→ML→过拟合→衰减→简报, 邮件/Telegram 推送 |
| **v3.9** | 2026-07-20 | 🆕 全市场浏览 + 量化突破 | /browse · 因子实验室 5 Tab · GP+ML 联合 +13.69% · 回测保护 · F10 买卖点 |
| **v3.6** | 2026-07-01 | Futu + 工程 100% | A 股接 Futu · 认证解耦 · AI 异常 5 级 · TypeScript 零 any |
| **v3.0** | 2026-06-04 | AI 选股 MVP | 多因子扫描 · 持仓 · Docker |

> 📖 **完整变更**: [CHANGELOG.md](stockai-project-docs/CHANGELOG.md) 含每次更新的 bug 修复细节 + 文件统计

---

## 📂 文档导航

- 📘 **项目文档**: [stockai-project-docs/](stockai-project-docs/)
  - 简介: [README.md](stockai-project-docs/README.md) · [README.en.md](stockai-project-docs/README.en.md)
  - 设计: [DESIGN.md](stockai-project-docs/DESIGN.md)
  - 历史: [CHANGELOG.md](stockai-project-docs/CHANGELOG.md)
  - 待办: [TODOS.md](stockai-project-docs/TODOS.md)
- 🖥️ **监视器文档**: [monitor-desktop-docs/](monitor-desktop-docs/)
  - 计划: [PLAN.md](monitor-desktop-docs/PLAN.md)
  - 日志: [DAILY-LOG.md](monitor-desktop-docs/DAILY-LOG.md)
- 🧭 **入口**: [INDEX.md](INDEX.md)

## 🛡️ 安全与隐私

- **敏感信息策略**: `.env` / `*.db` / `*.db-wal` / `*.log` 全部 `.gitignore`,仓库无密钥泄露风险
- **设计系统**: 暗色主题 (oklch) · `rounded-none` · Tabler Icons · 数字列 `tabular-nums`
- **AI 调用**: 失败必抛 `AIServiceError`(带 `provider_name` + `function_key`),全局 handler 返 503
- **认证解耦**: JWT 通过 `ContextVar(_current_user_id)` 传递,**禁止硬编码 user_id**

---

**当前版本: v3.11** · **下一大版本: v4.0** (规划中)