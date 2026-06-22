# StockAI 路线图

> 更新: 2026-06-22 | 版本: v3.4 | 测试: 132/133

---

## 一、当前状态

| 维度 | 状态 |
|------|------|
| P0 安全红线 | ✅ 全部完成 (7/7) |
| P1 工程质量 | ✅ 全部完成 (10/10) |
| P2 用户体验 | ⬜ 未开始 (8 项) |
| 开源融合 | ⬜ 11 个项目已下载，待缝合 |

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

---

## 三、开源融合计划（当前重点）

### 第一优先级 — 指标引擎升级
- [ ] **F01**: 30+ 技术指标移植 (lightweight-charts-python → technical.py)
- [ ] **F02**: Volume Profile 成交量分布 (→ KlineChart 右侧子面板)
- [ ] **F03**: KlineChart 多窗格升级 (价格+1~3 指标子窗格)

### 第二优先级 — 因子研究升级
- [ ] **F04**: IC 分析面板 (→ screener 页面新增 IC tab)
- [ ] **F05**: Alpha158 因子体系 (29 → 50+ 因子)

### 第三优先级 — 策略回测升级
- [ ] **F06**: 风险平价策略 (→ compare_strategies 第5策略)
- [ ] **F07**: 策略 YAML 配置 (用户自定义策略参数)

### 第四优先级 — 因子淘汰 & 检验
- [ ] **F08**: IC/ICIR 因子淘汰 (自动淘汰低效因子)
- [ ] **F09**: Fama-MacBeth 回归 (因子有效性检验)

### 第五优先级 — 图表高级特性
- [ ] **F10**: Up/Down Markers K线标记
- [ ] **F11**: Watermark 品牌水印

### 第六优先级 — 指标翻译
- [ ] **F12**: Pine Script → Python 指标翻译 (QuanTAlib 算法参考)

### 第七优先级 — 架构参考
- [ ] **F13**: 回测架构参考 (moonshot + vnpy + nautilus)

---

## 四、剩余待办（非融合）

### P2 用户体验
- [ ] **U01**: AI 对话 SSE 流式响应 (30s 等待 → 实时字符流)
- [ ] **U02**: 拆分 data-table.tsx (745 行 → 3 文件)
- [ ] **U03**: 全局错误处理中间件
- [ ] **U04**: 数据源健康检查 + Fallback 监控面板
- [ ] **U05**: ✅ 已完成 (curl → httpx)
- [ ] **U06**: get_db() 连接池 + PRAGMA busy_timeout
- [ ] **U07**: ✅ 已完成 (passlib → bcrypt)
- [ ] **U08**: ✅ 已完成 (安全响应头)

### P1 工程规范
- [ ] **P01**: 认证系统完善 (user_id 硬编码 → JWT 解析, 3-5d)
- [ ] **P02**: ✅ 已完成 (数据库索引)
- [ ] **P03**: 数据备份机制 (1-2d)
- [ ] **P04**: CI/CD GitHub Actions (2-3d)
- [ ] **P05**: AI 异常处理重构 → AIServiceError (1d)
- [ ] **P06**: ✅ 已完成 (O(n²) 性能)
- [ ] **P07**: ✅ 已完成 (random.seed)
- [ ] **P08**: ✅ 已完成 (裸 except pass)
- [ ] **P09**: Baostock 全局锁 → 细粒度锁 (1-2d)
- [ ] **P10**: ✅ 已完成 (依赖版本锁定)

### 技术债
- [ ] **T01**: ✅ 已完成 (Proxy 认证守卫)
- [ ] **T02**: 前端全迁 SWR (3-5d)
- [ ] **T03**: ✅ 已完成 (前端 any 类型)
- [ ] **T04**: Alembic 数据库迁移 (1d)
- [ ] **T05**: Playwright E2E 测试 (2-3d)

### K 线图表增强
- [ ] **K01**: Bollinger Bands 叠加 (2h)
- [ ] **K02**: MACD 柱状图子面板 (1h)
- [ ] **K03**: RSI 子面板 (1h)
- [ ] **K04**: KDJ 子面板 (1h)
- [ ] **K05**: Quant 页改用 KlineChart (1h)
- [ ] **K06**: OHLCV crosshair 数字标签 (1h)
- [ ] **K07**: 成交量柱数字 (0.5h)
- [ ] **K08**: Volume Profile (1d)
- [ ] **K09**: VWAP 叠加 (2h)
- [ ] **K10**: Supertrend (2h)
- [ ] **K11**: 分钟级 K 线数据源 (2d)
- [ ] **K12**: K 线实时轮询 SWR 3s (1h)

### 量化分析增强
- [ ] **Q01**: 行业轮动热力图 (2h)
- [ ] **Q02**: 资金流向仪表盘 (2h)
- [ ] **Q03**: 择时信号聚合 (1h)
- [ ] **Q04**: 条件选股 (1d)
- [ ] **Q05**: 回测参数优化器 (1d)
- [ ] **Q06**: 因子 IC 时序图 (2h)

### 已识别 Bug
- [ ] AI 异常被吞 → 字符串污染 (`ai_service.py`)
- [ ] Baostock 全局锁串行化 (`baostock_adapter.py`)
- [ ] K 线 crosshair label 数字未显示
- [ ] 分钟级 K 线数据源未接入 (东财 klt=1/5/15/30/60)

---

## 五、优先级总览

```
P0 安全:    ██████████ 100% (7/7)
P1 工程:    ██████████ 100% (10/10)
P2 体验:    █░░░░░░░░░  10% (1/8, U05/U07/U08 并入 P1)
融合 F01-F13: ░░░░░░░░░░   0% (准备就绪)
K 线 P1:    ░░░░░░░░░░   0%
量化 Q:     ░░░░░░░░░░   0%
```

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
