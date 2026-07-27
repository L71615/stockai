# StockAI Runbook — 应急响应 / 回滚 / 灰度 (v4.0, T8+)

> 出现 metric/settlement 异常、误晋级、用户投诉时, 按本手册执行.
> 优先级: 1) 关开关 → 2) 保留证据 → 3) 切回老路径 → 4) 排查修复.
>
> **v4.0 新增章节**: §8 T+1 模拟成交异常、§9 Agent 工具调用异常、§10 反事实报告异常

---

## 1. 灰度开关 (Feature Flags)

所有 v3.11 新功能默认 OFF, 写在 `feature_flags` 表. 开启后才生效.

### 1.1 当前 flag 列表

| flag_key | 默认 | 描述 |
|---|---|---|
| `pipeline.shadow.enabled` | OFF | 启用影子组合 (T4) |
| `pipeline.approval.enabled` | OFF | 启用审批收件箱 (T5) |
| `pipeline.negative_control.enabled` | OFF | 启用负对照 (T3) |
| `pipeline.champion_replacement.enabled` | OFF | 启用 Champion/Challenger 替换建议 (Gate 2) |
| `pipeline.auto_promote.enabled` | OFF | **自动晋级 (必须人工 OFF)** |

### 1.2 查看 flag 状态

```sql
SELECT flag_key, enabled, scope, updated_by, updated_at
FROM feature_flags ORDER BY flag_key;
```

### 1.3 启用 / 关闭 flag

```sql
-- 启用影子组合
UPDATE feature_flags
SET enabled = 1, updated_by = 'admin', updated_at = datetime('now','localtime')
WHERE flag_key = 'pipeline.shadow.enabled';

-- 关闭 (回滚)
UPDATE feature_flags
SET enabled = 0, updated_by = 'admin', updated_at = datetime('now','localtime')
WHERE flag_key = 'pipeline.shadow.enabled';
```

**重要**: flag 改动 5 分钟内生效 (内存缓存 TTL); 紧急时重启后端进程立即生效.

### 1.4 紧急全部关闭 (一键回滚)

```sql
UPDATE feature_flags SET enabled = 0, updated_by = 'rollback', updated_at = datetime('now','localtime');
```

这会关掉所有 v3.11 新功能, 系统回到 v3.10 行为. **append-only 证据表不动**.

---

## 2. 单飞锁

`pipeline_lock` 表防并发跑 pipeline 同 scope. 默认 scope: `pipeline_daily`.

### 2.1 查看锁状态

```sql
SELECT scope, holder_pid, acquired_at, expires_at,
       (julianday(expires_at) - julianday('now')) * 24 AS hours_left
FROM pipeline_lock;
```

### 2.2 强制释放 (worker 死了, 锁没释放)

```sql
DELETE FROM pipeline_lock WHERE scope = 'pipeline_daily';
```

⚠️ 仅在确认没有真正在跑的 worker 时执行.

---

## 3. 实验 / 影子组合 / 审批 异常

### 3.1 误晋级 / 错误 proposal

**症状**: 实验 lifecycle 被错误推到 paper / champion.

**处理**:
1. **不要**直接改 `experiments` 表, 保留证据完整性
2. 用 `experiment_service.transition()` 反向 transition:
   ```python
   from services.experiment_service import transition
   transition(experiment_id="exp-...", axis="lifecycle_status",
              target="retired", expected_version=N, actor="admin:rollback",
              reason="manual rollback per RUNBOOK")
   ```
3. 同步 `portfolio_role` 回 `none`
4. 关闭对应 flag (`pipeline.approval.enabled` / `pipeline.champion_replacement.enabled`)

### 3.2 影子组合异常结算

**症状**: 影子组合 NAV 暴跌 / 单日 +50%.

**处理**:
1. 检查 `shadow_portfolio_snapshots` 最近状态:
   ```sql
   SELECT portfolio_id, observation_date, nav, costs, status, reason
   FROM shadow_portfolio_snapshots
   WHERE status IN ('blocked', 'stale')
   ORDER BY observation_date DESC LIMIT 20;
   ```
