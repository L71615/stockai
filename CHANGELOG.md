# StockAI 项目日志

> StockAI 从 0 到 v3.5 的完整演进记录。按时间倒序。

---

## 2026-06-26 #3 — 条件选股性能优化 + 候选池保护 + 数据源故障诊断

### 问题定位

用户反馈条件选股页面"扫描失败: HTTP 500"，逐步排查发现三层问题：

**1. 首次扫描串行太慢 → 加并发**

`get_stock_factors_http` (AKShare) 串行调用 800 次 × 0.5s = 400s。L3a 改为 `ThreadPoolExecutor(max_workers=5)` 并发处理，300 只降至 ~3s。

**2. 无 L1/L2 过滤时全量进 L3/L4 → 加候选池上限**

超跌反弹、高股息防御等策略模板没有 L1(行业)/L2(价格) 条件，800 只直接进 L3/L4 → 挂死。

修复:
- L3a 候选上限 500 (AKShare并发, 超出返回400+提示)
- L3b 候选上限 200 (Baostock慢, 超出跳过并警告)
- L4 候选上限 300 (K线获取慢, 超出返回400+提示)
- K线获取天数从 120→60 减少传输量

**3. K线数据源大面积故障（根本原因）**

| 数据源 | 状态 |
|---|---|
| 腾讯 `web.ifzq.gtimg.cn` | HTTP 501 Not Implemented |
| 东方财富 `push2his` | 不可用 |
| Baostock | 可用但慢 (单次3-5s, RLock串行) |

`fetch_kline` 依次尝试腾讯(3s超时)→东财(失败)→Baostock(5s)，每只股票 ~8s。
`_http_get` 默认超时从 10s → 3s，减少等待。

**L2/L3 条件选股（PE/PB/ROE/价格/行业）完全可用，秒级返回。L4 需等腾讯/东财恢复。**

### Baostock 稳定性增强

- `_ensure_login()`: 登录失败后 60s 冷却，避免 bs.login() 反复阻塞
- `get_all_stock_list()`: Baostock 部分 ThreadPoolExecutor 包裹 8s 超时
- 股票池回退: Baostock 全 A 股查询失败 → 仅用沪深300+中证500 (800只)
- 行业字段已知问题: Baostock 行业查询也失败 → industry 显示为股票名

### 文件变更
- `backend/routers/screener.py`: L3a 并发化(ThreadPoolExecutor 5workers) + L3/L4 候选上限 + K线 60天 + L4 并发 6workers
- `backend/services/akshare_adapter.py`: `_http_get` 超时 10s→3s
- `backend/services/baostock_adapter.py`: 登录冷却机制
- `backend/services/screener_service.py`: Baostock 线程超时 + 股票池回退
- `CHANGELOG.md`: 补充本次排查记录

### 已知待解决
- [ ] K线数据源恢复监控 (腾讯/东方财富)
- [ ] 股票池扩至全 A 股 (需 Baostock query_stock_basic 恢复)
- [ ] L3/L4 上限可通过前端 `force` 参数绕过
- [ ] 前端策略模板加载 `close>open` (compare_field) 条件丢失

---

## 2026-06-26 #2 — 因子清理 + K线修复 + 条件选股L3两阶段重构

### K线图表三合一修复 (KlineChart.tsx)

**Bug: RSI/KDJ 线与K线时间轴不对齐**

根因：`toLine()` 函数先 `filter` 掉 null 再 `map`，index 重排导致所有指标线向左平移预热期长度（RSI -14天，KDJ -9天，MACD -35天）。改为先 `map` 保留原始 index 再 `filter`。

**新增：图表下方指标讲解栏**

显示每个可见指标的最新值 + 自动解读（金叉/死叉/超买/超卖/放量/缩量/多头/空头），颜色信号区分多空。

**优化：默认指标 + 坐标轴**
- 默认从 VOL+BOLL+MACD+RSI(4个) → VOL+MACD(2个)
- RSI/KDJ 子面板 scaleMargins 收紧，参考线始终可见

### 因子体系清理 (57→55)

**修复 5 个阈值单位不匹配 (quant.py):**

| 因子 | 根因 | 修复 |
|---|---|---|
| PE | 阈值写的是原始PE(10~100)，因子返回盈利率 1/PE | 阈值改为盈利率 |
| PB | 同上 | 阈值改为 1/PB |
| ROE | 阈值写百分比(2~35)，因子返回小数 | 阈值改为小数 |
| DIVIDEND_YIELD | 同上 | 阈值改为小数 |
| AVG_AMOUNT | 阈值写原始金额(1e6~1e9)，因子返回 log10 | 阈值改为 log10 |

