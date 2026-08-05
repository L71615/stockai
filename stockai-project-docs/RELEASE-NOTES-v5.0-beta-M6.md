# StockAI v5.0-beta M6 — 分钟级 K 线接入

**发布日: 2026-08-05**
**代码基线: 9241c29**
**代号: v5.0-beta-M6**

> ⚠️ **灰度发布** — 默认 `REALTIME_USE_MINUTE_BARS=false`（保持 v5.0-alpha 行为），需手动启用。

---

## 🎯 一句话

把盘中因子数据源从日级 `historical_kline` 切到 1m 分钟级 `futu_raw_kline`，灰度可控，Futu 不可用时自动 fallback。

## ✨ 改动清单

| 能力 | v5.0-alpha | v5.0-beta M6 |
|---|---|---|
| 盘中因子数据源 | 日级 fallback (60 根) | **1m 分钟级 (240 根, 灰度开关)** |
| 切换策略 | 无 | `REALTIME_USE_MINUTE_BARS` env |
| Futu 失败处理 | N/A | 自动 fallback 日级 |
| `data_source` 字段 | 写死 `"historical_daily_fallback"` | 函数返回值（`futu_1m` / `historical_daily_fallback`） |

## 📁 文件清单

### 改动 (3)
- `backend/services/realtime_factor_minute.py` — `fetch_recent_bars()` 拆 3 函数 + if/else
- `backend/routers/realtime_factor_minute.py` — `data_source` 透传
- `backend/.env.example` — 加 `REALTIME_USE_MINUTE_BARS=false`

### 新增 (3)
- `backend/tests/__init__.py`
- `backend/tests/conftest.py` — 临时 DB fixtures
- `backend/tests/test_minute_bars.py` — 30 个 mock 测试

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `test_minute_bars.py` | 30/30 | 分支开关 4 + 数据 8 + 缓存 6 + 降级 6 + 边界 6 |

## 🚀 启用步骤

```bash
# 1. 确保 futu_raw_kline 有数据（盘中 ≥1 个 5min 周期）
cd backend && python scripts/sync_futu_data.py --mode intraday --scope watchlist+holdings

# 2. .env 启用
echo "REALTIME_USE_MINUTE_BARS=true" >> .env

# 3. 重启后端（env 立即生效，但建议重启窗口）
# Ctrl-C → python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload --env-file .env

# 4. 验证
curl http://localhost:3000/api/realtime/factor/600519/minute | jq .data_source
# 期望: "futu_1m"

# 5. 回滚（如出问题）
# echo "REALTIME_USE_MINUTE_BARS=false" >> .env
```

## 🚧 已知限制

- 跨频率一致性未验证（设计层面统一 qfq，需 staging 观察 1 周）
- 1 个 Windows asyncio teardown 崩溃可能（与 v5.0-alpha M2 同因，不影响测试本身 PASS）
- 未加 Prometheus 指标（YAGNI，先观察 log）

## 📌 下一步

- **M5**: WebSocket 推送（替换 5s 轮询）
- **M7**: 55 因子全部接入（依赖 M6）
- **M9**: 通知集成

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**
