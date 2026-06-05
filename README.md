# StockAI — AI 投资教练 + 量化分析平台

> 多 AI 独立选股对抗 + 量化回测验证 + 组合风控看板。A 股投资者的决策工具箱。

## 项目结构

```
stocks/
├── frontend/                        # 前端 (Vanilla JS SPA + Canvas 图表)
│   ├── index.html                  # 持仓仪表盘 (KPI/分散度/定投/新闻)
│   ├── quant.html                  # 量化分析 (K线图/成交量/因子/AI对抗/蒙特卡洛)
│   ├── review.html                 # AI 复盘报告
│   ├── watchlist.html              # 自选股
│   ├── market.html                 # 全球指数 (11/15 覆盖)
│   ├── ai-assistant.html           # AI 对话助手
│   ├── skills.html                 # Agent 工坊
│   ├── transactions.html           # 交易记录
│   ├── settings.html               # 多供应商 AI 配置
│   ├── login.html                  # 登录
│   ├── css/common.css              # 设计系统
│   └── js/common.js                # 共享 JS (API/Toast/快捷键/SVG图标)
│
├── backend/                         # Python FastAPI 后端
│   ├── main.py                     # 主入口 (uvicorn)
│   ├── config.py                   # 配置 (环境变量)
│   ├── database.py                 # SQLite 连接 + 查询工具
│   ├── dependencies.py             # FastAPI 依赖注入
│   ├── requirements.txt            # Python 依赖
│   ├── routers/
│   │   ├── stocks.py               # 行情/指数/新闻/AI复盘/预警
│   │   ├── holdings.py             # 持仓CRUD/批次/导入/XIRR/组合
│   │   ├── transactions.py         # 交易记录CRUD (含成本重算)
│   │   ├── quant.py                # 量化分析 (个股透视/因子/AI对抗/回测)
│   │   ├── ai.py                   # AI 对话
│   │   ├── auth.py                 # 认证
│   │   ├── settings.py             # AI/SMTP 配置
│   │   ├── dca.py                  # 定投计划
│   │   ├── agents.py               # Agent 管理
│   │   ├── memory.py               # Agent 记忆 (.md 文件)
│   │   └── skills.py               # Skills 管理
│   └── services/
│       ├── ai_service.py           # 多供应商AI调度 (5个供应商)
│       ├── quant_service.py        # 量化引擎 (Sharpe/MaxDD/Beta/DCA/蒙特卡洛)
│       ├── review_service.py       # AI 复盘引擎 (5层降级解析)
│       ├── technical.py            # 技术指标 (MA/MACD/KDJ/RSI)
│       ├── baostock_adapter.py     # Baostock (15年K线 + 基本面因子)
│       ├── akshare_adapter.py      # 腾讯财经 (A股实时行情/K线/搜索)
│       ├── sina_adapter.py         # 新浪财经 (港股行情 + 全球指数补充)
│       ├── news_service.py         # 新闻爬取+匹配
│       ├── email_service.py        # SMTP 邮件
│       ├── scheduler.py            # DCA 提醒后台线程
│       └── utils.py                # 共享工具 (行情缓存/XIRR/基金净值)
│
├── database/                        # SQL 表结构 (SQLite WAL模式)
└── README.md                        # 本文档
```

## 技术栈

| 层面 | 方案 |
|------|------|
| 前端 | HTML5 + CSS3 + Vanilla JS + Canvas |
| 后端 | Python FastAPI + uvicorn |
| 数据库 | SQLite (WAL 模式) |
| AI | MiniMax / DeepSeek / Claude / OpenAI / 小米 (多供应商独立配置) |
| A股数据 | 腾讯财经 + Baostock (15年前复权) + 新浪财经 |
| 港股数据 | 新浪财经 rt_hk 接口 |
| 全球指数 | 腾讯(7) + 新浪(4) = 11/15 覆盖 |
| 基金净值 | 天天基金 |
| 测试 | pytest + pytest-asyncio |

## 快速启动

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt

# 2. 启动后端 (自动创建 SQLite 数据库)
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload

# 3. 浏览器打开
# http://localhost:3000
```

## 页面路由

| 页面 | 文件 | 功能 |
|------|------|------|
| 持仓仪表盘 | index.html | 实时盈亏/分散度/定投/股息/新闻 |
| **量化分析** | quant.html | K线图+成交量/因子数据/AI策略对抗/蒙特卡洛 |
| AI 复盘 | review.html | 结构化投资复盘报告 |
| 自选股 | watchlist.html | 自选股实时行情 |
| 大盘指数 | market.html | 全球15个主要指数 (11个实时) |
| AI 助手 | ai-assistant.html | 多模型对话 + Agent 记忆 |
| Agent 工坊 | skills.html | 自定义 AI Agent |
| 交易记录 | transactions.html | 交易 CRUD + 成本自动重算 |
| 设置 | settings.html | 多供应商 AI Key 配置 / SMTP |

## 核心功能

### AI 策略对抗
- 6 种随机人设：价值猎手/成长捕手/逆向抄底/动量追涨/质量精选/红利低波
- 每人选 6 只 A 股，10 万虚拟资金，按实时行情成交
- 调仓窗口：交易日 11:00-11:30 / 14:30-15:00
- 规则兜底：止盈 +30%、止损 -15%
- 量化回测验证排名

### 量化分析引擎
- 风控指标：Sharpe / Max Drawdown / Volatility / Beta
- 持仓相关性热力图
- DCA 回测 + 4 策略对比
- 蒙特卡洛价格模拟
- 基本面因子：PE / ROE / EPS / 市值 / 行业

### 数据透视
- Canvas K 线图 (蜡烛 + MA5/MA10/MA20/MA60 四均线)
- 成交量柱状图 (红涨绿跌，悬浮精确数字)
- 技术指标：MA / MACD / KDJ / RSI + AI 信号解读

### AI 复盘
- 5 步 pipeline：aggregate → prompt → AI call → parse (5层降级) → store
- 盈亏归因 / 行为模式 / 风险提示 三维度评分

## 环境变量

复制 `.env.example` 为 `.env`，按需填写 AI Key（也可在网页"设置"页配置）：

```bash
cp .env.example .env
```