**删除 2 个死因子:**
- SOCIAL_RANK / SOCIAL_BUZZ — 雪球 API 不可用，永远返回 0.0→5分
- 同步清理：FACTOR_REGISTRY / compute_all_factors / IC 权重 / 注释

### 条件选股 L3 两阶段重构 (screener.py)

**根因：** 高股息防御等含 `dividend_yield`/`debt_ratio`/`market_cap` 的策略永远 0 结果。L3 中 Baostock 字段只在候选<100时填充，但无 L1/L2 过滤时 800 只全进 L3 → Baostock 被跳过 → 字段永不填充 → 全部淘汰。

**修复：** L3 拆为 L3a + L3b
- L3a: AKShare HTTP 处理 PE/PB/ROE，先缩池
- L3b: Baostock 处理 dividend_yield/debt_ratio/market_cap，阈值 100→200

### Baostock 超时保护

- `_ensure_login()`: 登录失败后 60s 冷却，避免 bs.login() 反复阻塞
- `get_all_stock_list()`: Baostock 部分用 ThreadPoolExecutor 包裹 8s 超时

### 文件变更
- `frontend/src/components/KlineChart.tsx` (613→803行)
- `backend/routers/quant.py` (5行阈值 + 删社交因子)
- `backend/services/factor_service.py` (删 SOCIAL_RANK/SOCIAL_BUZZ)
- `backend/services/screener_service.py` (删社交 IC 权重 + Baostock 线程超时)
- `backend/routers/screener.py` (L3 拆 L3a+L3b, ~40行)
- `backend/services/baostock_adapter.py` (登录冷却机制)
- `backend/routers/screener.py` (注释更新)

---

## 2026-06-26 #1 — 条件选股两层→四层过滤架构重构

### 问题诊断

条件选股页 (`/screener/condition`) 存在 7 个严重 Bug，导致大多数条件字段不可用：

| # | Bug | 影响 |
|---|-----|------|
| 1 | `pe`/`pb`/`dividend_yield`/`debt_ratio`/`market_cap` 始终为 `None` | 所有基本面条件（除 ROE）完全失效 |
| 2 | `avg_amount_20d` 不在 `KLINE_FIELDS` 中 | 9 个策略 YAML 都依赖此字段，但单独使用时永不触发 K 线 |
| 3 | `_has_kline()` 和 `_strip_kline()` 不检查 `compare_field` | `close > ma20` 被误判为非 K 线条件 → 静默筛掉 |
| 4 | `market_cap` 死字段 | 市值条件从未被填充 |
| 5 | `_strip_kline()` 每只股票调用一次 | 不必要重复 |
| 6 | 条件引擎缺失字段静默返回 `False` | 无日志，调试困难 |
| 7 | `ret_5d`/`ret_20d` 返回小数 (0.05)，策略 YAML 用百分比 (5) | 条件判断不匹配 |

### 四层过滤架构

按数据获取成本从低到高分为四层：

| 层 | 数据来源 | 成本 | 字段 |
|---|---|---|---|
| L1 股票列表 | `get_all_stock_list()` 内存缓存 | 零 | `industry` |
| L2 实时行情 | 腾讯 `qt.gtimg.cn` 批量 HTTP | 极低 | `price` |
| L3 基本面 | AKShare `stock_financial_abstract_ths` + Baostock 兜底 | 中等 | `pe`, `pb`, `roe`, `dividend_yield`, `debt_ratio`, `market_cap` |
| L4 K线+指标 | 腾讯 K线 → 东方财富 → Baostock + 本地计算 | 最重 | 所有均线/RSI/MACD/BOLL/交叉/动量/ATR/量比 |

核心流程：`classify_conditions() → L1过滤 → L2获取+过滤 → L3获取+过滤 → L4并行计算+过滤 → 排序返回`

### 关键修复

- **PE/PB 计算**：从 AKShare 返回的 `eps`/`bvps` + 行情 `price` 现场计算（`pe = price/eps`, `pb = price/bvps`）
- **Baostock 兜底优化**：只在候选 < 100 时启用，避免全局锁串行化（大规模扫描时跳过 `dividend_yield`/`debt_ratio`/`market_cap`）
- **`ret_5d`/`ret_20d` 百分比化**：`factor_ret_5d() * 100` 转为百分比，与策略 YAML 值匹配
- **`avg_amount_20d` 加入 L4**：可独立触发 K 线获取
- **`compare_field` 检查**：`classify_conditions()` 同时检查 `field` 和 `compare_field`，归类到最高层
- **条件引擎日志**：`condition_engine.py` 新增 `logger.debug` 输出 None 字段和异常

