# StockAI 路线图

> 更新: 2026-07-01 | 版本: v3.6 | 测试: 81/83

---

## 一、当前状态

| 维度 | 状态 |
|------|------|
| P0 安全红线 | ✅ 全部完成 (7/7) |
| P1 工程质量 | ✅ 全部完成 (10/10) |
| P2 用户体验 | 🟡 87.5% (7/8 — U04 未完成) |
| 开源融合 | 🟡 23% (3/13 — F08/F13 + 因子体系 done) |

---

## 二、已完成 (2026-05 ~ 2026-06-21)

| 日期 | 里程碑 |
|------|--------|
| 05-20 ~ 06-10 | MVP: FastAPI+SQLite+Vanilla JS 12页，AI对话，量化引擎 |
| 06-12 | Next.js 16+shadcn/ui 12页重构，暗色主题直角风格 |
| 06-12~13 | 15 个 Bug 修复 + 手续费追踪 + 行业饼图 + IC 权重数据驱动 |
| 06-14 | P0 安全 7/7 + 29 因子 + 5-Agent 交叉验证 + SWR 缓存 |
| 06-17 | 持仓删除 + 盈亏对齐同花顺 |
| 06-18 | lightweight-charts v5.2 蜡烛图 + MA5/10/20 |
| 06-21 | P1 工程 10/10: 22索引+7安全头+httpx+bcrypt+Random+依赖锁定+Proxy认证+71except+16any+O(n²) |
| 06-22 | 海龟选股引擎 + 量化页因子面板 + 自选股+海龟提醒 |
| 06-23 | AI设置页重构(功能→供应商映射表) + Quant交互优化 + 因子AI解读 + disposed错误根治 |
| 06-24 | AI SSE流式响应 + 前端认证中间件 + K线BOLL/MACD/RSI/KDJ + Quant页KlineChart + 条件选股页 |
| 07-01 | **v3.6**: P1 工程 100% + P2 体验 87.5% — 认证解耦(ContextVar JWT) + AI异常体系(5级) + K线crosshair/成交量 + 连接池(busy_timeout) + data-table拆分 + 全局异常处理 |

---

## 三、开源融合计划（当前重点）

### 第一优先级 — 指标引擎升级
- [ ] **F01**: 30+ 技术指标移植 (lightweight-charts-python → technical.py)
- [ ] **F02**: Volume Profile 成交量分布 (→ KlineChart 右侧子面板)
- [ ] **F03**: KlineChart 多窗格升级 (价格+1~3 指标子窗格)

### 第二优先级 — 因子研究升级
- [ ] **F04**: IC 分析面板 (→ screener 页面新增 IC tab)
- [x] **F05**: Alpha158 因子体系 ✅ 57/111 因子 (10大类, 54个规划中) — `factor_service.py`

### 第三优先级 — 策略回测升级
- [ ] **F06**: 风险平价策略 (→ compare_strategies 第5策略)
- [ ] **F07**: 策略 YAML 配置 (用户自定义策略参数)

### 第四优先级 — 因子淘汰 & 检验
- [x] **F08**: IC/ICIR 因子淘汰 (自动淘汰低效因子) ✅ `factor_service.py:1215 retire_factors_by_icir()`
- [ ] **F09**: Fama-MacBeth 回归 (因子有效性检验)

### 第五优先级 — 图表高级特性
- [ ] **F10**: Up/Down Markers K线标记
- [ ] **F11**: Watermark 品牌水印

### 第六优先级 — 指标翻译
- [ ] **F12**: Pine Script → Python 指标翻译 (QuanTAlib 算法参考)

### 第七优先级 — 架构参考
- [x] **F13**: 回测架构参考 (moonshot + vnpy + nautilus) ✅ `monthly_backtest.py` + `/api/quant/monthly-backtest`

---

## 四、剩余待办（非融合）

### P2 用户体验
- [x] **U01**: AI 对话 SSE 流式响应 ✅ `ai.py:/chat/stream` + 前端 `getReader()` 逐 token 渲染
- [x] **U02**: 拆分 data-table.tsx ✅ `data-table-core.tsx` + `data-table-cells.tsx` + `data-table-drawer.tsx` + barrel
- [x] **U03**: 全局错误处理中间件 ✅ `main.py` Exception handler + traceback 日志
- [ ] **U04**: 数据源健康检查 + Fallback 监控面板 (仅基础 `/api/health`)
- [x] **U05**: ✅ 已完成 (curl → httpx)
- [x] **U06**: get_db() 连接池 ✅ 5连接池 + `_PooledConnection` + `busy_timeout=5000`
- [x] **U07**: ✅ 已完成 (passlib → bcrypt)
- [x] **U08**: ✅ 已完成 (安全响应头 7/7)

### P1 工程规范
- [x] **P01**: 认证系统完善 ✅ ContextVar JWT 方案 — `dependencies.py` + 中间件 `_current_user_id.set()` — 24处硬编码已消除
- [x] **P02**: ✅ 已完成 (数据库索引)
- [ ] **P03**: 数据备份机制 (1-2d)
- [ ] **P04**: CI/CD GitHub Actions (2-3d)
- [x] **P05**: AI 异常处理重构 ✅ `ai_exceptions.py` 5级层次(AIServiceError→Key/Provider/RateLimit/Response/Config) — 10处 `"（...）"` 已消除
- [x] **P06**: ✅ 已完成 (O(n²) 性能)
- [x] **P07**: ✅ 已完成 (random.seed)
- [x] **P08**: ✅ 已完成 (裸 except pass)
- [x] **P09**: ✅ 已完成 (Baostock 全局锁→查询级细粒度锁, `_bs_locked()` 每次独立加解锁)
- [x] **P10**: ✅ 已完成 (依赖版本锁定)

