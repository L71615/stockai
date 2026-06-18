# StockAI 项目日志

## 2026-06-18 — K 线图表升级（lightweight-charts）+ TradingView 集成

### 新功能

**持仓详情抽屉 — K 线图表**
- `backend/routers/holdings.py` 新增 `GET /api/stocks/kline/{code}?period=5d|1m|3m|6m` 端点
  - 直连腾讯财经 K 线 API，返回 OHLCV + MA5/MA10/MA20
  - 支持 5 日 / 日K(22天) / 周K(聚合) / 月K(聚合) 四种周期
- `backend/services/akshare_adapter.py` 修复：`get_kline()` 补充成交量字段（`k[5]`），之前遗漏导致全为 0
- `frontend/src/components/data-table.tsx` — `StockDetailDrawer` 重写
  - 点击持仓名称 → 右侧抽屉弹出 K 线蜡烛图 + 成交量柱
  - 图表顶部摘要：现价/成本/持仓/盈亏
  - 周期切换标签：5日 | 日K | 周K | 月K
  - MA5(琥珀)/MA10(紫)/MA20(青) 均线叠加
  - 鼠标悬停显示开/高/低/收/量

**K 线图表升级 — lightweight-charts（TradingView）**
- 新增 `frontend/src/components/KlineChart.tsx`（新建组件）
  - 替换 recharts `ComposedChart` + 自定义 Bar shape → TradingView `lightweight-charts@5.2.0`
  - 内置 CandlestickSeries（蜡烛图）+ HistogramSeries（成交量）+ LineSeries（MA5/10/20）
  - 原生 ResizeObserver 支持，Drawer 打开时自动检测正确尺寸
  - v5 API：`chart.addSeries(CandlestickSeries, options)`
- `frontend/src/components/stock-chart-drawer.tsx` — 同上替换
- 删除了 `data-table.tsx` 中 60+ 行废弃代码（`KlineBar`/`BarShapeProps`/`KlineTooltip`/`toBars`/`renderCandle`/`renderVolume`）
- **根因修复**：recharts `ResponsiveContainer` 在 shadcn Drawer hidden 状态下初始化时返回宽高 -1，导致 chart 初始化失败

**Accessibility 修复**
- `DrawerContent` 添加 `DrawerDescription`（sr-only），消除 React a11y 警告

### Bug 修复

**持仓概览显示问题**
- Bug #21: 持仓名称显示为录入时的名字（如 "rainbow"） → 优先使用实时行情 API 返回的名称
- Bug #22: "持仓占比" 标签名误导 + 用 `Math.round(市值/成本-1)` 独立计算导致精度丢失 → 标签改为"总收益率"，直接使用后端 `total_pnl_pct`（已扣预估卖出费）

### 技术依赖

- `lightweight-charts@^5.2.0` — TradingView 开源金融图表库（MIT）
  - 参考：https://tradingview.github.io/lightweight-charts/
  - TradingView Pine Script 指标生态丰富，后续可对接更多指标

### 已知问题

- K 线图表：鼠标悬停 OHLCV 数字显示可进一步优化（lightweight-charts crosshair label）
- 成交量下方未显示具体数字，只有柱状高度
- 分钟级 K 线数据源未接入（东财 `klt=1/5/15/30/60` 未接入）

---

## 2026-06-17 — 持仓删除功能 + 盈亏对齐同花顺

### Bug 修复 (2 个)

**全局**
- Bug #19: Next.js API 代理端口错误 — `next.config.ts` 将 `/api/*` 转发到 `localhost:3002`（空端口），导致所有前端 API 请求失败。改为 `localhost:3000`。
- Bug #20: 持仓删除功能缺失 — `page.tsx` 的 `onDelete` 回调只有 `alert("删除 暂未实现")`。加入完整删除链路：AlertDialog 确认 → `DELETE /api/stocks/holdings/{id}` → SWR 乐观更新。

### 新功能

**盈亏对齐同花顺**
- `backend/routers/holdings.py` 新增 `_estimate_sell_fee()` 函数，预估卖出费用（佣金 + 印花税 0.05% + 过户费 0.002%）
- 盈亏公式改为同花顺口径：`PnL = (现价 - 成本价) × 数量 - 预估卖出费`
- 盈亏% 改为：`PnL / 总成本 × 100%`（之前是 `现价/成本 - 1`）
- 汇总端也改为逐项 net PnL 求和，不再用总市值减总成本
- 验证结果：彩虹股份 400 股，StockAI vs 同花顺 → 盈亏 ¥308.37 vs ¥308.18（差 ¥0.19 来自成本价小数位精度）

**持仓删除**
- `frontend/src/app/page.tsx`：引入 AlertDialog 确认弹窗 + `handleDelete` 调用 `DELETE /api/stocks/holdings/{id}`
- SWR 乐观更新：删除后立即从缓存移除该行，不等网络返回
- `HomeHolding` 类型增加 `id` 字段，`tableData` 增加 `holdingId` 传递真实数据库 ID

