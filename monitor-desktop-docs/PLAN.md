# StockAI 后端监视器 — 项目计划

> **独立桌面 app**,只读观察 stockai 后端一切状态,**deep freeze 操作**。
> 嵌套在 `D:\stocks\monitor-desktop/`,**git ignore 隔离**,stockai 主项目代码 0 改动。

---

## 🎯 项目目标

让用户能在 **桌面窗口** 里实时看到 stockai 后端三件事:

1. **进程状态** — backend uvicorn (3000) / frontend next (3001) / pipeline cron 三块卡片
2. **访问日志** — 类似 `INFO:     ::1:0 - "GET /api/pipeline/status HTTP/1.1" 200 OK` 实时 tail
3. **数据库结构** — `stockai.db` 表清单 + 行数 + 字段 + 外键关系图 + 抽象数据可视化

**核心约束**

- ✅ 只读 — `stockai.db` 用 `mode: 'read-only'`,不写
- ✅ 不污染 stockai — `monitor-desktop/` 整个被 `.gitignore`
- ✅ 不发任何通知(微信/邮件/钉钉) — 纯观察
- ✅ 不自动重启 stockai — 挂了只显示红色告警条
- ✅ 5s 轮询,低频,不爆 CPU
- ✅ 全中文 UI,复用 stockai 暗色主题

---

## 💻 技术栈(10 决策,全部敲定)

