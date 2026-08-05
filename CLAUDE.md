# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **当前版本: v5.0-beta-M7**(2026-08-05 tag) — 55 因子完整接入(`235f20b`)
> **量化方向**: 准实盘量化交易系统(D1 战略锁定) — 实时行情 + 盘中因子 + 信号手动确认 + 模拟成交
> **最新改动**: v5.0-beta M7 patch:
>   - **feat**: `realtime_factor_cache.py` in-place 升 30→55 因子(`compute_realtime_factors()` 转发到 `factor_service.compute_minute_factors`)
>   - **feat**: `fetch_recent_bars()` 改返 5 元组 `(closes, highs, lows, opens, volumes)` + `data_source` 字段
>   - **feat**: `/api/realtime/factor/{code}` 响应新增 `data_source` 字段
>   - **test**: 20 个 mock 测试 + M6 30 测试回归全过
> **上一里程碑**: v5.0-beta M6: minute bars 接入 — `fetch_recent_bars()` 灰度切 1m(`REALTIME_USE_MINUTE_BARS` env), Futu 失败自动 fallback 日级。详见 `RELEASE-NOTES-v5.0-beta-M6.md`
> **再上一**: v4.2.4 patch (`70f9dc3`) — `_pearson_daily` + decay 向量化(~90s → ~4s) + `get_cached_leaderboard()` 5min TTL + `async def` 漏改修复
> 详见 `RELEASE-NOTES-v4.2.md` + `RELEASE-NOTES-v4.2-m2.md` + `RELEASE-NOTES-v4.2.2.md` + `RELEASE-NOTES-v4.2.3.md` + `RELEASE-NOTES-v4.2.4.md`;**v5.0-alpha** 已完成(69 测试,git tag v5.0),详见 `2026-08-01-v5.0-strategy.md` + `RELEASE-NOTES-v5.0.md`
> **详细记录**: 看 `stockai-project-docs/CHANGELOG.md` 和 `stockai-project-docs/V4-PLAN.md`
> **文档结构**: 根目录 `INDEX.md` 是入口,所有 MD 已分类到 `stockai-project-docs/` 与 `monitor-desktop-docs/`

## gstack

所有网页浏览必须使用 gstack 的 `/browse` 技能，切勿使用 `mcp__claude-in-chrome__*` 工具。

### 可用技能

`/office-hours` `/plan-ceo-review` `/plan-eng-review` `/plan-design-review` `/design-consult` `/design-shotgun` `/design-html` `/review` `/ship` `/land-and-deploy` `/canary` `/benchmark` `/browse` `/connect-chrome` `/qa` `/qa-only` `/design-review` `/setup-browser-cookies` `/setup-deploy` `/setup-gbrain` `/retro` `/investigate` `/document-release` `/document-generate` `/codex` `/cso` `/autoplan` `/plan-devex-review` `/devex-review` `/careful` `/freeze` `/guard` `/unfreeze` `/gstack-upgrade` `/learn`

## 语言偏好

使用中文回复。

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec

## Design System

Always read `stockai-project-docs/DESIGN.md` before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match `stockai-project-docs/DESIGN.md`.

---

## 启动与构建

### 推荐路径
- Windows 控制面板：`D:\stocks\start.bat` → 选项 3 启动全部 / 4 停止 / 5 安装依赖
- 后端 `http://localhost:3000`，前端 `http://localhost:3001`，API 文档 `/api/docs`

### 手动启动
```bash
# 后端（端口 3000）
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload --env-file .env

# 前端（端口 3001）
cd frontend
npm run dev          # predev 会自动清理 Turbopack 缓存（根治 disposed 错误）
npm run dev:safe     # 4GB 堆内存，适用于大型页
```

### 依赖安装
- 后端：`pip install -r backend/requirements.txt`（含 fastapi/akshare/baostock/futu-api/anthropic/openai）
- 前端：`cd frontend && npm install`
- Futu：本地安装并启动 Futu OpenD（默认 127.0.0.1:11111）

### 测试
- 后端：`cd backend && pytest`（`backend/tests/` 下含 Futu client / ingest / sync / quant 回归）
- 前端：`npm run lint` + `npm run build`
- 数据同步脚本：`python backend/scripts/sync_futu_data.py --code 600519 --type quote|minute|daily`

### 必填环境变量（缺失会启动失败）
| 变量 | 说明 |
|------|------|
| `JWT_SECRET` | 64 位 hex（不填 → ValueError） |
| `ENCRYPTION_KEY` | 64 位 hex（加密存储的 AI Key） |
| `CORS_ORIGINS` | 逗号分隔白名单（不填 → ValueError） |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | 启动时自动创建管理员（无注册流程） |
| AI: 至少配一个 | `CLAUDE_API_KEY` / `DEEPSEEK_API_KEY` / `MINIMAX_API_KEY` / `OPENAI_API_KEY` / `XIAOMI_API_KEY` |
| 通知（可选） | `WECHAT_WEBHOOK_URL` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / SMTP_* |

