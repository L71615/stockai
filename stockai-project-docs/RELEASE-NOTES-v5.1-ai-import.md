# StockAI v5.1 — AI 录入交易

**发布日: 2026-08-06**
**代号: v5.1-ai-import**

> 🎯 **解决用户痛点** — "每次添加减少持仓都好麻烦"。粘贴交易文本 → AI 解析 → 一键批量入库

---

## 🎯 一句话

持仓页顶部新增"AI 录入交易"面板,粘贴交易文本(支持 CSV 模板 + 自然语言)→ AI 解析 → 预览 → 批量入库,告别逐笔手动录入。

---

## ✨ 改动清单

| 能力 | 之前 | v5.1 |
|---|---|---|
| 录入单笔持仓 | 手动逐字段填表单 | 粘贴 1 行 CSV |
| 录入多笔持仓 | 重复填表单 N 次 | 粘贴 N 行,AI 批量入库 |
| 字段记忆 | 无 | 自动识别代码/方向/数量/价格/日期 |
| 批量校验 | 无 | 单批上限 50 笔 + 前置持仓校验 |
| 失败隔离 | 一笔失败 = 全部丢失 | 单事务回滚保护 |

---

## 📋 模板格式

```csv
代码,方向,数量,价格,日期
600519,买入,100,1680.00,2026-08-06
000725,卖出,500,4.20,2026-08-06
```

**AI 自动处理**:
- 方向: `买入`/`buy`/`Buy`/`BUY`/`买了` 都识别为 `buy`
- 数量: `"100股"` → 100, `"1手"` → 100 (A 股 1 手 = 100 股)
- 价格: `1680` / `1,680.00` / `@1680` / `1680元` 都识别为 1680.0
- 日期: `2026-08-06` / `今天` / `昨天` 都识别
- 注释: `#` 开头的行和空行自动跳过

---

## 🔄 工作流

```
1. 用户粘贴交易文本(任意位置,任意格式)
   ↓
2. 点 "AI 识别"
   ↓ POST /api/ai/parse-transactions
3. 后端:
   - 过滤空行/注释/表头
   - AI (Claude Haiku 4.5) 解析 → 结构化 JSON
   - 后置校验(股票代码 + 卖出 ≤ 持仓)
   ↓
4. 前端预览:
   ┌──────────────────────────────────┐
   │ ✅ 600519 买入 100股 ¥1680      │ ✓
   │ ✅ 000725 卖出 500股 ¥4.20      │ ⚠️ 持仓仅 300 (用户可继续)
   │ ❌ 999999 买入 100股 ¥10        │ ✗ 代码不存在
   └──────────────────────────────────┘
   ↓
5. 用户检查 / 删除多余行
   ↓
6. 点 "确认入库"
   ↓ POST /api/transactions/bulk
7. 单事务批量写 → 持仓自动刷新 → 通知
```

---

## 📁 文件清单

### 新增 (5)
- `backend/services/ai_parse_transactions.py` — AI 解析服务 (Claude Haiku + tools + 后置校验)
- `backend/routers/ai_parse.py` — `/api/ai/parse-transactions` 端点
- `backend/tests/test_ai_parse.py` — 6 个测试
- `frontend/src/components/ai-transaction-importer.tsx` — AI 录入面板组件
- `stockai-project-docs/RELEASE-NOTES-v5.1-ai-import.md` — 本文档

### 改动 (4)
- `backend/main.py` — 注册 `ai_parse` 路由
- `backend/routers/transactions.py` — 新增 `/api/transactions/bulk` 端点(单事务 + 前置持仓校验)
- `frontend/src/app/page.tsx` — 集成 AI 录入面板到持仓概览顶部
- `frontend/src/lib/api-types.ts` — 新增 `AIParsedTransaction` / `BulkTransactionResponse` 等类型

---

## 🔌 API 协议

### POST /api/ai/parse-transactions
```json
// Request
{ "text": "代码,方向,数量,价格,日期\n600519,买入,100,1680.00,2026-08-06" }

// Response
{
  "template": "代码,方向,数量,价格,日期\n...",
  "transactions": [
    {"code":"600519","stock_name":"贵州茅台","direction":"buy","quantity":100,"price":1680.0,"date":"2026-08-06"}
  ],
  "errors": [
    {"line":3,"raw":"999999","reason":"股票代码 999999 不存在或本地无数据"}
  ],
  "summary": {"input_lines":3,"parsed_ok":1,"parse_failed":0,"validation_failed":1}
}
```

### POST /api/transactions/bulk
```json
// Request
{
  "transactions": [
    {"stock_code":"600519","direction":"buy","quantity":100,"price":1680.0,"traded_at":"2026-08-06"},
    {"stock_code":"000725","direction":"sell","quantity":200,"price":4.2,"traded_at":"2026-08-06"}
  ]
}

// Response
{
  "message": "成功入库 2 笔",
  "inserted": [{"id":1,"stock_code":"600519",...}],
  "holding_updates": {
    "600519": {"stock_code":"600519","quantity":100,"cost_price":1680.0},
    "000725": {"stock_code":"000725","quantity":100,"cost_price":4.0}
  }
}
```

---

## 🛡️ 安全护栏

| 检查 | 行为 |
|------|------|
| 输入长度 > 4000 字符 | 拒绝 |
| 行数 > 50 | 拒绝 |
| 股票代码不在 `stocks` 表 | 该行标 ❌,其他行继续 |
| 卖出 > 当前持仓 | 该行标 ❌ |
| 卖出 > (当前持仓 + 本批买入) | 该行标 ❌ |
| 价格为 0 或负 | 该行标 ❌ |
| 数量非正整数 | 该行标 ❌ |
| 日期格式错误 | 该行标 ❌ |
| 单事务中任意失败 | 全部回滚(不留半截) |
| 单批上限 50 笔 | 超限拒绝 |

---

## ✅ 测试验收

| 测试套件 | 通过 | 备注 |
|---------|------|------|
| `test_ai_parse.py` | 6/6 | 模板解析 / 注释过滤 / 代码校验 / 持仓校验 / 批量成功 / 部分失败回滚 |
| 回归(M5/M6/M7/M9) | 55/55 | 不破 |
| **合计** | **61/61** | |

---

## 🚀 使用步骤

```bash
# 1. 配置 AI Key(任一即可,Claude Haiku 4.5 最便宜快)
echo "ANTHROPIC_API_KEY=sk-ant-xxx" >> backend/.env

# 2. 重启后端
cd backend && python -m uvicorn main:app --reload --env-file .env

# 3. 浏览器打开 http://localhost:3001
# 4. 持仓页顶部 → "AI 录入交易" → 粘贴交易 → 识别 → 入库
```

---

## 🚧 已知限制

- **不接券商 API** — 仍然手动从券商 APP 复制交易文本(实盘 API 接入门槛极高,不推荐)
- **不批量 OCR** — 需要纯文本输入(截图识别是后续工作)
- **不识别分红/银转账** — 只支持 `buy`/`sell` 两种方向
- **不重复合并去重** — 同代码同方向同日会创建多笔(用户可手动删除)

---

## 📌 下一步

- **v5.1 完成** — AI 录入交易上线
- **下一步**: 试跑 1 周收集反馈 + 优化模板(常见格式自适应)
- **可选**: OCR 截图识别(技术成本高,二期)

---

**Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>**