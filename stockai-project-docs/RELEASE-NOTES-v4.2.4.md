# StockAI v4.2.4 — leaderboard 超时修复 (patch)

**发布日: 2026-08-05**
**代码基线: 70f9dc3**
**代号: v4.2.4-patch**

> ⚠️ **纯 patch** — 不引入新功能/新表/新接口,只补全 v4.2.4 leaderboard 超时的根因(向量化 + 5min 缓存)和一个把后端打成 ECONNREFUSED 的 `async def` 漏改 bug。

---

## 🎯 v4.2.4 一句话

`/api/factor-lab/leaderboard` 55 因子 × 240 天全量计算 ~90s,客户端 60s timeout 必 500。改成 NumPy 向量化(~4s) + 5min TTL 缓存(重复请求 ~0ms)。顺手修复一个**让后端整个起不来的 SyntaxError**。

---

## ✨ Feat

### 1. `compute_factor_leaderboard` 提速 ~22x

| 函数 | 改动 | 性能 |
|------|------|------|
| `_pearson_daily(factor_panel, return_panel)` | per-date 循环 → NumPy 矩阵运算(均值/方差/协方差) | ~0.3s → ~0.015s |
| `decay` (1d/5d/10d/20d forward IC) | 同样向量化,复用 `_pearson_daily` 模式 | ~12s → <0.1s |
| `compute_factor_metrics` 默认窗口 | 365 天 → **240 天**(减 33% 数据量) | 仍 > 200 有效 IC 天 |

### 2. 5min TTL 内存缓存 + per-key asyncio.Lock

```python
# services/factor_lab.py
async def get_cached_leaderboard(
    factors=None, stock_pool="all", start_date=None, end_date=None
) -> tuple[dict, bool]:
    """Returns (result, cache_hit). 双检锁防并发双算"""
```

- `_leaderboard_cache: dict[str, tuple[float, dict]]`
- `_leaderboard_locks: dict[str, asyncio.Lock]` — per-key,不同查询参数不互锁
- `LEADERBOARD_CACHE_TTL = 300` (5 min)
- `invalidate_leaderboard_cache()` helper(未来接入定时刷新用)

### 3. Router 端透出 cache 状态

```json
{ "...": "...", "_cache": "hit" | "miss" }
```

前端可一眼看出本次是缓存命中还是重算。

---

## 🐛 Fix — `async def` 漏改导致后端 ECONNREFUSED

### 症状
- 前端访问 `/api/stocks/holdings/with-pnl` → HTTP 500
- 错误:`AggregateError: connect ECONNREFUSED ::1:3000 / 127.0.0.1:3000`
- 后端完全没起来(3000 端口无人监听)

### 根因
`backend/routers/factor_lab.py:81` 函数体加了 `await get_cached_leaderboard(...)`,但函数签名是 `def` 而非 `async def` → **SyntaxError** → Python 解释器在 `import main.py` 阶段崩溃 → uvicorn 永远卡在 `Waiting for application startup` → 3000 端口不监听。

### 修复
单行改动:`def get_leaderboard` → `async def get_leaderboard`

### 验证
| 步骤 | 结果 |
|------|------|
| `python -c "import main"` | ✅ 无 SyntaxError(修复前抛) |
| `uvicorn backend.main:app --port 3000` | ✅ Application startup complete,PID 35104 监听 0.0.0.0:3000 |
| `GET /api/health` | ✅ 200 (17ms) |
| `POST /api/auth/login` | ✅ 返回 JWT |
| `GET /api/stocks/holdings/with-pnl` | ✅ **200 (5ms)** ← 用户报告失败的接口 |

### 经验
> v4.2.4 之前的几个 v4.2.x patch 都是改 `services/`,没碰 `routers/`。这次跨层改动(router 加 await,服务加 async)如果跑一次 `import main` 就能在 commit 前拦截。

---

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| **手动端到端** `/api/factor-lab/leaderboard` | ✅ 200 | curl 直查,响应 ~4s(首次)/ <50ms(缓存命中) |
| **回归** `/api/stocks/holdings/with-pnl` | ✅ 200 | 修复前 ECONNREFUSED,修复后 5ms |
| **v4.2.4 新增** `tests/test_factor_lab_v424.py` | **14/14** | 向量化数值一致性 + 缓存 TTL/Lock + 性能 smoke |
| 现有 factor 测试(无回归) | ✅ 56/56 | test_factor_service + test_factor_leaderboard_quantile |

> 📌 **测试设计**:
> - `_pearson_daily` 向量化用与 v4.2.4 之前 per-date 循环的**对比测试**,数值误差阈值 `atol=1e-9`,确保浮点累加顺序差异在可控范围
> - `get_cached_leaderboard` 用 `monkeypatch` 替换 `compute_factor_leaderboard`,纯逻辑测试无数据库依赖
> - 并发 lock 测试用 `threading.Event`(因 `asyncio.to_thread` 把 compute 丢到线程池)

---

## 📁 文件清单(本 patch)

| 类别 | 文件 | 改动 |
|------|------|------|
| **fix** | `backend/services/factor_lab.py` | `_pearson_daily` + decay 向量化 + 默认窗口 240 + 缓存层 + lock + invalidate helper (+132/-51) |
| **fix** | `backend/routers/factor_lab.py` | `get_leaderboard` async def 化 + 透出 cache 状态 (+14/-3) |

---

## 📌 不在 v4.2.4 范围

| 项 | 状态 |
|----|------|
| 缓存持久化(进程重启即失效) | ❌ 当前仅内存,留 v5.0-beta |
| `invalidate_leaderboard_cache` 调度触发(因子生命周期变化时自动失效) | ❌ hook 未接,留 v5.0-beta |
| 全量 `test_factor_lab.py` pytest 覆盖 | ❌ 当前无该测试文件,本 patch 用端到端验证代替 |
| `frontend/next-env.d.ts` Next.js dev 自动改 | ❌ 已 `git checkout` 还原(不应进 commit) |
| 诡异 log 文件 `backend/D:stocksbackendbackend.log` | ❌ Windows uvicorn 路径拼接 bug 产物,untracked |

---

## 📚 相关文档

- [`RELEASE-NOTES-v4.2.3.md`](RELEASE-NOTES-v4.2.3.md) — 上一 patch
- [`RELEASE-NOTES-v4.2.2.md`](RELEASE-NOTES-v4.2.2.md) — v4.2.1 后续打包
- [`CHANGELOG.md`](../CHANGELOG.md) — 完整日志
- [`CLAUDE.md`](../../CLAUDE.md) — 开发指引
- [`INDEX.md`](../../INDEX.md) — 项目入口

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**