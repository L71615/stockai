# StockAI v3.6 — AI 量化选股 + 投资决策平台

> 55 因子多因子选股 · 海龟交易法 · 因子全景面板 · 条件选股四层过滤 · TradingView K 线 · P1 工程 100%
>
> A 股投资者的量化工具箱。数据驱动，AI 增强。

## 核心能力

| 模块 | 功能 |
|------|------|
| 🔍 **AI 选股** | 全市场多因子扫描（55 因子）→ IC 加权打分 → AI 二次精选 → 策略回测 → 盯盘 |
| 🎯 **条件选股** | 四层过滤架构(L1-L4)，14 个预设策略模板，YAML 策略引擎，支持 AND/OR 组合 |
| 🐢 **海龟选股** | 唐奇安通道突破选股，S1(20日)+S2(55日)双系统，ATR止损仓位计算，综合评分 0-100 |
| 📊 **量化分析** | 个股 K 线(5 指标+讲解栏) + 55 因子全景透视(9 类+雷达图) / 策略回测 / 蒙特卡洛 |
| 🧠 **AI 对话** | SSE 流式响应，7 功能 × 5 供应商独立配置映射表，因子 AI 解读 |
| 🔔 **通知推送** | 企业微信 / Telegram / 邮件，盯盘异动自动推送 |
| 💼 **持仓管理** | 实时盈亏 + 分散度饼图 + 行业自动分类（20+ 板块） |
| 📉 **K 线图表** | TradingView lightweight-charts 蜡烛图，MA/BOLL/MACD/RSI/KDJ 五指标 + 海龟通道线 + 指标讲解栏 |

## 因子体系（55 个）

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

## 数据源

```
实时行情:  A股(腾讯) + 港股(新浪) + 基金(天天基金)
历史K线:   Baostock(15年前复权) → 腾讯 → 东方财富
全球指数:  腾讯(7) + 新浪(4) = 11/15 覆盖
基本面:    AKShare(同花顺 stock_financial_abstract_ths) + Baostock 兜底(PE/PB/ROE/EPS/市值/行业/分红)
资金流向:  AKShare(北向资金 stock_hsgt_individual_em + 机构持仓 stock_institute_hold_detail)
AI:        MiniMax / DeepSeek / Claude / OpenAI / 小米(7功能×5供应商独立配置)
图表:      lightweight-charts v5.2 (TradingView 开源)
```

## 项目结构

```
stocks/
├── frontend/                    # Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4
│   └── src/app/                 # 8 个页面
├── backend/                     # Python FastAPI
│   ├── routers/                 # API 路由 (10 个)
│   ├── services/                # 业务服务 (20 个)
│   └── strategies/              # 条件选股策略 YAML (9 个)
├── database/                    # SQLite (WAL 模式, 20+ 表)
├── tests/                       # pytest (132 测试)
└── scripts/                     # 工具脚本
```

## 快速启动

```bash
# 后端 (端口 3000)
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 3000 --reload

# 前端 (端口 3001)
cd frontend
npm install
npm run dev

# 浏览器打开 http://localhost:3001
```

## 页面路由

| 分组 | 页面 | 路由 | 说明 |
|------|------|------|------|
| 投资 | 持仓概览 | `/` | KPI 卡片 + 走势图 + 行业饼图 + 持仓表 |
| 投资 | 自选股 | `/watchlist` | 实时行情 + 批量报价 |
| 投资 | 大盘指数 | `/market` | 全球 15 指数 |
| 分析 | 量化分析 | `/quant` | 个股透视 / 因子面板(9类55因子+雷达图) / 策略回测 / 蒙特卡洛 |
| 分析 | 条件选股 | `/screener/condition` | 四层过滤(L1-L4) + 14 预设策略 + YAML 引擎 |
| 分析 | AI 选股 | `/screener` | 多因子扫描 + AI 精选 + 策略回测 + 盯盘 |
| 工具 | 交易记录 | `/transactions` | 交易 CRUD |
| 工具 | AI 对话 | `/ai-assistant` | 多模型 SSE 流式对话 |
| 工具 | 设置 | `/settings` | AI Key(功能→供应商映射表) + 通知配置 |

## 环境变量

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

# 通知 (可选)
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
NOTIFY_ENABLED=true
```

## 版本历史

- **v3.6** (2026-07-01): P1 工程质量 100% — 认证解耦(ContextVar JWT, 24处硬编码清零) + AI 异常体系(5级层次) + K线 crosshair 标签 + 成交量格式化 + 连接池(busy_timeout) + data-table 拆分(730→4文件) + 全局异常处理 + TypeScript 零 :any
- **v3.5** (2026-06-26): 条件选股四层过滤(L1-L4) + 因子清理(57→55, 删社交死因子, 修5阈值) + K线三合一修复(对齐+讲解栏+默认精简) + L3两阶段重构(AKShare快筛→Baostock精筛) + Baostock超时保护 + 废弃页面清理(duel/kol/review/skills)
- **v3.5** (2026-06-23): AI 设置页重构(功能→供应商映射表+连通测试), Quant 页交互优化(统一查询按钮+因子AI解读), 根治 Turbopack disposed 错误(proxy→middleware+predev), 12 调用点按功能分发 AI 供应商
- **v3.4** (2026-06-22): 因子体系 29→57 全面实现, 价格/成交量/BOLL/ACCELERATION/波动率/基本面因子实装, 量化页改版(海龟集成+因子面板), AKShare 兼容性修复, ATR 归一化
- **v3.3** (2026-06-13): lightweight-charts K 线图表, 社交因子+通知推送+大佬观点页, 海龟交易法集成
- **v3.2** (2026-06-06): 29 因子, 港股+美股行情, 多 Agent 交叉验证选股, SWR 缓存层, P0 安全修复
- **v3.1** (2026-06-05): AI 对抗系统, 全球指数 11/15, 基本面因子, AI 供应商统一
- **v3.0** (2026-06-04): AI 选股多因子扫描, 持仓管理, 部署 Docker