### 前端改动

- 条件分类从 `{基础, 基本面, 技术指标, 因子}` → `{L1 股票列表, L2 实时行情, L3 基本面, L4 K线指标}`
- 条件行前加彩色层标签（L1 灰 / L2 蓝 / L3 绿 / L4 紫）

### 验证结果

| 测试 | 结果 |
|---|---|
| PE<30 (纯 L3) | ✅ 800→427, PE=3.23 真实值, 38s |
| 动量策略 (纯 L4) | ✅ 800→27, ret_20d=58.91%, 5s |
| avg_amount_20d 单独使用 | ✅ 800→109, 修复 Bug #2 |
| 价格区间 (L1+L2) | ✅ 800→356, 4s |

### 文件变更
- **重写**: `backend/routers/screener.py` (~200行: 四层字段集 + `classify_conditions()` + 四层 `condition_scan` + PE/PB 计算 + CONDITION_SCHEMA 更新)
- **修改**: `backend/services/condition_engine.py` (+10行: None 字段调试日志)
- **修改**: `frontend/src/app/screener/condition/page.tsx` (+15行: 四层标签 + L1-L4 彩色徽标)
- **新增**: `backend/.env` (开发环境变量)
- **修改**: `backend/config.py` (+3行: `load_dotenv()` 自动加载 .env)

---

## 2026-06-23 — AI 设置页重构 + Quant 交互优化 + 因子解读

### AI 设置页重构：功能→供应商映射表

**之前的问题：**
- 6 个供应商卡片 × 3 字段 = 18 个输入框，但所有功能只用一个默认供应商
- "小米"供应商 model/base_url 为空，选了必然失败
- 配置来源不透明（.env / 数据库 / 默认值）
- 6 个 AI 功能不能独立指定供应商

**新设计：**
- **功能→供应商映射表**：7 行（AI选股/复盘/对抗/对话/盯盘/日报/量化解读），每行独立选择供应商
- **动态供应商配置区**：只展开被表格引用的供应商，减少视觉噪音
- **配置来源标签**：每个供应商显示 `.env` / `已保存` / `默认` / `未配置`
- **连通测试**：`POST /api/settings/ai-test` 端点，前端每行都有测试按钮
- **删除"小米"**：合并到"自定义 OpenAI 兼容"

**后端改动：**
- `ai_service.py`：新增 `get_provider_for_function(function_key)` → 读取 `function_providers` 映射
- `ai_chat()` 新增 `function` 参数：`function="screener"` → 自动查映射表找供应商
- 12 个 AI 调用点全部传入 `function` 参数（screener/review/duel/chat/watchdog/kol/explain）
- 不配置 `function_providers` 时回退到 `get_default_provider()`，向后兼容

### Quant 页面交互优化

- 添加统一「查询」按钮：根据当前 tab 自动分发（个股透视→K线 / 因子分析→因子面板 / 回测→回测 / MC→模拟）
- 快速选择器（▼下拉）改为只填入代码，不自动查询
- Enter 键改为调用 `handleQuery()`，统一分发
- 因子分析空状态删除冗余的"查看因子"按钮，引导使用上方统一查询

### AI 因子解读

- 新增 `POST /api/quant/factor-explain` 端点
- 因子面板加载后出现「AI 因子解读」按钮
- AI 分析 10 类因子的优势维度（得分最高）和风险维度（得分最低）
- 生成结构化报告：优势/风险/综合评估/操作建议

### 根治 Turbopack "Object is disposed" 错误

- `proxy.ts` → `middleware.ts`（Next.js 标准命名，消除模块歧义）
- 函数 `proxy` → `middleware`
- 新增 `predev` 脚本：每次 `npm run dev` 自动清除 `.next/dev` 缓存

### Bug 修复

- **设置保存后丢失**：前端发送数据与后端 `MultiAiConfigBody` 结构不匹配（缺 `configs` 包装），修复 `{ configs }` 包装
- **掩码覆盖真实 Key**：GET 返回掩码 `sk-a****b3` → 保存时检查是否含 `****`，掩码不发送，保护真实 Key

