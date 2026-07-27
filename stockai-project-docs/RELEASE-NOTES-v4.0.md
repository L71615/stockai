# StockAI v4.0 — Release Notes

**Release Date**: 2026-07-28
**Tag**: `v4.0`
**Type**: Major Release (D1-D4 战略决策全部落地)

---

## 🎉 TL;DR

StockAI v4.0 是 v3.x 之后的**第四次大更新**,主线场景从"通用量化研究"升级为 **T+1/T+2 短线预测**,核心战略三方向:

- 🧠 **AI 深度**: 8 角色多 Agent 辩论 + CoT 推理链 + Agent 工具调用 + 个性化 prompt
- 📊 **因子回测**: 64 因子(29 经典 + 35 Alpha158) + 滑点/冲击成本 + 多策略组合 + IC 重新校准
- 🔁 **决策闭环**: T+1 模拟成交 watcher + 反事实报告可视化

---

## ✨ 新增能力(New Features)

### 🧠 A. AI 深度能力

- **A1 多 Agent 5→8 角色** — 新增**资金面分析师 / 政策解读员 / 做空研究员** 3 角色
  - 3 轮编排(round1×4 + round2×3 + judge)
  - 前端 2×4 卡片布局
- **A2 Agent 工具调用** — Claude tool_use + OpenAI function_calling 双协议
  - 4 个核心工具:`get_quote` / `get_factor` / `run_backtest` / `calc_t1_cost`
  - 5 轮调用循环,自动错误重试
- **A3 推理增强(CoT)** — 5 步显式推理
  - 关键信号 → 多空评估 → 风险 → 决策 → 信心
  - 前端 verdict 卡可折叠展示 reasoning_chain
- **A4 个性化 prompt** — 从交易历史推断用户风格
  - 自动计算:胜率 / 平均持仓天数 / 风险偏好 / 行业偏好
  - 注入到 8 个角色的 system prompt

### 📊 B. 因子与回测体系

- **B1 Alpha158 Batch 1(15 价量类)** — K线形态/变化率/偏离度/价格变异/自回归/量能/价量相关
- **B2 Alpha158 Batch 2(15 动量/波动类)** — 偏离度扩展/波动率扩展/自回归短周期/价量相关多周期/收益率自相关/VWAP
- **B3 Alpha158 Batch 3(5 技术/资金流类)** — 量比/OBV/K线中位2/振幅均值/量价配合信号
- **B4 滑点模型** — 默认 10bps(0.1%),买入加价/卖出减价/期末清仓 3 处
- **B5 冲击成本模型** — 基于 ADV 比例的平方根模型 `impact = base × sqrt(order_size/ADV)`,5x base 上限
- **B6 多策略组合回测** — 3 模式(union/intersect/majority)+ trade_attribution

### 🔁 C. 决策与执行闭环

- **C1 反事实报告可视化** — approved vs rejected 实际表现对比
  - 2 API 端点:`/api/pipeline/counterfactual` + `/api/pipeline/retrospectives`
  - 前端 `/pipeline` 反事实 Tab + 3 卡片对比 + 详情列表
  - **基于已有 `proposal_retrospectives` 表,无新表**
- **T+1/T+2 模拟成交 watcher** — 状态机 `pending_buy → bought → sold`
  - 新表 `t1_pending_orders`(4 索引)
  - `t1_watcher.process_pending_buys()` 09:30 模拟买入
  - `t1_watcher.process_pending_sells()` 持仓期满模拟卖出
  - 写 `holdings` + `transactions` + 收益统计

---

## 📁 文件变更

### 新增(11 文件)

- `backend/services/agent_tools.py` (258 行) — Agent 工具注册表
- `backend/services/t1_cost.py` (155 行) — T+1 成本计算器
- `backend/services/t1_watcher.py` (380 行) — T+1 模拟成交 watcher
- `backend/services/user_style.py` (110 行) — 用户交易风格分析(A4)
- `backend/routers/counterfactual.py` — 反事实报告 API(C1)
- `tests/test_agent_tools.py` (21 tests)
- `tests/test_slippage_model.py` (8 tests)
- `tests/test_t1_cost.py` (21 tests)
- `tests/test_t1_watcher.py` (16 tests)
- `tests/test_alpha158_batch2_3.py` (28 tests)
- `tests/test_user_style.py` (8 tests)
- `tests/test_counterfactual_api.py` (10 tests)
- `tests/test_combined_strategies.py` (11 tests)
- `tests/test_ic_recalibration.py` (13 tests)
- `tests/test_alpha158_batch1.py` (32 tests)

### 修改(9 文件)