2. 检查对应 `prices` 数据源 (Futu / akshare)
3. 关闭 `pipeline.shadow.enabled` 暂停新结算
4. 已结算的快照**保留**, 不要 DELETE

### 3.3 审批服务异常 (lease 过期 / CAS 冲突)

**症状**: 用户无法 accept / reject 提案.

**处理**:
1. 检查 proposal 状态:
   ```sql
   SELECT proposal_id, status, lease_expires_at, decided_at, decided_by
   FROM approval_proposals WHERE status = 'pending'
   ORDER BY lease_expires_at ASC LIMIT 20;
   ```
2. 过期 lease → 用户前端点"重开发 lease" 或调用:
   ```python
   from services.approval_service import reopen_lease
   reopen_lease(proposal_id, owner_user_id=1, lease_ttl_seconds=86400)
   ```
3. 审计完整 (append-only, 不丢):
   ```sql
   SELECT * FROM approval_attempts
   WHERE proposal_id = ? ORDER BY attempt_id DESC;
   ```

---

## 4. Pipeline Run 异常

### 4.1 Run 状态卡在 'running'

**症状**: `experiment_runs.status = 'running'` 但 worker 已死.

**处理**:
1. 查 stale run (started_at > 24h 前):
   ```sql
   SELECT run_id, started_at, current_step FROM experiment_runs
   WHERE status = 'running' AND started_at < datetime('now','-24 hours');
   ```
2. 标记 failed (保留 append-only 证据):
   ```sql
   UPDATE experiment_runs
   SET status = 'failed',
       error_json = '{"reason": "stale run, worker died, manual rollback"}',
       finished_at = datetime('now','localtime')
   WHERE run_id = ?;
   ```
3. 检查 `pipeline_lock`, 释放僵尸锁

### 4.2 通知失败掩盖了研究状态

**症状**: 简报生成成功, 但 `notify_ok=false`.

**处理**:
1. 这是 **预期行为** (D7), 不掩盖: 研究 `done` 状态正确入库
2. 查 `notification_log` 找具体哪个 channel 失败:
   ```sql
   SELECT * FROM notification_log
   WHERE success = 0 ORDER BY created_at DESC LIMIT 10;
   ```
3. 单独修 SMTP / Telegram / 微信 webhook 配置, **不影响**研究数据

---

## 5. 监控指标 (手动 query)

### 5.1 健康度快照

```sql
-- 最近 7 天 Gate 通过率 (实验数 / 总数)
SELECT
  date(created_at) AS day,
  COUNT(*) AS total_experiments,
  SUM(CASE WHEN lifecycle_status IN ('validated', 'paper', 'champion') THEN 1 ELSE 0 END) AS passed_gate
FROM experiments
WHERE created_at > datetime('now','-7 days')
GROUP BY date(created_at);

-- 影子组合 block / stale 日数
SELECT
  date(observation_date) AS day,
  SUM(CASE WHEN status = 'settled' THEN 1 ELSE 0 END) AS settled,
  SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked,
  SUM(CASE WHEN status = 'stale' THEN 1 ELSE 0 END) AS stale
FROM shadow_portfolio_snapshots
WHERE observation_date > date('now','-7 days')
GROUP BY date(observation_date);

-- 最近审批积压
SELECT
  COUNT(*) AS pending_proposals,
  SUM(CASE WHEN lease_expires_at < datetime('now') THEN 1 ELSE 0 END) AS expired
FROM approval_proposals WHERE status = 'pending';
```

### 5.2 期望基线

- **Gate 通过率**: < 5% (v3.11 严格, 这是计划值)
- **shadow blocked/stale**: < 10% (主要因节假日/停牌)
- **approval pending**: < 20 条 (≤1 周积压)

---

## 6. 回滚 checklist (最严重时)

```
□ 1. 备份数据库: cp database/stockai.db database/stockai.db.bak
□ 2. 一键关 flag: UPDATE feature_flags SET enabled = 0 ...
□ 3. 重启后端: pkill -f uvicorn; cd backend && python -m uvicorn main:app ...
□ 4. 保留所有 append-only 表 (experiments, snapshots, attempts, etc.)
□ 5. 查 stale run 列表 → 手动标 failed
□ 6. 通知用户: 已决策的 proposal 仍生效, 只是新功能停了
□ 7. 排查 fix 后, 用 git revert 或反向 transition 修正
□ 8. 重新小流量开 flag (1 个候选 → 3 个 → 10 个)
```

