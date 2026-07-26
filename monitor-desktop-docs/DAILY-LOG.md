# StockAI 后端监视器 — 每日改动日志

> 按时间倒序记录:**今天 → 昨天 → …**
> 记录每次 commit / 每次踩坑 / 每次决策改动

---

## 2026-07-26(今天)

### 🚀 监视器 v0.1.0 commit + push 完成 ✅

- 3 个 commit 全部推送到 main:
  - `3b186cb` fix: 近期 bug 修复(stale-state + multi_agent 测试 + screener TDZ)
  - `f36537a` docs: 重构 MD 文档结构 + 新建根目录 INDEX.md
  - `cc3562e` feat(monitor): 引入 StockAI 后端监视器 v0.1.0 (Electron 桌面 app)
- **30 个监视器文件**, 6570 行新增, 全部入仓
- `package-lock.json` 一并入仓, 方便复现依赖
- `.gitignore` 排除了 `monitor-desktop/{node_modules,dist,dist-electron,release,*.log}`

### 📚 CHANGELOG.md 同步

- `stockai-project-docs/CHANGELOG.md` 顶部新增 `2026-07-26 — v3.11.x 补丁 + Monitor v0.1.0 引入` 段
- 记录:bug fixes / docs 重构 / monitor v0.1.0
- 预告:**v4.0** 大更新(规划中)

### 📚 PLAN.md 同步

- `monitor-desktop-docs/PLAN.md` 全部 4 步标记完成
- "当前状态"段加入 v0.1.0 commit 信息 + 下一阶段(v4.0 / v0.2.0)

---

## 2026-07-26(今天,之前记录)

### 📋 文档结构重组

- **新增** `D:\stocks\stockai-project-docs/` — 放 stockai 项目 MD
- **新增** `D:\stocks\monitor-desktop-docs/` — 放监视器 MD
- **新增** `D:\stocks\INDEX.md` — 根目录入口说明
- **迁移** 6 个根目录 MD 到 `stockai-project-docs/`:
  - `AGENTS.md` / `CHANGELOG.md` / `DESIGN.md` / `README.md` / `README.en.md` / `TODOS.md`
- **保留** `D:\stocks\CLAUDE.md` 在根目录(Claude Code 入会必读)
- **更新** `CLAUDE.md` 引用路径 → `stockai-project-docs/CHANGELOG.md` / `stockai-project-docs/DESIGN.md`

### 💡 监视器计划敲定

- **10 决策 / 10 ✅**:
  - D1 窗口壳: Electron
  - D2 UI: React + Tailwind + shadcn(实际简化为纯 Tailwind)
  - D3 DB: 表 + 字段 + 外键
  - D4 log: tail 文件(改为虚拟 access log)
  - D5 监控: backend + frontend + pipeline cron
  - D6 频率: 5s
  - D7 报警: 纯观察,不做
  - D8 可视化: 只表格/数字
  - D9 启动: 独立桌面 app
  - D10 持久化: 纯实时
- **5 模块**: 进程总览 / 实时日志 / DB 结构 / Pipeline 状态 / 错误统计
- **4 步交付**: 骨架 → 日志 → DB 探针 → 完善(总估时 3 天)
- **完整方案**写入 `monitor-desktop-docs/PLAN.md`

### 🏗 Step 1 — 骨架 ✅

- 创建 `D:\stocks\monitor-desktop/` 工程目录
- 配置文件: `package.json` / `tsconfig.json` / `vite.config.ts` / `tailwind.config.js` / `postcss.config.js` / `index.html`
- 主进程: `src/main/index.ts` + `src/main/config.ts` + `src/main/monitor/process.ts`
- 预加载: `src/preload/index.ts`
- 渲染: `src/renderer/src/{App.tsx, main.tsx, index.css, components/ProcessPanel.tsx, hooks/useMonitor.ts, lib/api.ts}`
- 启动: `run.bat`
- **build 验证**: tsc 0 错误,vite 5 产物全部生成

