# StockAI v5.0-beta M7 — 55 因子完整接入

**发布日: 2026-08-05**
**代码基线: 235f20b**
**代号: v5.0-beta-M7**

> ⚠️ **灰度发布** — 默认 `REALTIME_USE_MINUTE_BARS=false`(保持 M6 行为),因子数从 30 升到 55 自动生效,无需额外开关。

---

## 🎯 一句话

把盘中因子接口 `/api/realtime/factor/{code}` 从 30 因子(alpha M1)升到 55 因子(factor_service.MINUTE_FACTOR_REGISTRY),复用 M6 的 5 元组分发与灰度开关,前端不变。

## ✨ 改动清单

| 能力 | v5.0-beta M6 | v5.0-beta M7 |
|---|---|---|
| `/api/realtime/factor/{code}` 因子数 | 30 (alpha) | **55 (完整)** |
| 数据源 (env=false) | 日级 (60 根, 2 元组) | 日级 (240 根, 5 元组) |
| 数据源 (env=true) | N/A (minute router 单独走) | 1m (240 根, 5 元组) + 自动 fallback |
| `data_source` 字段 | 无 | 新增 (`futu_1m` / `historical_daily_fallback`) |
| Cache 表 | `realtime_factor_cache` (30 因子) | **`realtime_factor_cache` (55 因子)** + `minute_factor_cache` 双表保留 |

## 📁 文件清单

### 改动 (3)
- `backend/services/realtime_factor_cache.py` — `fetch_recent_bars()` 拆 3 函数返 5 元组 + `compute_realtime_factors()` 转发到 55 因子
- `backend/routers/realtime_factor.py` — 解包 5 元组 + 新增 `data_source` 字段
- `backend/tests/conftest.py` — test_db fixture 加 `realtime_factor_cache` 表

### 新增 (1)
- `backend/tests/test_55_factors.py` — 20 个 mock 测试 (5 组)

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `test_55_factors.py` | 20/20 | 5 元组 4 + 分发 6 + 缓存 4 + router 4 + 降级 2 |
| `test_minute_bars.py` | 30/30 | M6 回归 (不破) |
| **合计** | **50/50** | |

## 🚀 启用步骤

```bash
# 1. 无需额外 env — M7 自动生效(alpha M1 接口因子数从 30 升 55)
# 2. 验证
curl http://localhost:3000/api/realtime/factor/600519 | jq '.factors | length'
# 期望: >= 55

curl http://localhost:3000/api/realtime/factor/600519 | jq '.data_source'
# 期望: "futu_1m" 或 "historical_daily_fallback"

# 3. (可选)启用 1m 数据源
echo "REALTIME_USE_MINUTE_BARS=true" >> backend/.env
# 重启后端

# 4. 回滚(如出问题)
# git revert <commit-hash> — 单 commit 回滚
```

## 🚧 已知限制

- alpha M1 接口旧 cache(30 因子)会在 5min TTL 后自然过期被 55 因子新值覆盖
- 前端 cards 因子数翻倍 (数据更全),UI 不主动调;后续可分组优化
- 单因子 `turnover_rate` 需 `total_shares` 基本面参数,盘中无 → 返 None
- `north_flow` / `inst_change` 需日级北向/机构数据 → 返 None

## 📌 下一步

- **M5**: WebSocket 推送(替换 5s 轮询)
- **M9**: 通知集成
- **M8**: 多用户 + 权限

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**
