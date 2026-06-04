---
name: qa-stockai
description: Full QA sweep before pushing StockAI code. Run this after making changes — checks all 8 pages, API endpoints, charts, and common failure modes.
---

# QA StockAI

Push 前全站检查。覆盖 8 个页面、9 个 API、Canvas 图表、AI 对抗。每项只检查最常见的故障模式。

## 运行 QA

```bash
cd stocks

# 0. 确认服务在跑
curl -s http://localhost:3000/api/health || (
  cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 3000 &
  sleep 3
)

# 1. 冒烟测试 (9 个核心 API)
python .claude/skills/run-stockai/driver.py

# 2. 测试
python -m pytest tests/ -q
```

## 手动检查清单

每一项在浏览器打开，确认**没有 "加载中…" 卡住**。

### 1. 量化页 (quant.html)
```
打开: http://localhost:3000/quant.html
检查:
[ ] 个股透视区: 输 600519 点查看 → K线图清晰(不模糊) → 成交量柱可见
[ ] 悬浮 K线: 显示 开/高/低/收 + 涨跌幅
[ ] 悬浮成交量: 显示 日期 + 手数(如 7.65万手)
[ ] 指标面板: MA/MACD/KDJ/RSI 有数值不是 "--"
[ ] 因子行: PE/ROE/市值/行业 有数据
[ ] 风控 KPI: 没持仓时显示"无持仓数据"，不是 "--"
[ ] 相关性: 没持仓时显示"暂无数据"，不是"加载中…"
```

### 2. 持仓页 (index.html)
```
[ ] 页面加载完成，不卡在骨架屏
[ ] 没持仓时显示空状态引导，不报错
```

### 3. 大盘页 (market.html)
```
[ ] 15 个指数卡片全部渲染
[ ] 至少 7 个有实时价格(不含台湾/韩国/印度/新加坡)
[ ] 30 秒自动刷新不报错
```

### 4. 设置页 (settings.html)
```
[ ] 6 个 AI 供应商配置区全部渲染
[ ] MiniMax / DeepSeek / Claude / OpenAI / 小米 / 自定义
[ ] 填 Key → 保存 → 刷新 → Key 仍然在(脱敏)
```

### 5. AI 复盘 (review.html)
```
[ ] 页面加载，没持仓时显示"数据不足"而非白屏
```

### 6. 自选股 (watchlist.html)
```
[ ] 空列表时显示空状态
```

### 7. 交易记录 (transactions.html)
```
[ ] 空列表时显示空状态
```

### 8. AI 对话 (ai-assistant.html)
```
[ ] 对话界面加载
```

## 常见失败及修复

| 症状 | 修复 |
|------|------|
| Canvas 模糊 | CSS `width:100%` 和 HTML `width="900"` 不匹配 → 用 setupCanvas DPI 缩放 |
| Tooltip 在页面顶部 | 父元素缺 `position:relative` |
| "加载中…" 永远不消失 | 检查 init() 函数的 error 分支是否更新了该 UI 区域 |
| 成交量柱一片空白 | ETF 正常；个股 → 重启服务清缓存 |
| 三个 AI 选同一只 | 正常——人设随机分配，有时会撞。下次开局会换 |