---

## 架构

### 后端（FastAPI · `backend/`）
- `main.py` — 中间件链（auth → security headers）、全局异常处理（`AIServiceError`→503 / `Exception`→500）、`startup` 启动后台守护线程
- `routers/` — **18 个 API 路由**（v3.9 +1 data_ops · v4.0 +5 流水线）。所有 `/api/*` 走 JWT 中间件（公开列表：`/api/auth/login`、`/api/health`、`/api/version`、`/api/docs`、`/api/openapi.json`）
  - **🆕 v3.9 `data_ops.py`** — `/api/data-ops/*` 6 个端点：stocks / freshness / sector-performance / sparkline / sync-stocks / sync-status
  - **🆕 v4.0 流水线路由**（5 个）：
    - `approvals.py` — proposal 审批（approve/reject/withdraw）
    - `experiments.py` — `/api/pipeline/experiments*` 实验查询与审计事件
    - `counterfactual.py` — `/api/pipeline/counterfactual` + `/api/pipeline/retrospectives` C1 反事实报告（独立 router，避免与 experiments 前缀冲突）
    - `shadow.py` — shadow 模拟成交
    - `factor_lab.py` — `/api/factor-lab/*` IC/相关性/散点图
  - **🆕 v4.1 不增加新路由** — 现有路由的语义升级（holdings vs shadow 对比卡 / bulk-approve 单事务 / 反事实可视化）
- `services/` — 40+ 业务服务，关键模块：
  - `factor_service.py` — 55 因子计算（10 大类：价格/动量/波动/成交量/量价/基本面/情绪/资金/技术），因子函数自己消化异常（NaN/inf → None）+ **🆕 v4.1.1** `factor_rsrs` (阻力支撑相对强度,18 日 OLS beta z-score)
  - `factor_lab.py` — **🆕** IC 分析 + 相关性矩阵 + 散点图（+ 衰减评分 `_compute_decay_score()`）
  - `factor_expr.py` — **🆕** GP 遗传编程挖掘因子（表达式 AST 安全求值）
  - `factor_ml.py` — **🆕** LightGBM ML 因子 + **GP+ML 联合训练** (`train_ml_with_gp_factors()`)
  - `factor_lifecycle.py` — **🆕** 因子生命周期管理(active / warning / retired 三态 + 自动退役) + **🆕 v4.1.1** `_notify_lifecycle_changes` 联动通知
  - `ai_service.py` + `vendor_router.py` + `ai_exceptions.py` — 多供应商（5 家）× 7 功能独立路由，异常体系 5 级
  - **`agent_tools.py`** — **🆕 v4.0 A2** Agent 工具注册表(get_quote / get_factor / run_backtest / calc_t1_cost),支持 OpenAI function_calling + Anthropic tool_use 双协议
  - **`t1_cost.py`** — **🆕 v4.0 C2** T+1/T+2 持仓成本计算器(卖费+持仓风险溢价+滑点)
  - **`t1_watcher.py`** — **🆕 v4.0** T+1 模拟成交 watcher + **🆕 v4.2 M1** 6 态机(OSS 风格:open / partial_filled / filled / closed / cancelled / rejected)+ `transition()` 守卫函数 + 白名单 + CAS,写 holdings + transactions + **🆕 v4.1.1** `_evaluate_buy_risk` 风控拦截 + **🆕 v4.2** audit event_type='risk_blocked' 写 `t1_order_events`
  - `condition_engine.py` + `strategies/*.yaml` — 13 个 YAML 策略模板,AND/OR 组合 + 可调参数
  - **`strategy_registry.py`** — **🆕 v4.1.1** YAML 策略自动注册中心(单例 + mtime 失效 + validate)
  - **`risk_sizing.py`** — **🆕 v4.1.1** 4 种仓位算法(FixedFraction / Kelly / RiskParity / VolTarget) + calc_win_rate_and_profit_factor
  - **`risk_guard.py`** — **🆕 v4.1.1** 4 规则风控评估器(max_drawdown / daily_loss / single_position / total_exposure)
  - `futu_client.py` / `futu_ingest_service.py` / `futu_sync_service.py` — Futu OpenD 行情接入与 `intraday`/`nightly` 批量同步
  - `backtest_service.py` / `strategy_backtest_service.py` / `multi_agent_service.py` — 回测引擎（含 **🆕 v4.0 B4 滑点模型** + F10 买卖点标注 + `_evaluate_protection()` 6 维风险评估）+ **🆕 v4.0 A1 8 角色多空辩论**(资金面/政策/做空)
  - `trading_memory.py` — 决策→验证→反思→注入 闭环
  - `cache.py` — 三层缓存（factor_snapshot / daily_north_flow / daily_inst_holding + 24h TTL lazy-write）。**⚠️ 注意：所有 `row[]` 访问必须用列名（query_all 已 dict 化）**
  - `akshare_adapter.py` — A 股数据（东方财富/腾讯/新浪 fallback）。**⚠️ 腾讯免费 API 有 QPS 限制，连续 3000+ 调用必触发限频**
  - `scheduler.py` — 后台守护线程（DCA 提醒 / 止损 / Futu intraday+nightly 同步 / 记忆解析 / 晚间基本面 / **v4.1: index-sync 17:00 / etf-sync 17:10 / daily-pipeline 22:00 / drift-monitor 23:30**）