### 费率验证

- 核查同花顺交割单：佣金 5 元/笔（万 2.5 兜底）、印花税仅卖出、过户费未单独列
- StockAI 默认费率与券商一致：`commission_rate=0.00025, commission_min=5.0`

### 已知问题

- 端口 3000 僵尸进程（PID 3476）：Windows TCP 端点泄露，进程已死但端口被内核卡住。`taskkill`/`Stop-Process`/`wmic`/管理员权限均无法释放，需重启系统。当前临时用 3008 端口。

---

## 2026-06-12 ~ 2026-06-13 — Bug 修复 + 功能增强

### Bug 修复 (6 个)

**自选股**
- Bug #1: ETF/基金现价小数位 — `fund→4, etf→3, stock→2`，添加 `decimals()` 辅助函数
- Bug #2: 行情字段映射错误 — `price ?? change ?? 0` 导致涨跌额当现价，改为独立 null 检查
- Bug #3: 添加自选后数据覆盖 — quotes 失败时覆盖已有数据，改为过滤 error + 只在有效值才覆盖
- Bug #6: 沪市 ETF 符号映射 — `_symbol()` 漏了 51/56/58 前缀，导致请求到 `sz` 接口返回空数据

**交易记录**
- Bug #4: 添加交易失败 — 前端 `trade_date` vs 后端 `traded_at` 字段名不匹配

**持仓概览**
- 现价/成本/总资产/今日盈亏/盈亏统一显示两位小数
- PnL 列从 `Math.round()` 改为 `toFixed(2)`

**量化分析**
- Bug #5: ETF 行情假数据 — 腾讯 API 对部分 ETF 返回 name="北京2474" price=100.0，加检测+兜底
- Bug #10: 技术指标显示 "undefined" — MA/MACD/KDJ 是多键对象，前端不当读 `val.value`
- Bug #11: 组合风险指标全显示 "--" — Sharpe/回撤/波动率被绑在基准数据上，分离计算
- Bug #12: Beta 始终为 None — 沪深 300 指数无法从 K 线源获取，改用 510300 ETF 代理
- Bug #14: 回测/策略对比字段名不匹配 — `dca_return`→`total_return`, `return_pct`→`return`
- Bug #15: 蒙特卡洛亏损概率 "--" — `loss_prob`→`prob_loss`, `loss_15_pct`→`prob_loss_15pct`
- KPI 百分比修正：回撤/波动率 × 100 显示

**AI 选股**
- Bug #16: 扫描后无结果 — `/results` 返回 `{candidates:[...]}` 但前端当数组处理
- Bug #17: 页面崩溃 — `top_factors` 是对象数组，直接渲染 `{f}` 报 React 错误
- Bug #18: 名称/行业为空 — `_process_single_stock` 不从 stock_list 取名字，加兜底逻辑
- 评分显示 `toFixed(0)` → `toFixed(1)`

**全局 UI**
- 全站 `<select>` 下拉框 `bg-transparent` → `bg-background text-foreground`（暗色模式可见）

### 新功能

**持仓分析 — 行业分布饼图**
- `frontend/src/components/sector-pie-chart.tsx` — recharts 环形饼图
- `page.tsx` 集成：调用 `/api/stocks/diversification`，KPI 和图表之间展示
- 暗色友好 12 色调色板，悬停显示行业名/占比/市值

**手续费追踪**
- `backend/services/utils.py` — `calc_fee()` + `FeeConfig`：stock/etf 自动计算佣金/印花税/过户费
- 佣金率可配置：`settings` 表存储，设置页面 UI，`GET/PUT /api/settings/fee-config`
- 费用计入 amount（买入 +fee，卖出 -fee），自动流入成本重算/PnL/XIRR
- `POST /api/stocks/recalc-fees` — 一键重算所有历史交易手续费并更新持仓成本
- 交易页面：佣金列 + 自动/手动切换 + 总佣金 KPI 卡片

**总资产走势图真实数据**
- `GET /api/stocks/holdings/history` — 累计成本日线 + 当前市值
- `ChartAreaInteractive` 重写：两条线（成本灰虚线 + 市值红实线），真实日期

**KOL 大佬观点 — 代理支持**
- `backend/services/kol_crawler.py` — `_get_proxy()` 从环境变量/`settings` 表读取代理
- `PUT /api/kol/proxy` — 设置/清除爬虫代理
- `PUT /api/kol/proxy` — 获取当前代理配置

