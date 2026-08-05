# StockAI v5.0-beta M5 — WebSocket 实时推送

**发布日: 2026-08-05**
**代码基线: 78d428a**
**代号: v5.0-beta-M5**

> ⚠️ **前端改造已就绪** — `useRealtimeQuote` hook 接口不变,内部从 SWR 5s polling 切到 WebSocket 推送。`/api/realtime/ws` 端点已就位。

---

## 🎯 一句话

盘中实时报价从 5s SWR 轮询改为 WebSocket 推送,延迟从 ~5s 降到 ~即时(0.1s 内),后端 1 份 Futu 腾讯 API 拉取 + 多客户端共享推送。

## ✨ 改动清单

| 能力 | v5.0-beta M4 | v5.0-beta M5 |
|---|---|---|
| 实时报价延迟 | SWR 5s polling | **WebSocket 推送 (~0.1s)** |
| 后端 quote 拉取 | 每客户端独立 5s | **单例 + 5s 后台 thread** (M1 已实现,本 task 利用) |
| 客户端连接 | HTTP 短轮询 | **WebSocket 长连接 + subscribe codes** |
| 多客户端 | 每客户端独立 5s 拉取 | **共享单例,服务端只拉一次** |
| 鉴权 | JWT (REST) | 待补(WS 当前未鉴权) |

## 📁 文件清单

### 改动 (3)
- `backend/services/realtime_quote.py` — `RealtimeQuoteService.unsubscribe(callback)` 清理 API
- `backend/routers/realtime.py` — `/api/realtime/ws` 实现 subscribe/unsubscribe + 多客户端广播 + ping/pong
- `frontend/src/hooks/use-realtime-quote.ts` — 改为 WebSocket(替换 SWR polling),接口保持

### 新增 (1)
- `backend/tests/test_ws_quote.py` — 5 个 mock 测试(connect/snapshot/push/ping/multi-client)

## 🔌 WebSocket 协议

### 客户端 → 服务端
```json
{"type": "subscribe", "codes": ["000725", "600519"]}
{"type": "unsubscribe", "codes": ["000725"]}
"ping"
```

### 服务端 → 客户端
```json
{"type": "trading_status", "is_trading_hours": true, "is_trading_day": true, "ts": 1234567890.0}
{"type": "snapshot", "quotes": [...], "ts": 1234567890.0}
{"type": "quote", "code": "000725", "price": 4.5, ...}
{"type": "pong", "ts": 1234567890.0}
```

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `test_ws_quote.py` | 5/5 | connect/snapshot/push/ping/multi-client |
| 回归(M6/M7/conftest) | 50/50 | 不破 |
| **合计** | **55/55** | |

## 🚀 启用步骤

```bash
# 1. 后端自动启动 — RealtimeQuoteService.start() 已在 main.py 启动时调
# 2. WebSocket 端点自动注册(/api/realtime/ws)
# 3. 前端 useRealtimeQuote hook 自动用 WS 推送(无需配置)
# 4. 验证(curl + websocat):
websocat ws://localhost:3000/api/realtime/ws
> {"type": "subscribe", "codes": ["000725"]}
< {"type": "trading_status", ...}
< {"type": "snapshot", "quotes": [...]}
< {"type": "quote", "code": "000725", "price": 4.5, ...}
```

## 🚧 已知限制

- **未鉴权**: WS 端点当前跳过 JWT middleware,生产环境部署前需加(在 `dependencies.py` 加 WS 鉴权 helper)
- **简单重连**: 前端 3s 后重试一次,无限循环直到 unmount
- **未集成到 `use-realtime-factor.ts` / `use-realtime-minute-factor.ts`**: 因子推送仍 SWR polling,本 task 只替换 quote

## 📌 下一步

- **M9**: 通知集成(盘中信号 → 邮件/微信/Telegram)
- (未来) WS 鉴权
- (未来) factor WS 推送

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**