⚠️ **永远不要**:
- DELETE 任何 append-only 表 (`experiment_run_events`, `approval_attempts`, `experiment_snapshots`)
- 直接 UPDATE `experiments` 表 (绕过 CAS), 用 `transition()`
- DROP 整个表 (即使"看起来没用")

---

## 7. 紧急联系方式

- **服务监控**: 看 `/api/health` 和 `/api/pipeline/status`
- **日志位置**: `backend/backend.log` (rotating)
- **本次上线变更**: 见 `CHANGELOG.md` v4.0 节

---

## 8. T+1 模拟成交异常 (v4.0)

### 8.1 监控点

- **未成交订单堆积**:`t1_pending_orders.status = 'pending_buy'` 数量
- **卡在 bought 状态**:持有期满但 `exit_date <= today` 仍未 sold
- **异常 PnL**:大额负 PnL 或胜率 < 30%

```sql
-- 当前未成交订单
SELECT status, COUNT(*) FROM t1_pending_orders GROUP BY status;

-- 卡住的 bought 订单
SELECT * FROM t1_pending_orders
WHERE status = 'bought' AND exit_date <= date('now')
LIMIT 20;
```

### 8.2 应急处理

| 症状 | 立即动作 | 后续排查 |
|------|----------|----------|
| `process_pending_buys` 报错 | 检查 `vendor_router` 状态 / 离线 futu 是否影响 | 看 `backend.log` 关键错误 |
| 历史 K 线缺失 | 手动从 `quant_pipeline.py` 跑 `nightly` 数据同步 | 检查 akshare/baostock fallback |
| 大量 `cancelled` 订单 | 检查 `t1_watcher.cancel_order` 触发原因 | 翻 `reason` 字段 |
| holdings/transactions 写入失败 | 检查 DB 锁(可能 `pipeline_lock` 占用) | 杀进程重试 |

### 8.3 关闭 T+1 watcher(极端情况)

```bash
# 临时禁用:把 cron 任务从 scheduler.py 注释掉,重启后端
# 不删数据 — `t1_pending_orders` 保留,恢复后继续处理
```

### 8.4 数据回滚

如需回滚某天的 T+1 模拟成交:

```sql
-- 找出某天的 holdings 写入
SELECT * FROM transactions
WHERE note LIKE '%T+1%' AND date(traded_at) = '2026-07-15';

-- 手动标记订单为 cancelled
UPDATE t1_pending_orders
SET status = 'cancelled', reason = '手动回滚: 异常数据'
WHERE id = 123;
```

---

## 9. Agent 工具调用异常 (v4.0 A2)

### 9.1 监控点

- `ai_chat_with_tools` 调用失败率
- 工具调用循环超过 5 轮(死循环信号)
- 工具返回大量 `error` 字段

### 9.2 常见问题

| 错误 | 原因 | 修复 |
|------|------|------|
| `工具未注册` | `agent_tools.TOOL_REGISTRY` 没同步 | 确认 `agent_tools.py` import 正常 |
| `tool_use` 不被识别 | Claude 模型版本太老(< 3.5 Sonnet) | 升级到 Claude 3.5+ |
| `function_calling` 不被识别 | DeepSeek API 兼容性问题 | 改用 `base_url` 对齐 OpenAI 协议 |
| 5 轮循环耗尽 | Agent 没找到工具 | 检查 `tools` 列表是否含目标工具 |
| 工具结果不返回 | `execute_tool_call` 内部异常 | 看 `agent_tools._get_quote_tool` 等日志 |

### 9.3 应急开关

```python
# 在 ai_chat.py 中临时关闭工具调用,降级到纯对话
from services import agent_tools
agent_tools.TOOL_REGISTRY = {}  # 清空工具列表
```

### 9.4 与 A3 CoT 交互

