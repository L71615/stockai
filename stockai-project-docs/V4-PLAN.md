# StockAI v4.x — 第四次大更新计划 + 后 v4 演进

> **当前版本: v4.1.1 patch3**(2026-08-01 发布)
> **已关闭**: v4.0 + v4.1 完整交付 + v4.1 测试套件 168/168 全过
> **下一阶段**: v4.2 (候选 Auto Champion) → **v5.0 准实盘量化交易系统**(战略已锁定,详见 `2026-08-01-v5.0-strategy.md`)

---

## 🎯 战略方向(D1-D4 全部敲定 ✅)

| # | 决策 | 内容 |
|---|------|------|
| **D1** | 战略方向 | 🧠 AI 深度 + 📊 因子回测 + 🔁 决策闭环(三方向并行) |
| **D2** | **主线能力** | **🧠 AI 选股智能化**(5→8 角色辩论 + Agent 调函数 + 推理增强) |
| **D3** | 形态入口 | **🖥️ 保持桌面 Web 不动**(不扩展 PWA / Tauri / 移动 app) |
| **D4** | 交付场景 | **🎯 T+1/T+2 短线预测**(前一晚收盘→次日开盘买入→第三日卖) |

### ⚠️ 核心红线(继承 + 加固)

- **预测 + 回测**,**不做实时量化**
  - 典型场景:T+1/T+2 短线预测 OR 周月大方向预测
  - **明确不做**:盘中 tick 级自动交易、券商对接、低延迟设计
- **白盒可解释**:因子表达式 / 特征重要性可见,不迷信黑盒
- **桌面 Web 不动**:v4.x 改动限定在**后端 + AI 逻辑**,不重构前端架构

---

## ✅ v4.0(2026-07-27)— Phase 1-4 全部完成

### Phase 1 — 主线 MVP ✅
- [x] **A1** 多 Agent 5→8 角色(做空研究员 / 政策解读员 / 资金面分析师)
- [x] **A2** Agent 工具调用框架(`get_quote` / `get_factor` / `run_backtest` / `calc_t1_cost`)
- [x] **B4** 滑点模型(默认 0.1% × 金额,可配)
- [x] **C2** T+1 成本计算器(卖费 + 持仓风险溢价 + 滑点)
- [x] **T+1/T+2 预测场景**(整合 A1/A2/B4/C2)

### Phase 2 — 因子体系升级 ✅
- [x] **B1** Alpha158 Batch 1 (价量类)
- [x] **B5** 冲击成本模型(基于 ADV 比例 + `as_of_date` 隔离未来数据)
- [x] 因子 IC 重新校准

### Phase 3 — 闭环可视化 ✅
- [x] **C1** 反事实报告可视化
- [x] **A3** 推理增强(CoT + ReAct)
- [x] **B6** 多策略组合回测(union / intersect / majority)

### Phase 4 — Alpha158 完整 + 个性化 ✅
- [x] **B2** Batch 2 (动量/波动)
- [x] **B3** Batch 3 (技术/资金流)
- [x] **A4** 个性化 prompt

### Phase 5 — v4.0 发布 ✅
- [x] v4.0 tag
- [x] README 三件套同步
- [x] CHANGELOG 完整 entry
- [x] GitHub release notes
- [x] RUNBOOK 更新

---

## ✅ v4.1(2026-07-30)— 决策闭环 + 真实基准 + 漂移监控

### Phase 1A — 决策闭环 ✅
- 1A.1 scheduler t1_watcher 注册
- 1A.2 pipeline pool 5→15 守护
- 1A.3 inbox accept → pending_buy + source 字段
- 1A.4 反事实自动跟跑 — `run_retrospective_writer`
- 1A.5 holdings vs shadow portfolio 对比卡

### Phase 1B — 审批稳健性 ✅
- 1B.1 watcher 推送通知
- 1B.2 shadow 净值曲线图
- 1B.3 bulk-approve 单事务 + 三层版本乐观锁 + 0.85 boundary
- 1B.4 holdings vs shadow portfolio 对比卡

