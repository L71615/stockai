# StockAI v3.3 — AI 量化选股 + 投资决策平台

> 28 因子多因子选股 · 6 AI 人格对抗 · TradingView K 线 · 企业微信/Telegram 通知
>
> A 股投资者的量化工具箱。数据驱动，AI 增强。

## 核心能力

| 模块 | 功能 |
|------|------|
| 🔍 **AI 选股** | 全市场多因子扫描（28 因子）→ IC 加权打分 → AI 二次精选 → 策略回测 → 盯盘 |
| ⚔️ **AI 对抗** | 6 个 AI 人格各拿 ¥10 万，独立选股对战，实时排名 |
| 📊 **量化分析** | 个股 K 线+技术指标+28 因子透视 / 组合风险 / 策略回测 / 蒙特卡洛 |
| 🧠 **AI 复盘** | 结构化投资复盘报告，多 AI 供应商可选 |
| 📈 **社交情绪** | 雪球关注数 + 微博看多/看空情绪 + 财经 RSS，AI 生成每日观点日报 |
| 🔔 **通知推送** | 企业微信 / Telegram / 邮件，盯盘异动自动推送 |
| 💼 **持仓管理** | 实时盈亏 + 分散度饼图 + 行业自动分类（20+ 板块） |
| 📉 **K 线图表** | TradingView lightweight-charts 专业蜡烛图，MA5/10/20 均线叠加，支持日/周/月 K |

## 因子体系（29 个）

| 类别 | 数量 | 因子 |
|------|------|------|
| 动量 | 6 | ret_5d, ret_20d, ret_60d, rsi_14, macd_signal, ma_disposition |
| 波动 | 4 | hist_vol_20d, atr_14, amplitude_20d, downside_vol |
| 量价 | 5 | vol_ratio, turnover_rate, obv_divergence, price_volume_corr, avg_amount |
| 基本面 | 6 | pe_inverse, pb_inverse, roe, eps_growth, market_cap_ln, dividend_yield |
| 情绪 | 2 | strength_20d, momentum_composite |
| 资金 | 3 | north_flow, margin_change, inst_change |
| 社交 | 3 | social_rank, social_buzz, weibo_sentiment |

- IC 加权：截面 Spearman 秩相关，数据驱动
- PB 来源：Baostock 真实 pbMRQ（非 PE×ROE 反推）
- 季报自动年化：Q4→Q1 逐季回退

## 数据源

```
实时行情:  A股(腾讯) + 港股(新浪) + 基金(天天基金)
历史K线:   akshare → 东方财富 → Baostock(15年前复权)
全球指数:  腾讯(7) + 新浪(4) = 11/15 覆盖
基本面:    Baostock(PE/ROE/EPS) + akshare(季报)
社交情绪:  雪球关注数 + 微博情绪(akshare)
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
│   └── services/                # 业务服务 (15 个)
├── database/                    # SQLite (WAL 模式, 20+ 表)
├── docker/                      # Docker Compose 部署
├── tests/                       # pytest (44 测试)
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
| 分析 | 量化分析 | `/quant` | 个股透视 / 组合风险 / 回测 / 蒙特卡洛 |
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

## 版本规则

- 大版本 (X.0): 重大架构变更
- 功能版 (3.X): 新模块/新因子/新页面
- 修复版 (3.3.X): Bug 修复/性能优化

```
v3.0 → v3.1 → v3.2 → v3.3 → ...
  ↑       ↑       ↑       ↑
 AI选股  社交因子  大佬观点  K线图表
 对抗    通知推送  ETF分类  lightweight-charts
```
