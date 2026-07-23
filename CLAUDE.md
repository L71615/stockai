# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **当前版本: v3.10** (2026-07-23)
> **量化方向**: 因子挖掘/分析 + 回测 + 预测（用户 7-19 调整项目重点）
> **最新改动**: 自动量化 Pipeline (cron + 简报 + 推送) + 端到端 5 步跑通
> **详细记录**: 看 `CHANGELOG.md`

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

Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

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
- `routers/` — **12 个 API 路由**（v3.9 +1: `data_ops` 数据运维）。所有 `/api/*` 走 JWT 中间件（公开列表：`/api/auth/login`、`/api/health`、`/api/version`、`/api/docs`、`/api/openapi.json`）
  - **🆕 v3.9 `data_ops.py`** — `/api/data-ops/*` 6 个端点：stocks / freshness / sector-performance / sparkline / sync-stocks / sync-status
- `services/` — 40+ 业务服务，关键模块：
  - `factor_service.py` — 55 因子计算（10 大类：价格/动量/波动/成交量/量价/基本面/情绪/资金/技术），因子函数自己消化异常（NaN/inf → None）
  - `factor_lab.py` — **🆕** IC 分析 + 相关性矩阵 + 散点图（+ 衰减评分 `_compute_decay_score()`）
  - `factor_expr.py` — **🆕** GP 遗传编程挖掘因子（表达式 AST 安全求值）
  - `factor_ml.py` — **🆕** LightGBM ML 因子 + **GP+ML 联合训练** (`train_ml_with_gp_factors()`)
  - `factor_lifecycle.py` — **🆕** 因子生命周期管理（active / warning / retired 三态 + 自动退役）
  - `ai_service.py` + `vendor_router.py` + `ai_exceptions.py` — 多供应商（5 家）× 7 功能独立路由，异常体系 5 级
  - `condition_engine.py` + `strategies/*.yaml` — 13 个 YAML 策略模板，AND/OR 组合 + 可调参数
  - `futu_client.py` / `futu_ingest_service.py` / `futu_sync_service.py` — Futu OpenD 行情接入与 `intraday`/`nightly` 批量同步
  - `backtest_service.py` / `strategy_backtest_service.py` / `multi_agent_service.py` — 回测引擎（含 **🆕 F10 买卖点标注** + **🆕 `_evaluate_protection()` 6 维风险评估**）+ 5 角色多空辩论
  - `trading_memory.py` — 决策→验证→反思→注入 闭环
  - `cache.py` — 三层缓存（factor_snapshot / daily_north_flow / daily_inst_holding + 24h TTL lazy-write）。**⚠️ 注意：所有 `row[]` 访问必须用列名（query_all 已 dict 化）**
  - `akshare_adapter.py` — A 股数据（东方财富/腾讯/新浪 fallback）。**⚠️ 腾讯免费 API 有 QPS 限制，连续 3000+ 调用必触发限频**
  - `scheduler.py` — 后台守护线程（DCA 提醒 / 止损 / Futu intraday+nightly 同步 / 记忆解析 / 晚间基本面）
- `strategies/` — 13 个 YAML 策略（boll / turtle / momentum / value / pullback 等）

### 数据库（SQLite · `database/`）
- WAL 模式 + 连接池（5 个）+ `busy_timeout=5000ms` + `foreign_keys=ON`
- 入口：`database.query_all / query_one / execute / execute_many`（自动归还连接到池）。**⚠️ query_all 返回 `list[dict]`（已 dict 化），所有 `row[]` 整数索引会抛 KeyError**
- 关键表：`users` · `holdings` · `transactions` · `dca_plans` · `futu_raw_quote` · `futu_raw_kline` · `historical_kline` · `futu_sync_runs` · `futu_sync_run_items` · `ai_*` · `trading_memory_*`
- **🆕 v3.9 因子实验室表**：`factor_snapshot`（55 因子 × 全市场 · 24h TTL）· `factor_candidates`（GP/ML 挖掘候选因子）· `factor_lifecycle_status`（active/warning/retired）
- Schema：`database/schema.sql`（应用初始化时由 `database.init_db()` 执行）

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

DESIGN.md 为唯一权威源，强制规范：
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