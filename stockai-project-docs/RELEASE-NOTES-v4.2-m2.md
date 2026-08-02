# StockAI v4.2 M2 — 因子分钟级 (55 因子完整对齐)

**发布日: 2026-08-03**
**Commit: `5f20d93`**
**代号: v4.2 M2 — 配合 M1 打包 tag v4.2.1**

> **v4.2 M2 一句话**: 把 `factor_service` 升级支持分钟级数据 — 复用 55 个 `factor_xxx` 函数(签名已天然兼容 `list[float]`),新增 `MINUTE_FACTOR_REGISTRY` + `compute_minute_factors()` + `minute_factor_cache` 5m TTL 表 + REST `/api/realtime/factor/{code}/minute` + 前端 hook + 卡片。

---

## 🎯 为什么做这个

- **v5.0-strategy.md §3.4** M5「实时因子计算(55 因子分钟级 + 增量更新)」前置 — v5.0-rc M10 才需要
- **v5.0-alpha M2 现状**: factor_lab 30 因子 + `realtime_factor_cache` 已分钟级,但**只 30 因子** — v4.2 M1 用户要求补齐完整 55 因子
- **本次目标**: 把 factor_service 完整的 55 因子也接入分钟级调度,与 factor_lab 30 因子平行

---

## ✨ 关键交付

### 1️⃣ `MINUTE_FACTOR_REGISTRY` (55 因子)

在 `factor_service.py` 新增,4 元组 + 1 flag:

```python
MINUTE_FACTOR_REGISTRY: dict[str, tuple[Callable, bool, bool, bool, bool]] = {
    # (fn, needs_volume, needs_highs_lows, needs_opens, fn_volumes_only)
    "ma5":             (factor_ma5,             False, False, False, False),
    "vol_ma5":         (factor_vol_ma5,         True,  False, False, True),  # fn 只接 volumes
    "klen":            (factor_klen,            False, True,  True,  False),  # K 线形态
    ...
}
```

55 因子分类:

| 类别 | 数量 | 因子 |
|------|------|------|
| 价格 | 10 | ma5/10/20/60, price_position, high_low_ratio, close_open_ratio, typical_price, weighted_close, rsrs |
| 动量 | 6 | ret_5d/20d/60d, rsi_14, macd_signal, ma_disposition |
| 波动 | 10 | hist_vol_5d/20d, atr_14, amplitude_20d, downside_vol, boll_upper/lower/position, volatility_ratio, bb_width |
| 成交量 | 9 | vol_ma5/10/20, vol_std, vol_ratio, turnover_rate, obv_divergence, price_volume_corr, avg_amount |
| K线形态 | 4 | klen, kup, klow, ksft (v4.0 B1) |
| 价量 | 11 | roc, deviation, price_std, beta20, vroc, corr20, kmid, vwap, corr, cord, vol_change (v4.0 B2/B3) |
| 情绪 | 3 | strength, momentum_score, acceleration |
| 资金 | 2 | north_flow, inst_change (盘中无对应频段 → 算时 None) |

**与既有 FACTOR_REGISTRY (92-key) 区分**: 老的 92-key 注册表是 `dict[str, dict]`(status/done/pending 元数据),本 M2 新注册表是 `(fn, needs_*)` 5 元组 — 两者并存,各司其职。

### 2️⃣ `compute_minute_factors()` 入口

```python
def compute_minute_factors(
    *,
    code: str,
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
    factor_names: list[str] | None = None,
) -> dict[str, float | None]:
```

**复用所有 55 个 `factor_xxx` 函数**(签名 `list[float]`,算法对日级/分钟级天然兼容)。

| 边界 | 行为 |
|------|------|
| `closes < 5` | 返回 `{}` |
| 未知因子名 | 抛 `ValueError` |
| 大写 key (e.g. "MA5") | 自动归一化为 `"ma5"` |
| K 线因子无 highs/lows | 返回 None(不抛) |
| 量价因子无 volumes | 返回 None(不抛) |
| 单因子计算失败 | 返回 None + log debug(不阻塞) |