- `backend/services/ai_service.py` (+310 行)— Claude + OpenAI tool_use 协议 + 工具调用循环
- `backend/services/multi_agent_service.py` (+250 行)— 8 角色 + JUDGE_SYSTEM_COT + 个性化 prompt
- `backend/services/factor_service.py` (+400 行)— 35 个新因子 + opens 参数 + IC 校准函数
- `backend/services/factor_lab.py` (+90 行)— B1 11 因子 + recalibrate_all_factors_ic
- `backend/services/strategy_backtest_service.py` (+200 行)— slippage + impact + run_combined_backtest
- `backend/services/agent_tools.py` — run_backtest + impact_bps 透传
- `backend/database.py` (+30 行)— t1_pending_orders 表 + 4 索引
- `backend/main.py` — counterfactual router 注册
- `database/schema.sqlite.sql` — t1_pending_orders DDL
- `frontend/src/app/pipeline/page.tsx` — 反事实 Tab + CounterfactualView
- `frontend/src/components/multi-agent-analysis.tsx` — 2x4 卡片 + CoT 折叠

---

## 🧪 测试统计

| 维度 | 数量 |
|------|------|
| **新增测试** | 168 个 |
| **修改测试** | 19 个(multi_agent_service) |
| **v4.0 总测试** | **223 个** |
| **测试覆盖率** | 关键路径 100%(5 核心服务) |

---

## ⚠️ 重大架构变更

### 数据库

- **新增表**:`t1_pending_orders`(T+1/T+2 模拟成交)
- **schema 变更**:`compute_all_factors` 加 `opens` 参数(向后兼容,缺则 K 线 4 因子为 None)
- **新增索引**:4 个(`t1_orders_*`)

### API

- **新增端点**:`/api/pipeline/counterfactual`, `/api/pipeline/retrospectives`
- **修改端点**:`/api/quant/multi-agent-analysis` 返回新增 3 字段(`capital_flow_report` / `policy_report` / `short_researcher_case` / `reasoning_chain` / `user_style`)

### 前端

- `/pipeline` 加"反事实" Tab
- 多 Agent 分析组件重写为 2x4 卡片布局
- 评分链可折叠 UI

---

## 🔧 部署与升级

### 从 v3.11 升级到 v4.0

1. **拉取最新代码**:`git pull origin main`
2. **运行 migration**:`python backend/scripts/init_db.py`(自动创建 `t1_pending_orders` 表)
3. **重启后端**:`start.bat` → 选项 3
4. **重启前端**:`npm run dev` (predev 自动清理 Turbopack 缓存)
5. **验证**:`pytest tests/test_t1_watcher.py tests/test_counterfactual_api.py` 全绿

### 环境变量

无新增,所有 v3.11 配置继续生效。AI Keys 继续走 `CLAUDE_API_KEY` / `DEEPSEEK_API_KEY` 等。

### 兼容性

- `compute_all_factors` 加 `opens` 参数(向后兼容,缺省不影响其他因子)
- `run_strategy_backtest` 加 `slippage_bps` / `impact_bps` 参数(默认 0 = 关闭)
- `analyze_stock` 加 `enable_cot` / `personalize` 参数(默认 True / False)
- 旧 API 端点保持不变

---

## 🐛 已修复 Bug

- `query_all` 返回 dict 化(原 `row[N]` 整数索引抛 KeyError)— 已在 v3.11 修复
- 多 Agent 推理不可见 — v4.0 A3 CoT 5 步推理解决
- 反事实数据无法可视化 — v4.0 C1 解决

---

## 🚧 已知限制(后续版本)

- 工具调用在多家 AI provider 上的兼容性仅在 Claude + DeepSeek 充分测试
- Phase 1-2 胶水代码(`scheduler.py` 守护线程 + pipeline 22:00 + 收件箱 UI 审批)尚未接入,需手动触发
- 64 因子中 4 个 K 线形态因子需要 OHLC 数据,数据源为 OHLC 时才能计算
- IC 重新校准需 ≥30 天有效数据

---

## 🙏 致谢

v4.0 是一次重大版本升级,感谢 v3.11 奠定的实验账本基础设施(`approval_proposals` / `proposal_retrospectives` / `shadow_portfolios`) — 这些都让 v4.0 的 C1 反事实报告 / T+1 watcher 有了现成的数据基础。

---

## 📚 相关文档

- [V4-PLAN.md](V4-PLAN.md) — v4.0 完整实施计划
- [CHANGELOG.md](CHANGELOG.md) — 逐 phase 详细变更记录
- [README.md](README.md) — 中文使用文档
- [README.en.md](README.en.md) — English docs
- [../docs/RUNBOOK.md](../docs/RUNBOOK.md) — 运维手册

---

**完整代码 + 测试**:[github.com/L71615/stockai](https://github.com/L71615/stockai)