### 文件变更
- 修改：`backend/services/ai_service.py` (+27行 get_provider_for_function + function参数)
- 修改：`backend/routers/settings.py` (+63行 测试端点 + env_keys + function_providers)
- 修改：`backend/routers/quant.py` (+106行 factor-explain端点)
- 修改：`frontend/src/app/settings/page.tsx` (完全重构，18框→7行表格)
- 修改：`frontend/src/app/quant/page.tsx` (+137行 查询按钮 + 因子解读)
- 删除：`frontend/src/proxy.ts`
- 新增：`frontend/src/middleware.ts`
- 后端 9 个调用点：各 +1 行 `function=` 参数

---

## 2026-06-22（续）— `/quant` 页面 10 问规划 + 全面改版

### Q1-Q10 量化页改版决策

| Q | 决策 | 状态 | 内容 |
|---|------|:---:|------|
| Q1 | A 升级蜡烛图 | ✅ 已实现 | recharts 折线图 → lightweight-charts 蜡烛图 + MA5/10/20 |
| Q2 | A 全面海龟 | ✅ 已实现 | 通道线叠加到K线图 + 评分卡片 + ATR/止损/仓位 |
| Q3 | B 不对比 | 不做 | 单只深度分析 |
| Q4 | A AI 底部 | ⬜ 未验证 | AI 解读卡片（技术面+基本面+风险）—— 需配 AI Key |
| Q5 | C 保持现状 | 不做 | 因子面板不动，优先激活 pending 因子 |
| Q6 | A 海龟回测 | 🔲 待实现 | 海龟S1/S2 加入策略对比 |
| Q7 | B 手动触发 | 不做 | 不自动刷新 |
| Q8 | A 提醒面板 | ⬜ 未验证 | 底部「我的提醒」列表+删除 —— 需进入页面确认 |
| Q9 | C 快速选择 | ⬜ 未验证 | 持仓/自选/海龟Top10 下拉选择器 —— 需前端确认 |
| Q10 | C 不考虑 | 不做 | 移动端不优化 |

### Q1 实现 — K线图表升级
- 后端: `stock-insight` +MA5/MA10/MA20 数组
- 前端: `KlineChart` 替换 `AreaChart`, 5 指标切换按钮 (VOL/BOLL/MACD/RSI/KDJ), 技术指标摘要 6 列精简

### Q2 实现 — 海龟全面集成
- 后端: `stock-insight` +`_calc_turtle()` (S1/S2通道 + 突破检测 + ATR + 0-100评分)
- KlineChart: `TurtleOverlay` prop → `createPriceLine` 画 4 条水平线 (S1入红虚线/S2入橙虚线/S1出绿点线/S2出绿点线)
- 前端: 海龟评分卡 + S1/S2入场价+触发标记🔥 + ATR(N)/止损2N/仓位股数

### Q4 实现 — AI 量化解读
- 后端: explain prompt 补海龟数据, 链路: `ai_chat()` → `get_default_provider()` → settings表Key
- 前端: 「AI 解读」按钮 + 紫色左边框卡片 (技术面/基本面/风险三栏)

### Q8 实现 — 提醒面板
- 数据: `GET /api/stocks/alerts`
- 前端: Tabs 下方橙色边框卡片, 3列网格, 触发检测(红色高亮), 删除按钮

### Q9 实现 — 快速选择器
- 数据: `GET /api/stocks/holdings` + `GET /api/stocks/watchlist` (挂载时拉取)
- UI: ▼按钮 → 下拉三组 (持仓/自选/海龟Top10) → 点击自动填入代码+触发查询

### 版本
- `config.py`: VERSION "3.2" → **"3.4"**

### 文件变更
- 修改: `backend/routers/quant.py` (+200行 MA数组+turtle计算+AI prompt增强)
- 修改: `frontend/src/components/KlineChart.tsx` (+60行 TurtleOverlay prop+priceLine)
- 修改: `frontend/src/app/quant/page.tsx` (+300行 KlineChart+海龟卡+AI解读+提醒+选择器)
- 修改: `backend/config.py` (VERSION→3.4)
- 新增: `reports/turtle_screener.py`, `analyze_top3.py`, `turtle_screen_*.json`

### ⚠️ 未验证
- [ ] Q4: AI 解读 — 需配 AI Key 后实际调用
- [ ] Q8: 提醒面板 — 需前端页面确认 UI
- [ ] Q9: 快速选择器 — 需前端页面确认交互
- [ ] Q1/Q2: K线+海龟通道线 — 需浏览器实际渲染验证

### 已知待修
- `page.tsx:259` — TS2352 类型错误 (已有)
- 端口 3000 僵尸进程
- AI 依赖 settings 表 Key 配置

