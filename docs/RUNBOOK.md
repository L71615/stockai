# StockAI Runbook — 应急响应 / 回滚 / 灰度 (v3.11+, T8)

> 出现 metric/settlement 异常、误晋级、用户投诉时, 按本手册执行.
> 优先级: 1) 关开关 → 2) 保留证据 → 3) 切回老路径 → 4) 排查修复.

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
- **本次上线变更**: 见 `CHANGELOG.md` v3.11 节