### 技术改进
- 复盘页面：修复 `total_trades` 只统计卖出导致冷启动；generate 后不再重复 `fetchLatest` 闪烁
- 复盘门槛：5→3 笔交易即可生成
- `useRef` TS 修复：`useRef<ReturnType<typeof setTimeout>>(null)`
- 数据库迁移：`transactions` 表加 `fee` 列 ALTER TABLE 兜底

---

## 2026-06-12 — Next.js + shadcn/ui 前端重构

### 项目初始化
- `npx create-next-app@latest frontend-next` — 创建 Next.js 16 (App Router) 项目
- `npx shadcn@latest init --preset b3ZNO4HQhu` — 初始化 shadcn/ui 主题 (oklch 中性色)
- 配置 Tailwind CSS 4 `@theme inline` 字体：系统中文字体栈 + JetBrains Mono
- 默认暗色模式 (`<html class="dark">`)
- `--radius: 0` 全局直角风格
- `next.config.ts` 添加 `/api/*` → `localhost:3000` 代理

### 侧边栏
- 安装 `sidebar` `collapsible` `tooltip` shadcn 组件
- 创建 `app-sidebar.tsx`：12 项中文导航，3 折叠组 (投资/分析/工具)
- `SidebarProvider` + `TooltipProvider` 包裹根布局
- `app-layout.tsx` 客户端布局组件，登录页自动隐藏侧边栏
- `usePathname()` 自动高亮当前路由

### 首页：持仓概览
- 融合 dashboard-01 模板的 SectionCards → ChartAreaInteractive → DataTable 三段式布局
- 安装 `card` `button` `input` `label` `separator` `badge` `table` `dropdown-menu` `checkbox` `drawer` `tabs` `select` `toggle-group` `breadcrumb` `avatar` `chart` 等组件
- KPI 卡片 (总资产/今日盈亏/持仓数量/持仓占比)
- recharts 面积图 (总资产走势，红色)
- DataTable 持仓表格 (可拖拽排序/分页/列显隐/详情抽屉)，红涨绿跌

### 大盘指数 `/market`
- 对接 `GET /api/stocks/indices/global`
- 按地区分组 (中国/美国/欧洲/亚太)，响应式网格 (1-4 列)
- 指数卡片：名称/代码/现价/涨跌额/涨跌幅，红涨绿跌
- 30 秒自动刷新 + 手动刷新按钮
- 骨架屏加载 + 错误重试

### 全球资讯 `/global-news`
- 对接 `GET /api/stocks/news/global/{region}`
- SVG 世界地图 (深海色背景 + 经纬网 + 大陆点阵)
- 16 个金融中心城市点 (脉冲动画 + 标签)
- 资本流动曲线连线
- 顶部地区快捷标签栏 + 右侧新闻面板
- 点击新闻外链跳转

### AI 复盘 `/review`
- 对接 `POST /api/stocks/review/structured` + `GET /api/stocks/reviews`
- 3 列统计卡片 (总盈亏/交易次数/综合评分)
- AI 洞察紫色左边框卡片
- 交易维度分析折叠面板 (高/中/低评分彩色标签)
- 改进建议卡片 (查看理由/收起理由切换)
- 历史报告下拉选择器

### 量化分析 `/quant`
- 对接 `GET /api/quant/stock-insight/{code}` `/api/quant/portfolio-risk` `/api/quant/backtest` `/api/quant/compare` `/api/quant/monte-carlo`
- 股票输入 + 周期选择 → K线图 (recharts AreaChart)
- 技术指标网格 (MA/MACD/KDJ/RSI + 信号标签)
- 基本面因子行 (PE/ROE/EPS/市值/行业)
- 组合风险 Tab：Sharpe/最大回撤/波动率/Beta + 相关性标签
- 策略回测 Tab：定投回测 + 4 策略对比
- 蒙特卡洛 Tab：模拟参数 + 终值分布柱状图 (红涨绿跌)

### AI 选股 `/screener`
- 对接 `POST /api/screener/run` `GET /api/screener/results` `POST /api/screener/ai-screen` `POST /api/screener/backtest/batch` watchlist CRUD
- 操作栏：开始扫描/进度条/AI精选/一键流程
- 左列：多因子候选池表格 (评分条+因子标签+回测+加入盯盘)
- 右列：AI 精选卡片 (紫色推理文本) + 盯盘列表 (删除)
- 扫描进度轮询 (2 秒间隔)

### 大佬观点 `/kol`
- 对接 `GET /api/kol/accounts` `POST /api/kol/crawl` `GET /api/kol/briefs/latest` `POST /api/kol/briefs/generate`
- 操作栏：刷新帖子(爬取)/生成日报/添加账号
- 追踪账号标签条 (删除按钮 + 停用账号划线)
- 添加账号表单 (X用户名/显示名/分类)
- AI 日报卡片：摘要/情绪柱 (牛/中/熊)/热议话题/牛熊观点/提及股票/金句引用