### 🏗 Step 2 — 日志面板 ✅

- **新增** `src/main/monitor/logger.ts`
  - 内存 ring buffer (1000 条)
  - `loggedFetch()` 包装 fetch → 自动记 INFO/WARN/ERROR 日志
  - `startHealthProbe()` 每 5s ping stockai `/api/health` → 形成"虚拟 access log"
- **新增** `src/renderer/src/components/LogPanel.tsx`
  - 实时滚动列表 + 关键字搜索 + INFO/WARN/ERROR 过滤
  - 自动滚动开关 + 清空按钮
- **修改** `src/main/index.ts` 注册日志 IPC
- **修改** `src/preload/index.ts` 暴露日志 API + `onLogsUpdated` 事件

### 🏗 Step 3 — DB 探针 ✅

- **新增** `src/main/monitor/database.ts`
  - 用 `child_process` 调 Python `sqlite3` 子进程(避免 better-sqlite3 native 编译 + sql.js 245MB 全量加载内存爆)
  - 支持 `summary`(所有表清单 + 行数 + 大小)+ `table_detail`(字段 + 外键 + 索引 + 抽样 5 行)
  - 30s 内存缓存,避免每 5s 都跑 Python
- **新增** `src/renderer/src/components/DatabasePanel.tsx`
  - 左右分栏:左表清单(可搜索/排序)+ 右表详情
  - 字段表 + 外键链表 + 索引列表 + 抽样数据

### 🏗 Step 4 — Pipeline 状态 + 错误统计 + 完善 ✅

- **新增** `src/main/monitor/pipeline.ts`
  - 每 10s 拉 `GET /api/pipeline/status`
  - 解析 status / step / progress / brief_id
- **新增** `src/renderer/src/components/PipelinePanel.tsx`
  - 5 步进度条 (GP 挖掘 → ML 训练 → 因子衰减 → 数据健康 → 简报推送)
  - 元信息表格(当前步骤/进度/开始/结束/brief_id)
- **新增** `src/renderer/src/components/ErrorStats.tsx`
  - 总日志 / INFO / WARN / ERROR 计数
  - 1h 内 ERROR / WARN 高亮
- **整合** `src/renderer/src/App.tsx`
  - 三栏布局:进程卡片 + Pipeline + 错误统计
  - 下方双栏:日志 + 数据库
- **新增** `src/types.ts` — 跨进程共享类型
- **build 验证**: tsc 0 错误,vite 5 产物全部生成

### 🐛 踩坑

1. **better-sqlite3 native 编译失败** — Win 工具链缺失
   - **方案**: 改用 `child_process` 调 Python sqlite3(系统自带,不需额外依赖)
   - **代价**: 每次查询有 Python 启动开销(~100ms),但 30s 缓存足够
2. **sql.js 245MB 全量加载会爆内存** — 不用
3. **vite-plugin-electron simple 模式覆盖产物** — 改用数组配置,main + preload 输出到独立子目录
4. **preload 类型导出名错** — `TableDetail` 改成 `TableInfo`

### 🚧 仍待做(可选)

- 真实 tail `backend/logs/*.log`(需用户允许改 start.bat 加 stdout 重定向)
- 数据库详情缓存(LRU)
- 暗色主题微调(目前用 oklch,微调空间大)
- 设置面板(可改轮询频率)

---

## 2026-07-25(昨天)

### 📦 项目交付

- (此处记录 stockai 项目昨天的改动,后续维护)

---

## 格式约定

每次记录写:

```markdown
### 📋 标题 / 💡 决策 / 🐛 踩坑 / 🚧 进行中

- **具体动作**: 描述做了什么
- **原因**: 为什么
- **影响**: 影响什么
```

**Commit 模板** (后续):

```bash
git add monitor-desktop/ monitor-desktop-docs/
git commit -m "monitor: <简单描述>"
```