### 3️⃣ `minute_factor_cache` 表 + 5m TTL

```sql
CREATE TABLE minute_factor_cache (
    stock_code  TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    value       REAL,
    ts          REAL NOT NULL,
    PRIMARY KEY (stock_code, factor_name)
);
CREATE INDEX idx_mfc_code ON minute_factor_cache(stock_code);
CREATE INDEX idx_mfc_ts ON minute_factor_cache(ts);
```

**与 realtime_factor_cache 独立**(后者是 v5.0-alpha M2 的 30 因子用)— 后续 v5.0-rc 可能调 TTL(60s/300s/900s),两个频段分开 cache 更灵活。

### 4️⃣ REST API

```
GET  /api/realtime/factor/{code}/minute
GET  /api/realtime/factor/{code}/minute?names=ma5,ma20
POST /api/realtime/factor/{code}/minute/invalidate
GET  /api/realtime/factor/{code}/minute/factor-names
```

响应示例:
```json
{
  "code": "000725",
  "factors": {"ma5": -0.0206, "rsi_14": 33.89, "vol_ma5": -0.908, ...},
  "ts": 1754100000.0,
  "bar_count": 240,
  "cached_count": 55,
  "fresh_count": 0,
  "data_source": "historical_daily_fallback"
}
```

### 5️⃣ 前端 hook + 组件

| 文件 | 内容 |
|------|------|
| `frontend/src/hooks/use-realtime-minute-factor.ts` | `useRealtimeMinuteFactor` SWR 30s + `MINUTE_FACTOR_GROUPS` 8 组分类 |
| `frontend/src/components/realtime-minute-factor-card.tsx` | 4 组核心(价格/动量/波动/成交量) + 数据源标识 + DESIGN.md 合规(暗色 + `rounded-none` + `tabular-nums` + Tabler Icons) |

**未集成到 `/live` 页面** — 留 v5.0-beta M8 前端整合阶段。

---

## 📁 文件清单

### 改

| 文件 | 改动 |
|---|---|
| `backend/database.py` | `minute_factor_cache` DDL + 2 索引 |
| `backend/services/factor_service.py` | `MINUTE_FACTOR_REGISTRY` (55 因子) + `compute_minute_factors()` |
| `backend/main.py` | 注册新 router |
| `database/schema.sql` | PG/MySQL 兼容的 minute_factor_cache DDL |
| `database/schema.sqlite.sql` | SQLite 同上 + 注释 |

### 新

| 文件 | 内容 |
|---|---|
| `backend/services/realtime_factor_minute.py` | 缓存 CRUD + `compute_minute_factors_with_cache` + `fetch_recent_bars` + `all_factor_names` (~160 LOC) |
| `backend/routers/realtime_factor_minute.py` | REST 3 端点 (~70 LOC) |
| `scripts/migrations/v4.2_m2_add_minute_factor_cache.sql` | dev DB apply |
| `tests/test_factor_service_minute.py` | 25 测试 |
| `frontend/src/hooks/use-realtime-minute-factor.ts` | SWR hook + 因子分组 |
| `frontend/src/components/realtime-minute-factor-card.tsx` | 4 组因子卡片 |

**预计改动量**: ~700 LOC(后端 ~450 + 前端 ~150 + 测试 ~100)

---

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `tests/test_factor_service_minute.py` (新) | **25/25** | 注册表 + 计算 + 缓存 + REST + 大写兼容 |
| `tests/test_realtime_factor.py` (v5.0-alpha 回归) | 17/17 | 30 因子分钟级 0 破坏 |
| `tests/test_alpha158_batch1.py` (v4.0 B1 回归) | 32/32 | K 线形态因子 0 破坏 |
| `tests/test_alpha158_batch2_3.py` (v4.0 B2/B3 回归) | 28/28 | 价量相关因子 0 破坏 |
| `tests/test_factor_service.py` (v4.1.1 回归) | 25/25 | compute_all_factors 0 破坏 |
| `tests/test_t1_watcher*.py` (v4.2 M1 回归) | 60/60 | M1 N 态机 0 破坏 |
| `tests/test_pipeline_source_field.py` (v4.1.1 回归) | 4/4 | source/proposal_id 0 破坏 |
| **总计 v4.2 M2** | **212/212** | (含 187 现有回归) |