---

## 2026-06-22 — 海龟交易法选股 + 因子分析面板

### 海龟交易法 × 多因子综合选股
- **turtle_screener.py** — 全新海龟交易法选股脚本，组合三大维度：
  - 海龟通道：S1(20日突破)/S2(55日突破)入场 + S1(10日低)/S2(20日低)出场
  - ATR(N) 波动率归一化仓位计算 + 2N 止损
  - 29 因子体系打分（动量/波动率/量价/情绪/估值）
  - 综合评分：海龟 60% + 因子 40%
- **筛选漏斗**：4955 只 A 股 → 2964 只(价<20+市值>5亿) → 400 只深度分析 → Top50
- **数据源**：Baostock(股票列表) + 腾讯财经(实时行情/K线)，绕过系统代理
- **Top3 标的**：楚江新材(78.0) / 皖维高新(76.6) / 汤臣倍健(72.2)
- 结果保存至 `reports/turtle_screen_20260622_*.json`

### 量化页「因子分析」面板
- **后端**: `GET /api/quant/factor-panel/{code}` — 返回 7 大类 59 因子的完整评分
  - 计算全部 29 个 done 因子 + 基于 A 股合理阈值 0-100 打分
  - 按分类汇总：价格/成交量/技术指标/动量/波动率/量价/基本面/情绪/资金/社交
- **前端**: 量化页新增第 5 个 Tab「因子分析」
  - 综合评分卡片（紫色左边框 + 渐变进度条）
  - 7 维因子雷达条（横向进度条 × 10 类因子）
  - 因子详情网格（2 列 × 每类因子独立打分条 + 原始值）
  - 颜色编码：绿(≥60) / 橙(40-59) / 红(<40)
  - ↑↓ 标记因子方向（正向/负向）

### 自选股 + 海龟提醒
- 楚江新材/皖维高新/汤臣倍健 加入自选股 (`watchlist` 表)
- 6 条海龟入场提醒 (`price_alerts` 表, `alert_type=turtle_s1_entry/turtle_s2_entry`)
- 提醒阈值：楚江 16.19 / 皖维 9.02 / 汤臣 10.60(S1) + 10.88(S2)

### 数据源调试踩坑
- 腾讯批量行情接口 `qt.gtimg.cn/q=` 盘前返回 volume=amount=0 → 改用市值过滤
- 腾讯市值单位为亿元 → `mcap < 5`（非 `5e8`）
- Windows 系统代理导致 akshare 无法直连东方财富 → `ProxyHandler({})` 全局禁用
- Baostock 字段偏移：`row[4]=type, row[5]=status`（非 `row[3]=type`）

### 文件变更
- 新增：`reports/turtle_screener.py` — 海龟选股脚本
- 新增：`reports/analyze_top3.py` — Top3 深度技术分析脚本
- 新增：`reports/turtle_screen_20260622_092733.json` — Top50 结果
- 修改：`backend/routers/quant.py` — +60 行 `/factor-panel/{code}` 端点
- 修改：`frontend/src/app/quant/page.tsx` — +130 行「因子分析」Tab
- 修改：`frontend/package.json` 无变更、依赖不变

---

## 2026-06-21（续）— 开源项目缝合 + K 线多面板升级

### 量化框架缝合 (4/4)
- **qlib_factor_platform** → `factor_utils.py` (20个工具函数) + `factor_service.py` 59因子注册表 + `screener.py` 3个API (因子注册表/模板/校验)
- **moonshot** → `monthly_backtest.py` (470行) + `POST /api/quant/monthly-backtest` 端点
- **QuantLessMoneyMore** → `StrategyConfig` + 多权重方案(等权/市值/评分) + 仓位限制
- **multi-factor-stock-selection** → 因子退场机制 `track_factor_performance()` + `POST /api/screener/factor-retirement`

### K 线多面板升级
- `KlineChart.tsx` 重写 (280行): 6个指标前端计算 + 多面板 (价格/MACD/RSI/KDJ/成交量)
- `stock-chart-drawer.tsx` 重写: 5个指标切换按钮 (VOL/BOLL/MACD/RSI/KDJ)
- 用户可自由组合显示哪些指标面板

### 已知问题 (TODO)
- K 线多面板: 指标切换后高度计算偶有抖动，待排查 ResizeObserver 时序
- 布林带与 MA20 颜色重叠，需区分色系
- **后端因子功能无前端 UI**: 因子注册表/模板/校验/月度回测/因子退场 5 个 API 已完成，但前端页面未接入

