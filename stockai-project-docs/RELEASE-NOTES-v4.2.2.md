# StockAI v4.2.2 — patch (v4.2.1 后续 5 个 commit 打包)

**发布日: 2026-08-03**
**代码基线: 1a1e359**
**代号: v4.2.2-patch**

> ⚠️ **纯 patch** — 不引入新功能/新表/新接口,只修复 v4.2.1 之后的 5 个 commit。
> 已发布 v4.2.1 (`52be641` 之前的 tag),本 patch 是 v4.2.1 的小修补。

---

## 🎯 v4.2.2 一句话

把 v4.2.1 之后临时累积的 **2 个 bug fix + 1 个 feat 增强 + 2 个 docs 同步** 打包成 v4.2.2 patch tag,确保 release 树干净。

---

## 🐛 Bug Fixes

### 1. 因子 key 大小写不匹配 + scanner 默认策略 ID typo
**Commit**: `52be641`

| 项 | 修复前 | 修复后 |
|---|---|---|
| 前端 `factors.MA5` 大写访问 | 全部 `--` 显示 | 全部正常(后端返小写) |
| scanner 默认 `momentum` 策略 ID | yaml 里是 `momentum_leader`,扫不到任何信号 | 改成 `momentum_leader` |

**触发**: 用户在 `/live` 看到所有盘中因子卡片都是 `--`,scanner 跑不出任何信号。

### 2. scanner 默认策略列表扩展(3 → 7)
**Commit**: `a919100`

| 项 | 修复前 | 修复后 |
|---|---|---|
| scanner 默认策略数 | 3 (turtle_s1 / boll_mean / momentum_leader) | 7 (+ breakout_pullback / trend_continuation / gap_reversal / rsi_oversold) |
| 覆盖市场状态 | 只覆盖 突破 + 回归 + 动量 | 突破 + 回归 + 动量 + 趋势中途 + 反转 + 弱反转 |

**触发**: 600664(哈药股份)类强势股 RSI=76、ret_20d=+60% 不触发任何反转策略。扩展后即使强势股不触发,弱势股的反转机会也能扫到。

---

## ✨ Feat

### 3. `/live` 集成分钟级 55 因子卡片
**Commit**: `7fc9a6f`

| 项 | 修复前 | 修复后 |
|---|---|---|
| `/live` section 数 | 5 (PnL / 行情 / 信号 / 持仓 / 日级因子) | **6** (+ 分钟级因子) |
| 选中股票可见因子数 | 30 (factor_lab 日级) | 30 + 55 (factor_service 分钟级) |
| 百分比因子显示 | 0.04 (raw 比率) | **+4.47%** (自动 ×100 + %) |

**改动**:
- `frontend/src/app/live/page.tsx` — 加 `RealtimeMinuteFactorCard` import + 第 6 section
- `frontend/src/components/realtime-minute-factor-card.tsx` — `PERCENT_FACTORS` 集合(26 个百分比因子),自动格式化

**数据源**: `historical_kline` 日级 fallback (M2 阶段),`futu_raw_kline` 1m/5m 留 v5.0-rc。

**验证**:
- ✅ TS 类型校验通过
- ✅ `next build` ✓ Compiled successfully
- ✅ 后端 API 端到端测试 600664 → 55 因子中 41 个有值

---

## 📚 Docs

### 4. 三件套 + README.en.md 同步到 v4.2.1 + v5.0-alpha
**Commit**: `aa0e250`

| 文件 | 修复前 | 修复后 |
|---|---|---|
| `stockai-project-docs/README.md` badge | v4.1.1 | **v4.2.1** |
| `stockai-project-docs/README.md` TL;DR | v4.1 | v4.2.1 + v5.0-alpha 双主线 |
| `stockai-project-docs/README.md` T1 状态机 | `pending_buy→bought→sold` | **6 态机 `open/partial_filled/filled/closed/cancelled/rejected`** |
| `stockai-project-docs/README.md` 因子数 | 64 | **55** |
| `README.md`(根)版本历史表 | 只到 v4.1.1 | 加 v4.2.1 + v5.0-alpha + /live |
| `stockai-project-docs/README.en.md` | v4.1 英文版 | v4.2.1 + v5.0-alpha 英文版 |
| `INDEX.md` 目录树 | 只列 v4.0 + v4.1 release notes | 加 v4.2 / v4.2-m2 / v5.0 release notes |

### 5. 移除 docs/README.md 的 v4.0 ASCII 架构图
**Commit**: `1a1e359`

| 项 | 修复前 | 修复后 |
|---|---|---|
| `stockai-project-docs/README.md` | v4.0 ASCII 架构图(64 因子 / GP→ML→简报 / 影子组合) | 已删除 |
| 原因 | 描述 v4.0 时代架构,现已 v4.2.1 + v5.0-alpha(55 因子分钟级 / 实时行情 / 盘中信号),明显过期 | — |

---

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| v4.2 M1 `test_t1_watcher_n_state.py` | 30/30 | 6 态机 + transition() 守卫 |
| v4.2 M2 `test_factor_service_minute.py` | 25/25 | MINUTE_FACTOR_REGISTRY + compute_minute_factors + 5m TTL |
| v4.2 现有回归 | 212/212 | 含 v4.0 / v4.1 / v5.0-alpha |
| **总计** | **212/212** | patch 没改后端代码,全部回归通过 |

---

## 📁 文件清单(本 patch)

| 类别 | 文件 | 改动 |
|---|---|---|
| **bug fix** | `frontend/src/hooks/use-realtime-factor.ts` | 因子 key 小写化 |
| **bug fix** | `frontend/src/components/realtime-factor-card.tsx` | key + Date.now() 修复 |
| **bug fix** | `backend/services/realtime_signal_scanner.py` | typo + 默认策略扩 3→7 |
| **feat** | `frontend/src/app/live/page.tsx` | 第 6 section |
| **feat** | `frontend/src/components/realtime-minute-factor-card.tsx` | PERCENT_FACTORS |
| **docs** | 5 个 MD 文件 | 三件套 + 英文 README + INDEX |

---

## 📌 下一步

- **v5.0-beta M5** — WebSocket 推送(替换 5s 轮询,~1 周)
- **v5.0-beta M6** — 分钟级 K 线接入(`futu_raw_kline` 1m/5m)
- **v5.0-beta M8** — 多用户 + 权限分层

详见 [`2026-08-01-v5.0-strategy.md`](../2026-08-01-v5.0-strategy.md) + [`RELEASE-NOTES-v5.0.md`](RELEASE-NOTES-v5.0.md)。

---

## 📚 相关文档

- [`RELEASE-NOTES-v4.2.md`](RELEASE-NOTES-v4.2.md) — v4.2 M1 release notes
- [`RELEASE-NOTES-v4.2-m2.md`](RELEASE-NOTES-v4.2-m2.md) — v4.2 M2 release notes
- [`RELEASE-NOTES-v4.1.md`](RELEASE-NOTES-v4.1.md) — v4.1 release notes
- [`CHANGELOG.md`](../CHANGELOG.md) — 完整日志(含历史 v4.0/v4.1)
- [`CLAUDE.md`](../../CLAUDE.md) — 开发指引
- [`INDEX.md`](../../INDEX.md) — 项目入口

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>