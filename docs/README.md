# StockAI — 技术文档

## 项目结构

```
stocks/
├── frontend/                    # 前端 (HTML/CSS/JS)
│   ├── index.html              # 我的持仓
│   ├── watchlist.html          # 自选股
│   ├── market.html             # 大盘指数
│   ├── ai-assistant.html       # AI 助手
│   ├── skills.html             # Skills 商店
│   ├── transactions.html       # 交易记录
│   ├── settings.html           # 设置
│   ├── login.html              # 登录/注册
│   ├── css/common.css          # 公共样式
│   ├── js/common.js            # 公共脚本
│   └── components/             # 可复用组件
│
├── backend/                    # 后端 (Node.js/Express)
│   ├── server.js               # 主入口
│   ├── config/config.js        # 配置文件
│   ├── models/db.js            # 数据库连接
│   ├── routes/
│   │   ├── auth.js             # 认证 API
│   │   ├── stocks.js           # 股市数据 API
│   │   ├── ai.js               # AI 对话 API
│   │   └── skills.js           # Skills 管理 API
│   └── services/
│       ├── stockApi.js         # 股市数据服务
│       ├── aiService.js        # AI 模型服务
│       └── crawler.js          # 网页爬取服务
│
├── database/
│   └── schema.sql              # 数据库建表语句
│
├── skills/                     # Skills 插件目录
│   └── README.md               # Skills 开发规范
│
├── docs/README.md              # 本文档
└── PROJECT_PLAN.md             # 项目规划
```

## 技术栈

| 层面 | 方案 |
|------|------|
| 前端 | HTML5 + CSS3 + Vanilla JS (后续可迁移至 React) |
| 后端 | Node.js + Express.js |
| 数据库 | PostgreSQL |
| AI | Claude API / OpenClaw / OpenAI |
| 爬虫 | axios + jsdom |
| 股市数据 | 东方财富 API (免费) / Tushare Pro |

## 快速启动

```bash
# 1. 安装后端依赖
cd backend
npm init -y
npm install express cors pg axios jsdom

# 2. 创建数据库
psql -U postgres -c "CREATE DATABASE stockai;"
psql -U postgres -d stockai -f ../database/schema.sql

# 3. 启动后端
node server.js

# 4. 打开前端
# 浏览器打开 frontend/index.html
# 或通过 http://localhost:3000 访问
```

## 页面路由

| 页面 | 文件 |
|------|------|
| 我的持仓 (首页) | index.html |
| 自选股 | watchlist.html |
| 大盘指数 | market.html |
| AI 助手 | ai-assistant.html |
| Skills 商店 | skills.html |
| 交易记录 | transactions.html |
| 设置 | settings.html |
| 登录 | login.html |