---

## 2026-05-20 ~ 06-10 — MVP 搭建（原始项目）

### 项目启动
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

### 产品方向确定 (2026-05-30)
- 定位: A 股持仓追踪 + AI 分析助手 → AI 投资教练
- 新增 `review_service.py` 复盘引擎
- 新增 `review_reports` 表
- 确立 pytest 测试框架 (T1)
- 确立 Playwright E2E 测试 (T2)
- 确立 Docker 化部署 (T3)
- 确立 GitHub Actions CI/CD (T4)

---

## 2026-06-12 — Next.js + shadcn/ui 前端重构

### 技术栈升级
- Vanilla JS/HTML/CSS → `npx create-next-app@latest` (Next.js 16 App Router)
- `npx shadcn@latest init` 初始化 shadcn/ui (oklch 暗色主题)
- 配置 Tailwind CSS 4, `--radius: 0` 直角风格
- `next.config.ts` 添加 `/api/*` → `localhost:3000` 代理
- 旧 HTML/JS 前端删除，`frontend-next/` 正式上位 → `frontend/`

### 页面实现 (12 页)
- 侧边栏: 3 组折叠导航 (投资/分析/工具), 12 项中文导航
- 首页 `/`: KPI 卡片 + recharts 走势图 + DataTable + 骨架屏
- 大盘指数 `/market`: 全球 15 指数, 30s 刷新
- 自选股 `/watchlist`: 添加(500ms防抖查询)/删除/行情/加入持仓
- 交易记录 `/transactions`: CRUD + 5 KPI + AI 复盘
- 全球资讯 `/global-news`: SVG 世界地图(16金融城市) + 新闻
- AI 复盘 `/review`: KPI + 维度分析 + 改进建议 + 历史报告
- 量化分析 `/quant`: 4 Tab(个股透视/组合风险/回测/蒙特卡洛)
- AI 选股 `/screener`: 多因子扫描 + AI 精选
- 大佬观点 `/kol`: 雪球热门 + RSS + AI 日报
- AI 对话 `/ai-assistant`: Agent 选择 + 5 快捷指令 + conversationId
- AI 对抗 `/duel`: 6 AI 人格各 ¥10 万选股对战
- Agent 工坊 `/skills`: Agent CRUD + 记忆面板
- 设置 `/settings`: 6 供应商 Key + SMTP + 佣金
- 登录 `/login`: 邮箱+密码 → JWT → localStorage

### 架构变更
- 后端去掉 StaticFiles 挂载 → 纯 API 服务器 (端口 3000)
- `start.bat` 升级为双服务器控制面板

---

## 2026-06-12 ~ 06-13 — Bug 修复 + 功能增强

### Bug 修复 (15 个)
- 自选股: 现价小数位 (fund→4, etf→3, stock→2)、行情字段映射 (price vs change)、添加后数据覆盖、沪市 ETF 符号映射 (4个)
- 交易记录: `trade_date` vs `traded_at` 字段名不匹配 (1个)
- 量化分析: ETF 假数据、技术指标 undefined、组合风险全 "--"、Beta 始终 None、回测字段名、蒙特卡洛字段名、KPI 百分比 (7个)
- AI 选股: 扫描无结果、页面崩溃、名称/行业空 (3个)

### 新功能
- 持仓行业分布饼图 (`sector-pie-chart.tsx`, 暗色友好 12 色调色板)
- 手续费追踪: `calc_fee()` + `FeeConfig` + 设置页 UI + 一键重算
- 总资产走势图真实数据 (两条线: 成本灰虚线 + 市值红实线)
- KOL 代理支持
- Quant 页 `useSearchParams()` → `Suspense` 修复 `next build` 崩溃
- AI 对抗 demo 数据清理

---

## 2026-06-13 — 选股系统重大优化

### 死因子修复
- `eps_growth` 复活: Baostock 去年同期 EPS 真实增长率
- `dividend_yield` 复活: `bs.query_dividend_data()` 每股分红
- ROE 修复: Q4→Q3→Q2→Q1 逐季回退，季报自动年化
- PB 从真实值替代反推: K 线 `pbMRQ` 字段代替 PE×ROE 估算
- 因子状态: 21-22/25 → 23-25/25 有效，0 个死因子

### IC 权重从手工改为数据驱动
- 旧: 看大盘涨跌手工调权重
- 新: 截面 Spearman 秩相关，每个因子 Z-score 与 ret_20d 算秩 IC

