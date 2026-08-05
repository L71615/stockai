# StockAI v5.0-beta M9 — 通知集成

**发布日: 2026-08-06**
**代码基线: b81b5c1**
**代号: v5.0-beta-M9**

> 🎉 **v5.0-beta 4 子模块全部完成** — M5 WS / M6 分钟 K 线 / M7 55 因子 / M9 通知集成
> 准实盘量化 5 件套(alpha M1-M4 + beta M5/M6/M7/M9)全部就位!

---

## 🎯 一句话

盘中信号触发后,通过企业微信 / Telegram / 邮件 3 渠道推送 Markdown 通知,5min dedup 避免骚扰,NOTIFY_ENABLED=false 即可关闭。

## ✨ 改动清单

| 能力 | v5.0-beta M7 | v5.0-beta M9 |
|---|---|---|
| 盘中信号通知 | ❌ 仅 log_signal | **微信 / Telegram / 邮件 推送** |
| 去重 | N/A | **5min TTL(同 code+strategy 不重推)** |
| 启用开关 | N/A | **复用 NOTIFY_ENABLED(env)** |
| 失败隔离 | N/A | **单 channel 失败不影响其他 + 不阻塞 scanner** |

## 📁 文件清单

### 改动 (2)
- `backend/services/notify_service.py` — 加 `send_signal(signal)` 函数(dataclass/dict 双兼容,格式化 Markdown)
- `backend/services/realtime_signal_scanner.py` — `_tick` 写 log_signal 后调 send_signal + 5min dedup + 异常隔离

### 新增 (1)
- `backend/tests/test_notify_signal.py` — 6 个 mock 测试

## 🔌 通知协议

### signal scanner 触发流程
```
1. _tick() 每 5s 扫一次(盘中)
2. scan_signals() 命中策略 → 返 RealtimeSignal
3. log_signal(sig) 写 realtime_signal_log 表 (始终执行)
4. _should_push(code, strategy) — 5min dedup 检查
5. send_signal(sig) 推送 Markdown 到 wechat/tg/email
   - NOTIFY_ENABLED=false 跳过 (notify_service 内部 gate)
   - 任一 channel 失败不阻塞其他 channel
6. _log_notification() 写 audit log (per channel)
```

### 推送内容 (Markdown)
```markdown
## 🟢 盘中信号触发

**600519** 海龟通道突破

- 方向: 买入
- 强度: +0.85
- 触发: 2026-08-06 10:30
- 原因: 突破 20 日新高 + 成交量放大 2.3x

---
⏰ 2026-08-06 10:30:15 · StockAI
```

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `test_notify_signal.py` | 6/6 | 触发推送 / 5min dedup / TTL 过期 / NOTIFY_ENABLED=false 跳过 / 失败隔离 / 多 channel 并行 |
| 回归(M5/M6/M7) | 55/55 | 不破 |
| **合计** | **61/61** | |

## 🚀 启用步骤

```bash
# 1. .env 配置至少一个渠道(已有的保持不变)
echo "NOTIFY_ENABLED=true" >> backend/.env
echo "WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx" >> backend/.env
# 或 Telegram:
echo "TELEGRAM_BOT_TOKEN=xxx" >> backend/.env
echo "TELEGRAM_CHAT_ID=xxx" >> backend/.env
# 或邮件:
echo "EMAIL_SENDER=you@qq.com" >> backend/.env
echo "EMAIL_PASSWORD=xxx" >> backend/.env
echo "EMAIL_RECEIVER=you@qq.com" >> backend/.env

# 2. 重启后端(scanner 会在 startup 启动)
# Ctrl-C → python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload --env-file .env

# 3. 盘中验证: 触发一只 watchlist + 持仓的策略命中 → 5s 内收到推送
# 4. 关掉: NOTIFY_ENABLED=false 即可(不删配置)
```

## 🚧 已知限制

- **不推送** factor / quote 变化(只推 signal) — 避免刷屏
- **不按策略细分开关** — 任何 strategy_id 触发都推(7 个默认策略)
- **失败不重试** — 单次失败只记 audit,下次同 (code+strategy) 仍 5min dedup
- **不批量汇总** — 每次触发一条 push,信号多时可能多条连发(实际 dedup 5min 内最多 1 条)

## 📌 下一步

- **v5.0-beta 全套完成** — 4/4 子模块
- 准实盘量化系统 (D1) 核心就位
- 后续可考虑: factor 推送、策略级开关、批量汇总

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**