### 交易记录 `/transactions`
- 对接 `GET/POST/PUT/DELETE /api/stocks/transactions`
- 4 KPI 统计卡片 (总交易/买入额/卖出额/净额)
- 添加/编辑表单 (代码/名称/类型/方向/价格/数量/日期/备注)
- 交易表格 (日期/股票/方向标签/价格/数量/金额/备注)
- AI 复盘按钮 (紫色左边框结果卡片)

### AI 对话 `/ai-assistant`
- 对接 `GET /api/agents/agents` `POST /api/ai/chat`
- Agent 下拉选择器 + 工具标签
- 5 个快捷指令标签 (分析持仓/交易复盘/定投建议/市场概览/持仓新闻)
- 聊天气泡 (用户/助手/错误/加载中)
- 对话持久化 (conversationId)

### Agent 工坊 `/skills`
- 对接 `GET/POST/PUT/DELETE /api/agents/agents` `GET/POST /api/agents/{id}/memory`
- Agent 卡片网格 (名称/描述/工具标签/操作按钮)
- 创建/编辑表单 (名称/描述/系统提示词/工具勾选)
- 记忆面板 (紫色左边框，时间戳条目，添加记忆输入框)

### 设置 `/settings`
- 对接 `GET/PUT /api/settings/ai-configs` `GET/PUT /api/settings/smtp` `POST /api/settings/smtp/test`
- 6 家 AI 供应商配置 (MiniMax/DeepSeek/OpenAI/Claude/小米/自定义)
- 每供应商：API Key 密码框 + Model 输入 + Base URL 输入
- SMTP 邮件配置 (服务器/端口/邮箱/密码/用户名)
- 测试发送 + 退出登录按钮

### 自选股 `/watchlist`
- 对接 `GET/POST/DELETE /api/stocks/watchlist` `GET /api/stocks/lookup/{code}` `POST /api/stocks/quotes`
- 代码自动查询 (500ms 防抖) + 市场/类型自动检测
- 批量行情报价 (30 秒自动刷新)
- 表格：代码/名称/现价/涨跌幅/涨跌额/成交量/最高/最低
- 操作：加入持仓(数量+成本价弹窗) / 跳转量化分析 / 移除(AlertDialog确认)

### 登录 `/login`
- 对接 `POST /api/auth/login` JWT 认证
- `lib/auth.ts` 封装 Token 管理 + `apiGet`/`apiPost` 认证请求
- 未登录自动跳转 `/login`

### 架构变更
- 后端去掉 `StaticFiles` 挂载 → 纯 API 服务器 (端口 3000)
- `frontend-next/` → `frontend/` (正式上位，旧 HTML/JS 前端删除)
- `start.bat` 升级为双服务器控制面板 (后端+前端)
- `next.config.ts` 添加 `devIndicators: false` 隐藏开发标记

### 项目清理
- 删除 `__pycache__/` × 3、`.pytest_cache/`、`.next/` 构建缓存
- 删除空目录 `backend/config/` `routes/` `models/`、`skills/`
- 删除测试脚本 `test_playwright.py` `test_twikit.py` `test_x_api.py` `extract_x_queries.py`
- 删除模板残留 `frontend/src/app/dashboard/`
- 删除调试文件 `x_response_debug.json`、`BRANCH=main/`
- Docker 文件归档到 `docker/`
- Python 配置移到 `backend/` (pytest.ini, requirements-dev.txt, .env.example)
- 归档文档到 `docs/` (PROJECT_PLAN.md, TODOS.md)
- 删除 `SKILLS.md`、frontend 模板 README/AGENTS/CLAUDE

### 文档更新
- `DESIGN.md` — 全面更新 (Next.js + shadcn/ui 架构、Tailwind CSS 4、组件模式、决策日志)
- `README.md` — 更新项目结构、启动方式、路由表、技术栈
- `CHANGELOG.md` — 本项目日志 (新建)

### 已知问题 (待修)
- 自选股：ETF/基金现价小数位不准确，行情数据字段映射错误
- 交易记录：添加交易功能有问题
- 性能：每次页面切换数据重新加载，需引入 SWR 缓存

---

## 2026-05-20 ~ 2026-06-10 — 原始项目搭建

### MVP 阶段
- FastAPI 后端骨架 (JWT 认证、SQLite 数据库)
- Vanilla JS/HTML/CSS 前端 (12 个页面)
- AI 对话 (MiniMax/DeepSeek/OpenAI/Claude/小米)
- A股行情数据 (腾讯财经/AKShare/新浪)
- 量化分析引擎 (Sharpe/MaxDD/Beta/DCA/蒙特卡洛)
- AI 策略对抗 (多 AI 选股 PK)
- Agent 系统 (自定义 Agent + 记忆)
- 多因子选股扫描
- 大佬观点 X/Twitter 追踪
- Docker 部署配置