### 并发性能优化
- 5 只股票: 141s → 6.7s (21 倍加速)
- K 线 fetch 改序: akshare→东财→Baostock (HTTP 源天然并发)
- 基本面: akshare HTTP 并发优先，失败回退 Baostock
- 行业分类全局缓存

### 社交因子 + 通知 + KOL
- 社交情绪因子: 25 → 28 个 (雪球关注数+微博情绪)
- 通知推送: 企业微信 Webhook + Telegram Bot + SMTP 邮件
- 大佬观点页: 雪球热门 + 财经 RSS + AI 摘要
- 前端 AI 选股页: 股票池选择器 (快速30/标准500/全市场)

---

## 2026-06-14 — P0 安全修复 + 多 Agent 选股 + SWR 缓存

### P0 安全 (7/7)
- S01-S04: JWT_SECRET/ADMIN_PASSWORD/CORS/EASTMONEY_TOKEN 强制校验
- S05: AI Key + SMTP 密码 AES-256-GCM 加密存储 (`crypto_service.py`)
- S06: 全局限流 slowapi (AI 20/min, 通用 60/min)
- S07: JWT 有效期 7天 → 2小时

### 多 Agent 交叉验证选股
- `services/multi_agent_service.py`: 5 个 AI 投资人格并行分析
- 聚合逻辑: 投票制(≥3/5 通过) + 加权评分 + 风险否决
- 前端新增 "5 Agent 验证" 按钮

### 多市场 + SWR
- 港股+美股行情支持 (akshare_adapter 新增 6 个函数)
- 前端 SWR 缓存层: 5 个共享 hooks (usePortfolio/useMarket/useReview/useWatchlist/useDiversification)
- 因子体系: 25→29 (新增资金类 3 因子: north_flow/margin_change/inst_change)
- AI 对抗支持多供应商对战

### 第三方审计 + ROADMAP
- 解读 7 份审计报告 (架构/代码/安全/市场/面试/项目管理/基础设施)
- 产出 `docs/ROADMAP.md` (P0-P1-P2 + 长期架构 + 产品演进)

---

## 2026-06-17 — 持仓删除 + 盈亏对齐同花顺

### Bug 修复
- Next.js API 代理端口错误 (3002→3000)
- 持仓删除功能 (AlertDialog 确认 → DELETE API → SWR 乐观更新)
- 盈亏对齐同花顺口径: 预估卖出费 + PnL/总成本×100%
- 验证: 彩虹股份 400 股，StockAI ¥308.37 vs 同花顺 ¥308.18 (差 ¥0.19)

---

## 2026-06-18 — K 线图表升级 (lightweight-charts)

### recharts → TradingView lightweight-charts v5.2
- 新增 `KlineChart.tsx`: CandlestickSeries + HistogramSeries + LineSeries ×3 (MA5/10/20)
- 删除 60+ 行废弃 recharts 代码
- 根因修复: shadcn Drawer hidden 状态下 ResponsiveContainer 返回 -1 导致初始化失败
- 新增 `stock-chart-drawer.tsx`: 右侧滑出面板 (5日/日K/周K/月K)

---

## 2026-06-21 — P1 工程规范批量修复 (10/10) + 开源缝合准备

### 工程质量批量修复
- P02: 22 个数据库索引 (零全表扫描)
- S08: 7 项安全响应头 (HSTS/CSP/X-Frame-Options 等)
- U05: subprocess curl → httpx (utils.py)
- U07: passlib → bcrypt 直接调用 (database.py + auth.py)
- P07: random.seed(42) → random.Random 独立实例 (quant_service.py)
- P10: 后端+前端依赖版本全部锁定
- T01: Next.js Proxy 统一认证守卫 (12 页删除 useEffect 重复代码)
- P08: 71 处裸 except:pass 全部消除 (9 个 services 文件 + scheduler.py)
- T03: 16 处前端 any 类型全部替换为明确类型
- P06: O(n²) → O(n) 性能修复 (500 只 8.9ms→0.1ms, 75x)