- **`base_vendor_sync.py`** — **🆕 v4.1 2A** Abstract BaseClass 模板方法（`_record_run` / `_record_item` / `_finalize_run` / `_maybe_alert` / `run_sync`），子共享给 Index/ETF sync
- **`index_sync_service.py`** — **🆕 v4.1 2A** 6 默认指数 K 线同步（沪深300/中证500/创业板/上证50/中证1000/科创50）
- **`etf_sync_service.py`** — **🆕 v4.1 2A** 11 默认 ETF K 线同步（6 宽基 + 5 行业/跨境/商品）
- **`drift_policy.py`** — **🆕 v4.1 2A/2B** PSI/KL 纯函数 + `load_active_policy()` 阈值版本化（DriftThresholds + 分类）
- **`drift_monitor.py`** — **🆕 v4.1 2A/2B** orchestrator，`experiment_runs.status='done'` gate + `_historical_metric_mean()` 填 baseline_value + severe 通知
- **`database.execute_transaction()`** — **🆕 v4.1** 单事务 helper（t1_watcher._simulate_buy/_simulate_sell / acquire_pipeline_lock 用）
- `strategies/` — 13 个 YAML 策略（boll / turtle / momentum / value / pullback 等）

### 数据库（SQLite · `database/`）
- WAL 模式 + 连接池（5 个）+ `busy_timeout=5000ms` + `foreign_keys=ON`
- 入口：`database.query_all / query_one / execute / execute_many`（自动归还连接到池）。**⚠️ query_all 返回 `list[dict]`（已 dict 化），所有 `row[]` 整数索引会抛 KeyError**
- 关键表：`users` · `holdings` · `transactions` · `dca_plans` · `futu_raw_quote` · `futu_raw_kline` · `historical_kline` · `futu_sync_runs` · `futu_sync_run_items` · `ai_*` · `trading_memory_*`
- **🆕 v3.9 因子实验室表**：`factor_snapshot`（55 因子 × 全市场 · 24h TTL）· `factor_candidates`（GP/ML 挖掘候选因子）· `factor_lifecycle_status`（active/warning/retired）
- **🆕 v4.0 T+1/T+2 表**：`t1_pending_orders`(状态机 pending_buy→bought→sold,模拟成交 + 收益统计)+ **🆕 v4.2 M1** 6 态(OSS 风格)+ `filled_shares` / `pending_shares` partial_filled 字段
- **🆕 v4.2 M1 事件溯源表**：`t1_order_events`(order_id → 整条订单生命周期可回放,actor/event_type/from_status/to_status/metadata_json)
- **🆕 v4.1 2A 基准表**：`index_kline`（6 默认指数 sh000300/sz399006 等 · PK (symbol, trade_date)）· `etf_kline`（11 默认 ETF 510300/510500/159915 等）· `index_sync_runs`/`index_sync_run_items` · `etf_sync_runs`/`etf_sync_run_items`
- **🆕 v4.1 2A/2B 漂移表**：`drift_events`（factor/metric/value/severity 记录）· `drift_policies`（版本化阈值 policy_version + effective_from/to，init_db 自动插入 v1.0-default）
- Schema：`database/schema.sql`（应用初始化时由 `database.init_db()` 执行 — **关键单点风险**：新表必须同步 4 处 `database.py` + `schema.sql` + `schema.sqlite.sql` + 直接 apply dev DB）