| D# | 决策 | 选型 |
|----|------|------|
| **D1** | 窗口壳 | **Electron** |
| **D2** | UI 框架 | **React + Tailwind + shadcn** |
| **D3** | DB 探针 | **表 + 字段 + 外键关系** |
| **D4** | log 来源 | **tail backend/logs/*.log 文件** |
| **D5** | 监控范围 | **backend + frontend + pipeline cron** |
| **D6** | 刷新频率 | **5s** |
| **D7** | 报警/重启 | **纯观察,不做** |
| **D8** | 可视化 | **只表格/数字** |
| **D9** | 启动方式 | **独立桌面 app** |
| **D10** | 持久化 | **纯实时,不落库** |

| 层 | 选 | 理由 |
|----|----|----|
| 主进程 | Electron + TypeScript | 跨平台桌面 app |
| 渲染进程 | Vite + React 18 + Tailwind + shadcn | 复用 stockai 设计系统 |
| 进程监控 | `systeminformation` (Node) | 纯 JS,无需 Python |
| 日志 tail | `fs.watch` + `readline` | 实时跟踪文件 |
| DB 探针 | `better-sqlite3` (只读 mode) | 直接读 stockai.db |
| Pipeline 状态 | `GET /api/pipeline/status` | 唯一调用的内部 API |

---

## 🎨 UI 设计目标

### 视觉风格

- **暗色主题** (oklch 色彩空间, `.dark`),完全复用 stockai palette
- **rounded-none** (`--radius: 0`)
- **Tabler Icons** 唯一图标库(零 emoji 当功能图标)
- **数字列必须 `tabular-nums`**
- **字体**: PingFang SC / Microsoft YaHei (Sans) · JetBrains Mono / SF Mono (Mono)

### 窗口布局(单页 5 个模块)

```
┌────────────────────────────────────────────────────────────────────────┐
│ 📊 StockAI 后端监视器    [⏱ 21:08:35] [🔄 5s 自动刷新] [⏸暂停] [⚙设置] │
├──────────────────────────────────┬─────────────────────────────────────┤
│ 🟢 后端 uvicorn :3000            │ 🟢 前端 next :3001                   │
│ PID 12345 · CPU 12.3% · RAM 380M │ PID 67890 · CPU 5.1%  · RAM 280M    │
│ ⏱ 启动 2h14m · 端口监听 ✅       │ ⏱ 启动 2h14m · 端口监听 ✅            │
│ 🔗 /api/health 200(42ms)        │ 🔗 next ok(18ms)                     │
├──────────────────────────────────┴─────────────────────────────────────┤
│ 📋 实时访问日志                                                       │
├────────────────────────────────────────────────────────────────────────┤
│ 21:08:35  INFO:     ::1:0 - "GET  /api/pipeline/status"        200 OK  │
│ 21:08:40  INFO:     ::1:0 - "POST /api/screener/run"           200 OK  │
│ 21:08:50  WARN:     scheduler: futu-intraday 连接断开,3秒后重试         │
├────────────────────────────────────────────────────────────────────────┤
│ 🗄 数据库结构  stockai.db  ·  📦 24 张表 · 共 128,492 行 · 18.7 MB      │
├────────────────────────────────────────────────────────────────────────┤
│ ⏷ 表列表(按行数降序)             [搜索 ⌕]  [展开外键 ▾]  [导出 JSON]    │
│ ┌──────────────────────┬────────┬────────┬──────────────────────────┐ │
│ │ 表名                  │ 行数   │ 大小   │ 说明                     │ │
│ ├──────────────────────┼────────┼────────┼──────────────────────────┤ │
│ │ futu_raw_kline        │ 85,234 │12.3 MB │ 富途原始 K 线            │ │
│ │ historical_kline      │ 32,156 │ 4.5 MB │ 历史 K 线                │ │
│ │ transactions          │    432 │  68 KB │ 交易记录                  │ │
│ │ holdings              │     12 │   4 KB │ 持仓                      │ │
│ └──────────────────────────────────────────────────────────────────────────┘│
│ 🔗 外键关系(选中某表)                                                  │
│ users ────< transactions ────< dca_plans                                  │
│  └─< holdings >──── transactions ──┘                                      │
├────────────────────────────────────────────────────────────────────────┤
│ 📦 Pipeline 状态    [🟢 空闲]  最后一次: 2026-07-25 22:35 (3h 前)        │
│ ⏵ 步骤进度  ▢ GP挖掘  ▢ ML训练  ▢ 因子衰减  ▢ 数据健康  ▢ 简报推送  │
├────────────────────────────────────────────────────────────────────────┤
│ ⚠️ 错误统计(24h)                                                       │
│ ERROR: 3    WARN: 12    INFO: 1,248                                      │
│ 最近错误: scheduler: futu_intraday 断连 10:23:14                          │
└────────────────────────────────────────────────────────────────────────┘
```

### 交互设计

- **5s 自动轮询** (可暂停/可改频率)
- **表行可点开** — 弹层显示该表所有字段 + 该表外键引出/引向
- **log 关键字过滤** — 输入框过滤 INFO/WARN/ERROR
- **窗口可缩放** — 最小 1024×720,默认 1280×800
- **顶部状态条** — "🟢 全部正常" / "🟡 警告" / "🔴 异常"
- **中文优先** — 一切英文字段名翻译成中文标签(保留原文作为 tooltip)

---

## 📁 目录结构

```
D:\stocks\monitor-desktop\           ← 新建子文件夹,gitignore
├── .gitignore                        # 自身 ignore
├── package.json
├── electron-builder.yml
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── README.md                         # 独立使用文档
├── run.bat                           # 双击启动
│
├── src/
│   ├── main/                         # Electron 主进程
│   │   ├── index.ts                  # 主进程入口
│   │   ├── ipc.ts                    # IPC 通信通道
│   │   ├── monitor/
│   │   │   ├── process.ts            # 3 进程 CPU/RAM/PID/uptime
│   │   │   ├── log.ts                # tail backend/logs/*.log
│   │   │   ├── database.ts           # better-sqlite3 只读探针
│   │   │   └── pipeline.ts           # GET /api/pipeline/status
│   │   └── config.ts                 # stockai 路径/端口配置
│   │
│   ├── preload/
│   │   └── index.ts                  # contextBridge 暴露 API
│   │
│   └── renderer/                     # React UI
│       ├── index.html
│       ├── src/
│       │   ├── App.tsx
│       │   ├── main.tsx
│       │   ├── components/
│       │   │   ├── ProcessPanel.tsx        # ① 进程总览
│       │   │   ├── LogPanel.tsx            # ② 实时日志
│       │   │   ├── DatabasePanel.tsx       # ③ DB 结构
│       │   │   ├── PipelinePanel.tsx       # ④ Pipeline 状态
│       │   │   └── ErrorStats.tsx          # ⑤ 错误统计
│       │   ├── hooks/
│       │   │   └── useMonitor.ts           # 5s 轮询 IPC
│       │   └── lib/
│       │       └── api.ts                  # IPC 包装
│       └── styles.css
│
└── dist/                             # 编译产物 (gitignore)
```

**主项目 `.gitignore` 增量:**

```
# 后端监视器 (独立子项目)
monitor-desktop/
monitor-desktop-dist/
```

---

## 🧩 5 大功能模块

| # | 模块 | 展示 | 数据源 |
|---|------|------|--------|
| ① | **进程总览** | backend/frontend/pipeline cron 三块卡片,每块显示 PID · CPU · RAM · uptime · 端口✅ | `systeminformation` |
| ② | **实时日志** | tail `backend/logs/*.log`,按时间倒序滚动,关键字过滤栏 (INFO/WARN/ERROR) | `fs.watch` |
| ③ | **数据库结构** | 卡片头: `📦 24 张表 · 128K 行 · 18.7MB`<br>表清单(按行数排序,可搜索)<br>点开表 → 字段表 + 外键关系图 | `better-sqlite3` 只读 |
| ④ | **Pipeline 状态** | 当前步骤 / 进度 / brief_id / 启动时间 | `GET /api/pipeline/status` |
| ⑤ | **错误统计** | 24h 内 ERROR/WARN 数量 + 最近 5 条具体错误 | tail logs grep |

---

## 🚀 4 步交付(每步独立可跑)

| Step | 交付 | 时间 |
|------|------|------|
| **1️⃣ 骨架** | Electron + Vite + React 跑起来,顶部窗口出现,3 进程 CPU/RAM 数字刷新 | 1 天 |
| **2️⃣ 日志** | LogPanel 实时 tail + 过滤 + 滚动 | 半天 |
| **3️⃣ DB 探针** | 表清单 + 字段 + 外键关系图 | 1 天 |
| **4️⃣ 完善** | Pipeline 状态 + 错误统计 + 中文检查 + dark mode | 半天 |

**总估时:3 天**

---

## 🚧 严格红线(绝不违反)

- ✅ `stockai.db` 用 `mode: 'read-only'` 打开,不写
- ✅ 不调 stockai 内部 API(**仅** `/api/pipeline/status` + `/api/health` 两个公开端点)
- ✅ 不动 stockai 一个字符代码(backend/ frontend/ tests/ 等)
- ✅ `monitor-desktop/` 整体 gitignore
- ✅ 5s 轮询,低频,不要把 stockai 拖慢
- ✅ 不改 start.bat (除非用户主动允许)
- ✅ 全中文 UI
- ✅ 暗色主题,复用 stockai 的 Tailwind tokens

---

## ⚠️ 动手前需确认

1. **stockai 后端是否已存在 `backend/logs/` 目录?**
   - 如果没有,access 日志只走 stdout,需要改 start.bat 加 `> logs/access.log 2>&1`
   - 需要先看 `start.bat` 现状

2. **`stockai.db` 路径确认**
   - 我推测是 `D:\stocks\backend\database.db`,但要验证

---

## 🚥 当前状态

- [x] **Step 0**: 10 个决策全部敲定 ✅
- [ ] **Step 1**: Electron + Vite + React 骨架 + 进程监控
- [ ] **Step 2**: 日志 tail 面板
- [ ] **Step 3**: DB 探针
- [ ] **Step 4**: Pipeline 状态 + 错误统计 + 完善

**等待用户确认 MD 文件分类后,开始执行 Step 0 (探查) + Step 1 (骨架)**。