### 开源缝合准备
- 创建 `D:\some-oss\` 素材库目录
- 下载 11 个开源项目 (量化框架 4+TradingView 4+Pine Script 3)
- 制定 13 项融合任务 (F01-F13)

### 文档整合
- 旧文档 (TODOS/PROJECT_PLAN/ai-investment-coach) → 吸收到 CHANGELOG
- `docs/ROADMAP.md` 更新: 合并融合计划 + 标注已完成项
- 新增 `docs/ARCHIVE.md` 归档说明

---

> 版本演进: v3.0 (AI选股+对抗) → v3.1 (社交因子+通知) → v3.2 (K线+SWR) → v3.3 (P1工程收债+融合准备)

### 开源项目缝合准备
- 创建 `D:\some-oss\` 缝合素材库目录
- 下载 11 个开源项目：
  - 量化框架 (4): qlib_factor_platform, moonshot, QuantLessMoneyMore, multi-factor-stock-selection
  - TradingView/图表 (4): lightweight-charts(官方), lightweight-charts-python(30+指标), streamlit-lightweight-charts-v5, KLineChart
  - Pine Script (3): pinescript(QuanTAlib), pine-script-libraries, tradingview-pinescript-lab
- 1 个不可用: python-lightweight-charts (repo 404)
- 新增 `reports/stockai-status-2026-06-21.txt` — 以项目融合为核心的完整状态报告

### 数据库

**数据库索引 (P02)**
- `backend/database.py` `init_db()` 新增 22 个索引
- 覆盖: holdings / transactions / watchlist / ai_messages / price_alerts / review_reports / screener_* / backtest_results / dca_plans / dividends / ai_duel_* / kol_*
- 验证: 11/11 核心查询全部 USING INDEX，零全表扫描

### 安全

**安全响应头 (S08)**
- `backend/main.py` 新增 `security_headers_middleware`
- 7 项头: HSTS / X-Content-Type-Options / X-Frame-Options / X-XSS-Protection / Referrer-Policy / Permissions-Policy / Content-Security-Policy
- 验证: 200/401/API Docs 三种场景全部返回安全头

### 工程质量

**curl → httpx (U05)**
- `backend/services/utils.py` `run_curl()` 从 `subprocess.run(curl)` 重写为 `httpx.get()`
- 新增 `run_curl_async()` 异步版本供未来使用
- 验证: 全球指数 + 基金净值 + 新闻搜索 + K线 全部正常

**passlib → bcrypt (U07)**
- `backend/database.py` + `backend/routers/auth.py` 两处替换
- `bcrypt.verify()` → `_bcrypt.checkpw()` / `bcrypt.hash()` → `_bcrypt.hashpw()`
- `requirements.txt` 删除 `passlib[bcrypt]>=1.7`
- 验证: passlib 已卸载，登录/错误密码 全部正常

**random.seed(42) → Random 实例 (P07)**
- `backend/services/quant_service.py:503` 修复
- `random.seed(42)` (污染全局) → `rng = random.Random(); rng.seed()` (独立实例)
- 验证: 5 次模拟结果各不相同，测试 3/3 通过

**依赖版本锁定 (P10)**
- `backend/requirements.txt`: 14 个 `>=` → `==`，新增 `requests==2.32.2` + `feedparser==6.0.12`
- `frontend/package.json`: 28 个 `^` → 精确版本
- 验证: pip install --dry-run 全部满足，npm ls 无错误

**统一认证守卫 (T01)**
- 新建 `frontend/src/proxy.ts` (Next.js 16 proxy 中间件)
- cookie 检查 → 无 token 重定向 /login → 有 token 放行
- 12 个页面删除 `useEffect + isAuthenticated()` 重复代码 (~30 行)
- `frontend/src/lib/auth.ts` `setAuth()`/`clearAuth()` 同步写 cookie
- 验证: 307/200 三种路由场景正确，next build 通过

**消除裸 except pass (P08)**
- 两轮修复: 18 个文件 / 71 处
- 全部替换为 `logger.warning()` 或 `logger.debug()` + 上下文消息
- `parse_ai_json()` 的 `json.JSONDecodeError: pass` 添加注释说明降级意图
- 验证: `grep` 零残留，132/133 测试通过

**前端 any 类型消除 (T03)**
- 5 个页面: page.tsx / duel / screener / settings / quant
- 16 处 `any` 全部替换为明确类型 + 3 个新 interface
- 删除 2 条 eslint-disable 注释
- 验证: `grep` 零残留，`next build` Compiled successfully

**O(n²) 性能 Bug (P06)**
- `backend/services/screener_service.py:510`
- `stock_name_map` 从循环内移到循环外一次性构建
- 验证: 500 只股票打分 8.9ms → 0.1ms (75x 加速)

### 项目更新
- 新增 `D:\stocks\reports\stockai-status-2026-06-21.txt` — 完整项目状态报告
- 新增 `D:\some-oss\README.txt` — 开源缝合素材库目录说明

---

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
