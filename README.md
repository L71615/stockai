# StockAI — AI 投资教练 + 量化分析平台

> 多 AI 独立选股对抗 + 量化回测验证 + 组合风控看板。A 股投资者的决策工具箱。

## 项目结构

```
stocks/
├── frontend/                        # Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4
│   ├── src/
│   │   ├── app/                     # App Router 页面 (12 页)
│   │   │   ├── page.tsx             # 持仓概览 (KPI/图表/持仓表)
│   │   │   ├── market/              # 大盘指数
│   │   │   ├── global-news/         # 全球资讯 (SVG 地图)
│   │   │   ├── review/              # AI 复盘
│   │   │   ├── quant/               # 量化分析 (K线/因子/回测/蒙特卡洛)
│   │   │   ├── screener/            # AI 选股 (多因子扫描)
│   │   │   ├── kol/                 # 大佬观点 (X/Twitter 追踪)
│   │   │   ├── transactions/        # 交易记录
│   │   │   ├── ai-assistant/        # AI 对话
│   │   │   ├── skills/              # Agent 工坊
│   │   │   ├── settings/            # 设置 (AI/SMTP)
│   │   │   ├── watchlist/           # 自选股
│   │   │   └── login/               # 登录
│   │   ├── components/              # shadcn/ui 组件 + 业务组件
│   │   │   ├── ui/                  # shadcn 基础组件
│   │   │   ├── app-sidebar.tsx      # 三组折叠侧边栏
│   │   │   ├── app-layout.tsx       # 布局容器
│   │   │   ├── site-header.tsx      # 页面顶栏
│   │   │   ├── section-cards.tsx    # KPI 卡片行
│   │   │   ├── chart-area-interactive.tsx  # 资产走势图
│   │   │   └── data-table.tsx       # 持仓数据表格
│   │   ├── hooks/                   # 自定义 hooks
│   │   └── lib/                     # 工具函数 (auth/cn)
│   ├── public/                      # 静态资源
│   ├── package.json
│   └── next.config.ts               # API 代理配置
│
├── backend/                         # Python FastAPI 后端
│   ├── main.py                     # 主入口 (纯 API, 端口 3000)
│   ├── config.py                   # 配置 (环境变量)
│   ├── database.py                 # SQLite 连接 + 查询工具
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
│   │   ├── screener.py             # AI选股多因子扫描
│   │   ├── kol.py                  # 大佬观点追踪
│   │   └── skills.py               # Skills 管理
│   └── services/
│       ├── ai_service.py           # 多供应商AI调度
│       ├── quant_service.py        # 量化引擎
│       ├── review_service.py       # AI 复盘引擎
│       ├── technical.py            # 技术指标
│       ├── baostock_adapter.py     # Baostock (15年K线)
│       ├── akshare_adapter.py      # 腾讯财经 (实时行情)
│       ├── sina_adapter.py         # 新浪财经 (港股+指数)
│       ├── news_service.py         # 新闻爬取
│       ├── email_service.py        # SMTP 邮件
│       ├── scheduler.py            # 定时任务
│       └── utils.py                # 共享工具
│
├── database/                        # SQLite + schema
├── docker/                          # Docker 配置
├── docs/                            # 归档文档
├── scripts/                         # 工具脚本
├── tests/                           # pytest 测试
├── .claude/                         # Claude Code 配置
├── DESIGN.md                        # 设计系统
└── start.bat                        # 一键启动控制面板
```

## 技术栈

| 层面 | 方案 |
|------|------|
| 前端 | Next.js 16 App Router + React 19 + TypeScript |
| UI | shadcn/ui (Radix) + Tailwind CSS 4 |
| 图表 | recharts |
| 后端 | Python FastAPI + uvicorn |
| 数据库 | SQLite (WAL 模式) |
| AI | MiniMax / DeepSeek / Claude / OpenAI / 小米 (多供应商独立配置) |
| A股数据 | 腾讯财经 + Baostock (15年前复权) + 新浪财经 |
| 全球指数 | 东方财富 + AKShare + 新浪 (15个主要指数) |
| 基金净值 | 天天基金 |

## 快速启动

```bash
# 1. 安装后端依赖
cd backend
pip install -r requirements.txt

# 2. 安装前端依赖
cd ../frontend
npm install

# 3. 启动后端 (端口 3000)
cd ../backend
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload

# 4. 启动前端 (端口 3001)
cd ../frontend
npm run dev

# 5. 浏览器打开
# http://localhost:3001
```

或直接运行 `start.bat` → 选 `[3] Start Both` 一键启动。

## 页面路由

| 组 | 页面 | 路由 | 功能 |
|----|------|------|------|
| 投资 | 持仓概览 | `/` | KPI/资产走势/持仓表/AI洞察 |
| 投资 | 自选股 | `/watchlist` | 自选股实时行情+批量报价 |
| 投资 | 大盘指数 | `/market` | 全球15个主要指数 |
| 投资 | 全球资讯 | `/global-news` | SVG世界地图+城市财经新闻 |
| 分析 | AI 复盘 | `/review` | 结构化投资复盘报告 |
| 分析 | 量化分析 | `/quant` | K线/因子/回测/蒙特卡洛/AI对抗 |
| 分析 | AI 选股 | `/screener` | 多因子扫描+AI精选+盯盘 |
| 分析 | 大佬观点 | `/kol` | X/Twitter追踪+AI日报 |
| 工具 | 交易记录 | `/transactions` | 交易CRUD+成本重算 |
| 工具 | AI 对话 | `/ai-assistant` | 多模型对话+Agent记忆 |
| 工具 | Agent 工坊 | `/skills` | 自定义AI Agent |
| 工具 | 设置 | `/settings` | AI Key配置/SMTP |

## 环境变量

复制 `backend/.env.example` 为 `backend/.env`，按需填写：

```bash
cp backend/.env.example backend/.env
```

配置项：`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `JWT_SECRET`, AI Key 等。
