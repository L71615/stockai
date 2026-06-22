# StockAI v3.4 — AI 量化选股 + 投资决策平台

> 57 因子多因子选股 · 海龟交易法 · 因子全景面板 · 6 AI 人格对抗 · TradingView K 线
>
> A 股投资者的量化工具箱。数据驱动，AI 增强。

## 核心能力

| 模块 | 功能 |
|------|------|
| 🔍 **AI 选股** | 全市场多因子扫描（57 因子）→ IC 加权打分 → AI 二次精选 → 策略回测 → 盯盘 |
| 🐢 **海龟选股** | 唐奇安通道突破选股，S1(20日)+S2(55日)双系统，ATR止损仓位计算，综合评分 0-100 |
| ⚔️ **AI 对抗** | 6 个 AI 人格各拿 ¥10 万，独立选股对战，实时排名 |
| 📊 **量化分析** | 个股 K 线+技术指标+57 因子全景透视 / 因子分析面板(10类+雷达图) / 策略回测 / 蒙特卡洛 |
| 🧠 **AI 复盘** | 结构化投资复盘报告，多 AI 供应商可选 |
| 📈 **社交情绪** | 雪球关注数 + 财经 RSS，AI 生成每日观点日报 |
| 🔔 **通知推送** | 企业微信 / Telegram / 邮件，盯盘异动自动推送 |
| 💼 **持仓管理** | 实时盈亏 + 分散度饼图 + 行业自动分类（20+ 板块） |
| 📉 **K 线图表** | TradingView lightweight-charts 专业蜡烛图，海龟通道线叠加，支持日/周/月 K |

## 因子体系（57 个）

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
| 社交 | 2 | SOCIAL_RANK, SOCIAL_BUZZ(雪球关注) |

- 全部因子 done=57, pending=0
- 每个因子基于 A 股合理阈值 0-100 打分，含正向/负向反转
- PB 来源：Baostock 真实 pbMRQ（非 PE×ROE 反推）
- 季报自动年化：Q4→Q1 逐季回退
- 基本面：gpMargin(毛利率)、debt_ratio(资产负债率)、prev_revenue/net_profit(同比增速)

## 数据源

```
实时行情:  A股(腾讯) + 港股(新浪) + 基金(天天基金)
历史K线:   Baostock(15年前复权) → 腾讯 → 东方财富
全球指数:  腾讯(7) + 新浪(4) = 11/15 覆盖
基本面:    Baostock(PE/PB/ROE/EPS/市值/行业/毛利率/资产负债率/分红)
资金流向:  AKShare(北向资金 stock_hsgt_individual_em + 机构持仓 stock_institute_hold_detail)
社交情绪:  雪球关注数
AI:        MiniMax / DeepSeek / Claude / OpenAI / 小米(统一配置)
图表:      lightweight-charts (TradingView 开源)
```

## 项目结构

```
stocks/
├── frontend/                    # Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4
│   └── src/app/                 # 12 个页面
├── backend/                     # Python FastAPI
│   ├── routers/                 # API 路由 (14 个)
│   └── services/                # 业务服务 (24 个)
├── database/                    # SQLite (WAL 模式, 20+ 表)
├── docker/                      # Docker Compose 部署
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
| 分析 | AI 复盘 | `/review` | 结构化复盘报告 |
| 分析 | 量化分析 | `/quant` | 个股透视 / 因子面板(10类57因子) / 策略回测 / 蒙特卡洛 |
| 分析 | AI 选股 | `/screener` | 多因子扫描 + AI 精选 + 策略回测 + 盯盘 |
| 分析 | AI 对抗 | `/duel` | 6 AI 人格选股对战 |
| 分析 | 大佬观点 | `/kol` | 雪球热门 + RSS + AI 日报 |
| 工具 | 交易记录 | `/transactions` | 交易 CRUD |
| 工具 | AI 对话 | `/ai-assistant` | 多模型对话 |
| 工具 | 设置 | `/settings` | AI Key + 通知配置 |

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

- **v3.4** (2026-06-22): 因子体系 29→57 全面实现, 价格/成交量/BOLL/ACCELERATION/波动率/基本面因子实装, 量化页改版(海龟集成+因子面板), AKShare 兼容性修复, ATR 归一化
- **v3.3** (2026-06-13): lightweight-charts K 线图表, 社交因子+通知推送+大佬观点页, 海龟交易法集成
- **v3.2** (2026-06-06): 29 因子, 港股+美股行情, 多 Agent 交叉验证选股, SWR 缓存层, P0 安全修复
- **v3.1** (2026-06-05): AI 对抗系统, 全球指数 11/15, 基本面因子, AI 供应商统一
- **v3.0** (2026-06-04): AI 选股多因子扫描, 持仓管理, 部署 Docker
