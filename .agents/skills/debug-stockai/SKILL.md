---
name: debug-stockai
description: Diagnose StockAI issues — API returns empty data, frontend stuck on loading, charts not rendering, server not picking up code changes. Use when something "doesn't work" but no clear error.
---

# Debug StockAI

系统性诊断 StockAI 的常见故障。今天踩过的坑都在这里。

## 诊断流程

按顺序排查，90% 的问题在前两步就能定位。

### Step 1: 服务器有没有加载最新代码？

**症状：** API 返回空数据，但直接调函数有数据。这是今天踩最多的坑。

```bash
# 清除所有缓存
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null

# Kill 并重启
pkill -f "uvicorn" 2>/dev/null
sleep 2
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload &

# 等待就绪后验证
curl -s "http://localhost:3000/api/health"
```

**如果还不行 → 绕过缓存，直接测函数：**

```bash
python -c "
import sys; sys.path.insert(0,'backend')
from routers.quant import stock_insight
r = stock_insight('600519', 5)
print('volumes:', len(r['kline']['volumes']))
"
```

直接调用有数据但 API 返回空 → 代码是对的，服务器加载了旧代码 → 重启时确认所有相关 `.py` 文件的修改时间。

### Step 2: 前端渲染问题？

**症状：** API 返回了正确数据，但页面显示空白 / "加载中…" / 无内容。

```
排查顺序:
1. Canvas 图表:  检查 CSS height 是不是 auto → 换成固定 px
2. Tooltip 漂移: 检查父元素有没有 position:relative
3. "加载中…" 卡住: 打开对应 HTML 的 init 函数 → 检查 error 分支有没有更新 UI
4. 成交量不显示: 确认 data.kline.volumes 不是空数组 → API 问题回 Step 1
```

**Canvas 渲染检查清单:**
```
- CSS height 不能是 auto，必须显式 px
- Canvas 的 HTML width/height 和 CSS width/height 要一致，否则模糊
- 高分屏需要 devicePixelRatio 缩放
- 深色背景先画 fillRect('#141722')，否则条形图透明不可见
```

### Step 3: 数据源问题？

**症状：** 某个股票/ETF 的 K 线或成交量查不到。

```bash
# 逐一测试数据源
python -c "
import sys; sys.path.insert(0,'backend')
from services.baostock_adapter import get_kline as bs
from services.akshare_adapter import get_kline as tx

code = '000725'
print('Baostock:', 'OK' if 'error' not in bs(code,5) else bs(code,5)['error'])
print('Tencent:', 'OK' if 'error' not in tx(code,5) else tx(code,5)['error'])
"
```

| 数据源 | 覆盖范围 | 有 volumes? |
|--------|---------|-------------|
| Baostock | A股个股(不含ETF) | ✅ |
| 腾讯 K 线 | A股+ETF | ❌ |
| 腾讯行情 | A股+ETF实时价 | N/A |
| 新浪港股 | 5位0开头港股 | N/A |

**ETF 成交量永远为空**——这是已知限制，不是 bug。不要花时间排查 510050/159915 的成交量。

### Step 4: 数据库问题？

**症状：** 量化页 KPI 全 "--"、相关性"加载中…"、AI 复盘显示"数据不足"。

```
根因: 数据库没有持仓数据 (0 holdings)。
这不是 bug，是设计如此。
解决: 去持仓页添加 3-5 只股票。
```

### Step 5: AI 配置问题？

**症状：** AI 对抗开局失败、AI 解读无响应。

```
排查:
1. curl http://localhost:3000/api/settings/ai-configs → 检查 Key 是否已保存
2. 多供应商模式: 每个 AI 的 Key 是独立存储的
3. DeepSeek/小米是新增供应商，确认 base URL 正确
```

## 今天踩过的最坑记录

1. **服务器热重载不靠谱** — `uvicorn --reload` 改了文件不生效，清 `__pycache__` 也没用。最终方案：绕过 `fetch_kline`，端点内直接调 Baostock。

2. **Canvas `height:auto` 塌缩** — CSS 给 canvas 设 `height:auto` 会让元素高度变为 0，柱状图执行了但看不见。改成 `height:70px` 立刻正常。

3. **`init()` 提前 return 不更新 UI** — 量化页 `portfolio-risk` 返回 error 时，代码 return 了但没有更新相关性区域的 HTML。永远在每个 error 分支更新所有 UI 区域。

4. **三个 AI 选同一只股票** — 不是股票好，是提示词完全一样。给每个 AI 随机分配不同的"人设"（价值/成长/逆向/动量），选股立刻分散。