### Phase 2A — 真实基准 ✅
- 6 默认指数 K 线同步(沪深300/中证500/创业板/上证50/中证1000/科创50)
- 11 默认 ETF K 线同步
- `_get_benchmark_curve` 4 段 fallback(真实指数 → ETF → 历史代理 → 全市场等权)
- `index_kline` / `etf_kline` 表 + `base_vendor_sync` 模板方法

### Phase 2B — Drift PSI/KL 监控 ✅
- `drift_policies` 版本化阈值(policy_version + effective_from/to)
- `drift_monitor` orchestrator,`experiment_runs.status='done'` gate
- `_historical_metric_mean()` 填 baseline_value
- 严重级别通知

### v4.0 outside voice 5 项修复 ✅
- init_db ALTER 顺序 (decision_score 在 CREATE INDEX 前)
- watcher 事务原子性 (`execute_transaction` 单事务)
- pipeline_lock 跨进程 race
- 09:30 race (09:30→09:35 + first-tick ±20% 校验)
- admin lookup (不再硬编码 id=1)

---

## 🆕 v4.1.1 patch(2026-07-30)

### OSS port — quant-trading-system 学习成果
- **factor_rsrs** — 阻力支撑相对强度(18 日 OLS beta z-score)
- **risk_sizing.py** — 4 种仓位算法(FixedFraction / Kelly / RiskParity / VolTarget)
- **risk_guard.py** — 4 规则风控(max_drawdown / daily_loss / single_position / total_exposure)
- **strategy_registry.py** — YAML 策略自动注册中心(单例 + mtime 失效 + validate)

### Bug fixes
- **`_calc_impact_cost_bps` 移除未来数据泄漏** — 加 `as_of_date: str` 必需 kw 参数
- **t1_watcher `_evaluate_buy_risk`** — 风控拦截器接入
- **策略加载路径与 registry 一致** — 3 处统一走 `registry.strategies_dir`

### 数据
- dev DB 5 年一次性 seed — `index_kline` 1250 行 × 6 指数

---

## 🔒 v4.2 候选(已被证据门槛挡住)

见 `TODOS.md`:

| 候选 | 状态 | 阻塞门槛 |
|------|------|----------|
| Full order/fill simulation | P2/L | shadow ledger 稳定 + A 股成交 fixtures + D7 typed errors |
| Auto Champion replacement | P2/M | **需多个 regime transition 后才允许** — 严禁先做 |
| Cross-market validation | P3/L | 至少 1 个 Champion 之后再启动 |
| Online learning | P3/XL | **严禁先做** — 漂移检测稳定 + 回滚演练 |

### 活跃 v4.1.1 patch2(2026-07-31)
- 策略加载路径与 registry 一致
- dev DB 5 年一次性 seed
- 详见 CHANGELOG

---

## 🚥 当前状态(2026-07-31)

- [x] v4.0 完整发布 ✅
- [x] v4.1 完整发布 ✅
- [x] v4.1.1 patch 发布 ✅
- [x] v4.1.1 patch2(路径一致 + dev DB seed) ✅
- [ ] v4.2(等证据门槛达标)

**测试覆盖**: 53+ 通过(Phase 2A 21 + Phase 2B 9 + 既有 21+)
**Commits**: 16+ commits(v4.1 11 + v4.1.1 patch 3 + patch2 1)

---

## 📁 文件位置约定

```
stocks/
├── backend/                 # v4.x 主战场(服务在 services/)
├── frontend/                # 仅 UI 微调
├── tests/                   # 回归测试
├── monitor-desktop/         # 监视器独立,不动
├── stockai-project-docs/
│   ├── V4-PLAN.md           ← 本文件
│   ├── CHANGELOG.md         # 每次 patch 一段 entry
│   ├── TODOS.md             # 证据门槛挡住的候选
│   ├── DESIGN.md            # 设计系统(暗色 / Tabler / rounded-none)
│   └── ...
└── README.md / INDEX.md     # 同步入口
```