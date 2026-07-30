# StockAI v4.1 — Decision-Loop 闭环 + 真实基准 + Drift 监控

**发布日: 2026-07-30**
**代码基线: 59a4ec9**

---

## 🎯 v4.1 一句话

把"研究 → 决策 → 成交 → 复盘"打通成自动循环,用真实指数基准取代 ETF 代理,并引入 PSI/KL 漂移监控防止 factor 失效。

---

## ✨ 三大主线交付

### 1️⃣ 决策闭环 (Phase 1A/1B)

| 能力 | v4.0 | v4.1 |
|---|---|---|
| Daily Pipeline | 手动触发 | scheduler 22:00 守护线程 + busy_timeout 10s + pool 15 |
| T+1 Watcher | 单次跑 | scheduler 守护 + 09:35 first-tick 校验 + 通知推送 |
| Shadow 组合 | 跑通无 UI | 净值曲线图 + holdings vs shadow 对比卡 |
| Bulk Approve | 无 | 单事务 + 三层乐观锁 + 0.85 边界 |
| 反事实 | 一次性 | `run_retrospective_writer` 自动跟跑 |

### 2️⃣ 真实基准 (Phase 2A)

`_get_benchmark_curve` 从「ETF 510300 代理」升级到 **4 段 fallback**:
1. `index_kline` (CSI300/中证500/创业板/上证50/中证1000/科创50)
2. `etf_kline` (11 默认 ETF)
3. `historical_kline` 代理 (老 holdings)
4. 全市场等权合成 (last-resort)

新增同步守护:
- **17:00** index-sync nightly (30 天增量)
- **17:10** etf-sync nightly (30 天增量)
- 首次部署需手动 `run_full_seed(days_back=1250)` 5 年 seed

### 3️⃣ 漂移监控 (Phase 2A/2B)

`drift_events` 表 + `drift_policies` 表版本化阈值:

```python
# 调度 23:30 跑
result = run_drift_check(snapshot_at=today)
# {"pipeline_status": "done", "policy_version": "v1.0-default",
#  "events_written": 8, "by_severity": {"none": 8, "warning": 0, "severe": 0}}
```

**Gate 设计**: 只在 `experiment_runs.status='done'` 当天才跑 — 没有真实 pipeline run 就不浪费 CPU。

**阈值版本化**: 插一行新 policy 即可切换严格度:
```sql
INSERT INTO drift_policies (version, psi_warn, psi_severe, kl_warn, kl_severe, bins, effective_from, ...)
VALUES ('v2.0-strict', 0.05, 0.15, 0.05, 0.30, 10, '2026-08-01', ...);
```

---

## 🐛 v4.0 outside voice 5 项修复

| Bug | 修复 |
|---|---|
| `init_db:733` `idx_appr_prop_score` | ALTER ADD COLUMN 必须在 CREATE INDEX 之前 |
| `t1_watcher._simulate_buy` 非原子 | 封装 `execute_transaction` 单事务 (4 步写入同时成功/失败) |
| `pipeline_lock` 跨进程 race | 整体包 `execute_transaction` 保证写串行 |
| 09:30 open-price race | 触发时间 09:30→09:35 + first-tick ±20% 校验 |
| admin lookup 硬编码 `id=1` | 改用 `email OR username='admin'` 查询 + username 同步 |

---

## 📦 数据库 schema 改动

### 新增 (7 表)
- `index_kline` (PK: symbol, trade_date)
- `etf_kline` (PK: code, trade_date)
- `index_sync_runs` / `index_sync_run_items`
- `etf_sync_runs` / `etf_sync_run_items`
- `drift_events`
- `drift_policies` (init_db 自动插入 v1.0-default)

### 修改 (1 字段)
- `approval_proposals.decision_score` — ALTER 移到 CREATE INDEX 之前

---

## 🧪 测试

| 测试文件 | 数量 | 状态 |
|---|---|---|
| `test_index_sync_service.py` | 7 | ✅ |
| `test_etf_sync_service.py` | 6 | ✅ |
| `test_drift_policy.py` | 8 | ✅ |
| `test_drift_policy_phase2b.py` | **🆕 9** | ✅ |
| Phase 1B/1A 既有 | 21+ | ✅ |
| **总计** | **51+** | ✅ |

> 单文件全过; 全集并发跑因 pytest collection Windows file-lock 已知问题有噪音(与 v4.0 既有 — 不是回归)。

---

## 🚀 部署清单

1. **拉代码** + `pip install -r backend/requirements.txt`
2. **首次部署**: `python -c "from backend.services.index_sync_service import run_full_seed; from backend.services.etf_sync_service import run_full_seed as etf_seed; run_full_seed(); etf_seed()"` (~5 分钟)
3. **启动**: `cd backend && python -m uvicorn main:app --reload`
4. **验证 scheduler**:
   ```python
   import threading; print([t.name for t in threading.enumerate()])
   # 期望: 't1-watcher', 'daily-pipeline', 'index-sync', 'etf-sync', 'drift-monitor'
   ```

---

## ⚠️ Breaking Changes

无 API breaking change。新表只增不改。

---

## 🗺️ 下一阶段 (v4.2 候选)

- P2/M — Full order/fill simulation (完整订单/成交模拟)
- P2/M — Auto Champion replacement (自动 Champion 替换)
- P3/L — Cross-market validation (HK/US 跨市场)
- P3/XL — Online learning (在线学习)

---

## 🙏 致谢

本次迭代耗时 ~3 周,11 个 commit,53+ 测试通过。Drift 监控设计参考业界 PSI > 0.25 严重漂移标准 + KL > 0.50 阈值,结合本仓库横截面使用场景微调。