- A3 启用时(`enable_cot=True`),JUDGE_SYSTEM_COT 强制结构化 JSON
- 如果 CoT 解析失败,`_parse_judge_response` 会回退到文本推断
- 监控: `reasoning_chain` 为空的次数 / 总调用次数

---

## 10. 反事实报告异常 (v4.0 C1)

### 10.1 监控点

- `proposal_outcomes` 表数据稀疏(无 realized_at)
- `proposal_retrospectives` 缺少 `lesson` 字段
- `/api/pipeline/counterfactual` 返回空 accepted/rejected

```sql
-- outcomes 覆盖率
SELECT
  COUNT(*) AS total_outcomes,
  COUNT(*) FILTER (WHERE label = 'good') AS good,
  COUNT(*) FILTER (WHERE label = 'bad') AS bad
FROM proposal_outcomes
WHERE realized_at >= date('now', '-30 days');
```

### 10.2 异常处理

| 症状 | 排查 |
|------|------|
| `accepted.count = 0` | 检查 `proposal_outcomes` 是否有 'approved' 决策的实绩 |
| `edge` 始终为 0 | 多数 decision 的 fwd_return = 0(未填实绩) |
| `interpretation` 异常 | 检查 `proposal_retrospectives.lesson` 字段 |

### 10.3 重新生成 retrospective

```bash
# 触发回填(如有 background job)
python -m services.retrospective_service backfill --days 30
```

---

## 11. 8 角色多 Agent 异常 (v4.0 A1)

### 11.1 监控点

- `agent_count < 8`(角色被禁用)
- Token 消耗(8 角色并发 vs 5 角色 ~2x)
- 单次 `analyze_stock` 延迟(>30s)

### 11.2 降级

```python
# 调用方:限制角色到 5(向后兼容)
result = await analyze_stock(
    "000001",
    enabled_roles=["technical", "fundamentals", "bull", "bear", "judge"],
    enable_cot=False,  # 同时关 CoT,降到 5 角色 + 简单 prompt
)
```

### 11.3 CoT (A3) 关闭

```python
result = await analyze_stock("000001", enable_cot=False)
# 退回 JUDGE_SYSTEM,更快但 reasoning_chain 为空
```

### 11.4 个性化 (A4) 关闭

```python
result = await analyze_stock("000001", personalize=False, user_id=None)
# 不注入 user_style,适合批量扫股
```

---

## 12. v4.0 部署检查清单

### 12.1 升级后必须验证

```bash
# 1. 数据库 schema 正确(新增 t1_pending_orders)
python -c "from database import init_db; init_db()"

# 2. 所有 v4.0 测试通过
pytest tests/test_agent_tools.py tests/test_t1_watcher.py \
       tests/test_counterfactual_api.py tests/test_user_style.py \
       tests/test_combined_strategies.py tests/test_alpha158_batch1.py \
       tests/test_alpha158_batch2_3.py tests/test_ic_recalibration.py -v
# 预期:223+ passed

# 3. 路由注册正确
python -c "from main import app; print([r.path for r in app.routes if 'counterfactual' in r.path])"
# 预期:['/api/pipeline/counterfactual', '/api/pipeline/retrospectives']
```

### 12.2 数据迁移(如有 v3.11 旧库)

```bash
# 1. 备份
cp database/stockai.db database/stockai.db.bak.v3.11

# 2. 跑 init_db(自动 IF NOT EXISTS 创建 v4.0 新表)
python -c "from database import init_db; init_db()"

# 3. 验证
sqlite3 database/stockai.db ".tables" | grep t1_pending_orders
# 预期:t1_pending_orders
```

### 12.3 回滚到 v3.11(紧急)

```bash
# 1. 拉 v3.11 tag
git checkout v3.11
# 2. 备份 v4.0 数据(可选,保留)
mv database/stockai.db database/stockai.db.v4.0.bak
# 3. 恢复 v3.11 DB
cp database/stockai.db.bak.v3.11 database/stockai.db
# 4. 重启后端
```

---

**v4.0 RUNBOOK END — 应急响应优先级:关开关 > 保留证据 > 切老路径 > 排查修复**