### 技术债
- [x] **T01**: ✅ 已完成 (Proxy 认证守卫)
- [ ] **T02**: 前端全迁 SWR (2/11 页面, 18% — 其余 9 页仍用 fetch/useEffect, 3-5d)
- [x] **T03**: ✅ 已完成 (`: any` → `: unknown`, KlineChart.tsx 零 `:any` 残留)
- [ ] **T04**: Alembic 数据库迁移 (1d)
- [ ] **T05**: Playwright E2E 测试 (2-3d)

### K 线图表增强
- [x] **K01**: Bollinger Bands 叠加 ✅ `KlineChart.tsx:112 calcBollinger()`
- [x] **K02**: MACD 柱状图子面板 ✅ `KlineChart.tsx:132 calcMACD()`
- [x] **K03**: RSI 子面板 ✅ `KlineChart.tsx:153 calcRSI()`
- [x] **K04**: KDJ 子面板 ✅ `KlineChart.tsx:175 calcKDJ()`
- [x] **K05**: Quant 页改用 KlineChart ✅ `quant/page.tsx:452`
- [x] **K06**: OHLCV crosshair 数字标签 ✅ `CrosshairMode.Normal` + vertLine/hor Line labelVisible
- [x] **K07**: 成交量柱数字 ✅ 自定义 priceFormat formatter (万/亿显示)
- [ ] **K08**: Volume Profile (1d)
- [ ] **K09**: VWAP 叠加 (2h)
- [ ] **K10**: Supertrend (2h)
- [ ] **K11**: 分钟级 K 线数据源 (2d)
- [ ] **K12**: K 线实时轮询 SWR 3s (1h)

### 量化分析增强
- [ ] **Q01**: 行业轮动热力图 (2h)
- [ ] **Q02**: 资金流向仪表盘 (2h)
- [ ] **Q03**: 择时信号聚合 (1h)
- [x] **Q04**: AI 量化解读 ✅ `/api/quant/stock/{code}/explain` + `/api/quant/factor-explain`
- [x] **Q05**: 条件选股 ✅ `screener.py` 多因子扫描 + AI二次筛选 + 盯盘管理
- [ ] **Q06**: 回测参数优化器 (1d)

### 已识别 Bug
- [x] AI 异常被吞 → 字符串污染 ✅ P05 已修复 — `AIServiceError` 层次替代 `"（...）"` 字符串约定
- [x] Baostock 全局锁串行化 ✅ 已改为查询级细粒度锁 (`baostock_adapter.py`)
- [x] K 线 crosshair label 数字未显示 ✅ K06 已修复 — crosshair labelVisible
- [ ] 分钟级 K 线数据源未接入 (东财 klt=1/5/15/30/60) — K11
- [ ] **条件选股/AI选股筛选功能不可用** (2026-07-01 发现) — 待排查：数据源超时/并发锁/前端请求失败

---

## 五、优先级总览

```
P0 安全:    ██████████ 100% (7/7)
P1 工程:    ██████████ 100% (10/10) ✅
P2 体验:    ████████░░  87.5% (7/8 — U04 未完成)
融合 F01-F13: ███░░░░░░░  23% (F05/F08/F13 done, 其余待开始)
K 线:       █████░░░░░  58% (K01-K07 done, K08-K12 pending)
量化 Q:     ███░░░░░░░  33% (Q04-Q05 done, Q01-Q03/Q06 pending)
技术债:    ████░░░░░░  40% (T01/T03 done, T02 18%, T04/T05 未开始)
已识别 Bug: ████████░░  75% (3/4 fixed — 仅 K11 分钟K线未接入)
```

### 新增功能 (v3.4→v3.5，ROADMAP 外)
- AI 功能→供应商映射表 (settings页 435行, 7功能×5供应商独立配置)
- 前端 Next.js 认证中间件 (14页统一守卫, 无需各自 useEffect 检查)
- 海龟选股引擎 (`turtle_screener.py` + `run_analysis.py`, 4955→400→Top10)
- 月度因子分层回测 (`monthly_backtest.py`, moonshot 融合)
- 个股 AI 解读 (`/api/quant/stock/{code}/explain` 技术面+基本面+风险)
- 因子 AI 解读 (`/api/quant/factor-explain` 优势/风险/建议)

---

## 六、缝合素材库 (D:\some-oss\)

| 分类 | 项目 | 缝合目标 |
|------|------|----------|
| 量化 | qlib_factor_platform | IC面板/Alpha158因子 |
| 量化 | moonshot | 月度因子回测 |
| 量化 | QuantLessMoneyMore | 风险平价/YAML策略 |
| 量化 | multi-factor-stock-selection | IC/ICIR淘汰/Fama-MacBeth |
| 图表 | lightweight-charts (官方) | 插件示例 |
| 图表 | lightweight-charts-python | **30+指标** (主力源) |
| 图表 | streamlit-lightweight-charts-v5 | 多窗格布局 |
| 图表 | KLineChart | 指标TypeScript源码 |
| Pine | pinescript (QuanTAlib) | 数学严谨算法 |
| Pine | pine-script-libraries | 经典指标增强 |
| Pine | tradingview-pinescript-lab | 带教程指标集 |