**E2E 验证**:
- `fetch_recent_bars("000725")` 拉 240 根 K 线,5 个序列齐全
- `compute_minute_factors_with_cache` 6 因子全有值(ma5=-0.0206 / rsi_14=33.89 / vol_ma5=-0.908)
- cache 5m 命中
- `invalidate` 清空 cache

---

## 📐 关键设计要点

### `fn_volumes_only` 第 5 字段

发现 `factor_vol_ma5(volumes)` 等几个量因子的签名只接 `volumes`,不接 `closes`。在 4 元组基础上加第 5 个 `fn_volumes_only: bool` 标记,计算入口据此区分参数构造:

```python
if fn_volumes_only:
    args = [vols]                              # factor_vol_ma5(volumes)
else:
    args = [closes]
    if needs_vol:
        args.append(vols)
    if needs_hilo: args.append(hi); args.append(lo)
    if needs_open: args.append(op)
raw = fn(*args)
```

### 与 factor_lab.FACTOR_REGISTRY (30 因子) 共存

- factor_lab 30 因子: `np.ndarray` 签名,无 OHLC,无 K 线形态,用于 IC 分析 / 散点图
- factor_service 55 因子: `list[float]` 签名,完整含 OHLC,用于选股/回测/生产

两套并存,各司其职。**M2 走 factor_service 这条新路径**,不动 factor_lab 30 因子路径。

### 数据源: historical_kline 日级 fallback

```python
def fetch_recent_bars(code: str, limit: int = 240):
    rows = query_all(
        """SELECT trade_date, open, high, low, close, volume
           FROM historical_kline WHERE stock_code = ?
           ORDER BY trade_date DESC LIMIT ?""",
        (code, limit),
    )
    rows = list(reversed(rows))
    return closes, highs, lows, opens, volumes
```

**v5.0-rc M11** 切 `futu_raw_kline`(1m / 5m)。REST 响应加 `data_source` 字段标记,前端卡片用 `IconCircleDot` 颜色区分(fallback 黄色 / 真实 绿色)。

### cache 写策略

`set_cached_factor(value=None)` 不写库(沿用 realtime_factor_cache 模式) — 失败的因子不会复活,必须重算并成功才覆盖。

---

## 🚧 已知限制 / 不在本 M2 范围

| 项 | 现状 | 后续 |
|---|---|---|
| 数据源 | `historical_kline` 日级 fallback (240 根) | v5.0-rc M11 切 `futu_raw_kline` 1m/5m |
| 增量更新 | 5m TTL 命中(每根新 bar 重新覆盖同一窗口) | v5.0-rc M10 |
| TTL | 固定 300s | v5.0-rc 可调(60s/300s/900s) |
| `/live` 页面集成 | 未集成 | v5.0-beta M8 |
| 多用户 | 单 admin (alpha 沿用) | v5.0-beta M8 |
| notify 集成 | 无(缓存算因子不通知) | v5.0-beta M9 |

---

## 🛣 下一步

- **v4.2 收尾**: 文档同步 + git tag v4.2.1(M1+M2 打包)
- **v5.0-beta**: M5 WS 推送 / M6 分钟级 K 线 / M7 55 因子接入(已做) / M8 多用户 / M9 通知集成

---

## 📚 相关文档

- [`RELEASE-NOTES-v4.2.md`](RELEASE-NOTES-v4.2.md) — v4.2 M1 release notes
- [`CHANGELOG.md`](CHANGELOG.md) — 完整日志
- [`2026-08-01-v5.0-strategy.md`](2026-08-01-v5.0-strategy.md) — v5.0 战略(M5 提到 55 因子分钟级)
- [`2026-08-01-v5.0-alpha-plan.md`](../../.gstack/projects/L71615-stockai/ceo-plans/2026-08-01-v5.0-alpha-plan.md) — v5.0-alpha 实施计划

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**