### 前端（Next.js 16 · `frontend/`）
- `src/app/` — App Router，**🆕 9 个页面**（`/` 持仓概览 · **`/browse` 🆕 全市场浏览** · `/quant` 量化 · `/screener` AI 选股 · `/screener/condition` 条件选股 · `/transactions` 交易记录 · `/ai-assistant` AI 对话 · `/settings` 设置 · `/market` 大盘指数）
- `src/middleware.ts` — 前端层认证（路由级跳转登录）
- `src/lib/` — `api-types.ts` API 客户端（按功能模块拆分）· `swr-config.tsx` 全局 SWR 配置 · `auth.ts` / `auth-redirect.ts` / `protected-page-auth.ts` 认证工具
- `src/hooks/` — SWR 数据 hooks（`use-portfolio` / `use-watchlist` / `use-market` / `use-review` / `use-mobile`），统一缓存去重
- `src/components/` — 关键组件：
  - **`KlineChart.tsx`** — lightweight-charts v5 + 5 指标 + 海龟通道 + **🆕 TradeMarker 支持（F10 买卖点标注）**
  - `data-table*.tsx`（v3.6 拆分为 core / cells / drawer / 入口 4 文件）
  - `multi-agent-analysis.tsx`
  - ~~`hot-panel.tsx`~~（v3.9 已删，akshare 接口坏且用户不需要）

### 后台线程（`startup` 时启动）
| 线程 | 周期 | 作用 |
|------|------|------|
| DCA 提醒 | 每小时 | 24h 内到期计划 → 邮件 |
| 止损检查 | 每分钟 | 持仓触发止损 → 通知推送 |
| Futu intraday 同步 | 交易时段 | watchlist + holdings 实时行情落库 |
| Futu nightly 同步 | 每日晚间 | 日线 + 基本面落库 |
| 交易记忆解析 | 定时 | 历史交易 → AI 反思 → 注入知识库 |

---

## 设计系统

`stockai-project-docs/DESIGN.md` 为唯一权威源,强制规范:
- 暗色主题（oklch 色彩空间，`.dark`）· `rounded-none`（`--radius: 0`）· Tabler Icons 唯一图标库（**禁止 emoji 作为功能图标**）
- 数字列必须 `tabular-nums` · 状态组件须处理 Loading/Empty/Error/Success 4 态
- 字体：PingFang SC / Microsoft YaHei（Sans）· JetBrains Mono / SF Mono（Mono）

---

## 关键约束（违反会触发回归 bug）

- **TypeScript 零 `any`**（v3.6 P1 工程已强制）
- **认证解耦**：JWT 通过 `ContextVar(_current_user_id)` 传递，**禁止硬编码 user_id**（v3.6 已清零 24 处）
- **AI 调用**：失败必须抛 `AIServiceError`（带 `provider_name` + `function_key`），**不要裸 `try/except`** — 全局 handler 自动返 503
- **因子计算**：因子函数自己消化异常返回 `None`，调用方收到 `None` 即跳过该因子
- **数据源 fallback**：报价 / 日线 / 1m 图表优先走 Futu，失败链：`futu → sina → akshare → baostock`
- **query_all 返回 dict**：所有 SQL 查询结果 `row[N]` 整数索引会抛 `KeyError`。**必须用列名 `row["col_name"]` 或 `row.get(N)`**（v3.9 cache.py 修复过此 bug）
- **🆕 A 股交易日历**：`days_ago` 必须用 `_trading_days_lag()` 计算（akshare.tool_trade_date_hist_sina），不能用日历天数（周末/节假日误判）
- **🆕 复权一致性**：所有数据源统一用 qfq 前复权（akshare + baostock + Futu），切换数据源前确认复权方式一致
- **🆕 akshare 限频**：腾讯免费 API（`web.ifzq.gtimg.cn`）有 QPS 限制，单次批量调用 >500 必触发 30-60 分钟冷却。`sync-stocks` 必须带 retry + sleep（≥0.1s）
- **不要提交**：`*.db` / `*.db-*` / `.env` / `reports/` / `.claude/` / `docs/superpowers/` / `backend-start.*.log` / `*.tsbuildinfo`（详见 `.gitignore`）
- **Futu 同步**：表结构 `futu_raw_quote` / `futu_raw_kline` / `futu_sync_runs` / `futu_sync_run_items`，新增字段必须更新 `database/schema.sql`
- **策略 YAML**：新增策略放 `backend/strategies/*.yaml`，参数必须在 YAML 中标注 `description`（用户在条件选股页可见说明）
- **🆕 Radix UI Select**：`<SelectItem value="">` 不允许（空串用于"清除选择"）。要用 `value="__all__"` 等占位，onValueChange 时映射回业务值
- **🆕 类型契约**：修改 `services/*.py` 函数签名要同步更新 `frontend/src/lib/api-types.ts` 的 TS 类型