# StockAI 后端监视器

> 独立桌面 app — 只读观察 stockai 后端进程,Deep Freeze 操作。
> 完整计划: `../monitor-desktop-docs/PLAN.md`

---

## 🚀 快速启动

```bash
cd D:\stocks\monitor-desktop
run.bat
```

首次运行会自动装依赖。窗口打开后,顶部状态条会显示两个 stockai 进程 CPU/RAM/PID/uptime。

---

## 🎯 当前状态 (Step 1)

**已完成**:
- ✅ Electron + Vite + React + Tailwind 工程骨架
- ✅ 主进程 + 预加载 + 渲染进程三层架构
- ✅ 进程监控(`systeminformation` 抓 uvicorn + next-server)
- ✅ 5s 自动刷新 + 暂停/继续
- ✅ 顶部状态条 + 整体 CPU/内存
- ✅ 后端/前端两张进程卡片

**待实现**:
- ⏳ Step 2: 实时日志 tail
- ⏳ Step 3: 数据库结构 + 外键关系图
- ⏳ Step 4: Pipeline 状态 + 错误统计

---

## 🛠️ 开发命令

```bash
# 安装依赖
npm install

# 开发模式(自动打开 Electron 窗口)
npm run dev

# 类型检查
npm run lint

# 打包发布
npm run electron:build
```

---

## 📁 目录结构

```
monitor-desktop/
├── src/
│   ├── main/                  # Electron 主进程
│   │   ├── index.ts           # 主入口
│   │   ├── config.ts          # stockai 路径
│   │   └── monitor/
│   │       └── process.ts     # 进程监控
│   ├── preload/
│   │   └── index.ts           # IPC 桥
│   └── renderer/
│       └── src/
│           ├── App.tsx        # 主 App
│           ├── main.tsx       # React 入口
│           ├── index.css      # Tailwind
│           ├── components/
│           │   └── ProcessPanel.tsx
│           ├── hooks/
│           │   └── useMonitor.ts
│           └── lib/
│               └── api.ts
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
└── run.bat
```

---

## ⚠️ 红线

- 不修改 stockai 代码
- 不写 stockai.db
- 只调 stockai 公开 API(`/api/health` / `/api/pipeline/status`)
- 5s 轮询不爆 CPU
- 不要把 stockai 拖慢

---

## 🐛 已知问题

- `better-sqlite3` 编译失败(Win 工具链缺失) — Step 3 处理,可能改用 `sql.js` (纯 JS WASM)
- `start.bat` 中 stockai 后端 stdout 不重定向到文件 — Step 2 跟用户讨论
