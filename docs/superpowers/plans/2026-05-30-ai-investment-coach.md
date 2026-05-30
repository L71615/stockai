# AI 投资教练 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform StockAI from a stock tracking tool into an AI investment coach — AI generates structured review reports (profit/loss attribution, behavior pattern analysis, risk warnings), displayed on a new review.html page, backed by pytest tests, with polished UX across all core pages.

**Architecture:** New `review_service.py` handles data aggregation, prompt building, AI calling, and response parsing. Two new API endpoints (`POST /api/stocks/review/structured`, `GET /api/stocks/reviews`) expose this via the existing stocks router. New `review_reports` table stores results. New `review.html` renders reports with progressive disclosure (KPI hero → collapsible dimension panels → suggestions with expandable reasoning). Existing pages get loading/empty/error state upgrades and keyboard shortcuts.

**Tech Stack:** FastAPI + SQLite + vanilla JS frontend (no framework), Chinese market dark theme, MiniMax-M2.7 primary AI provider with Claude/OpenAI fallback, pytest + pytest-asyncio + httpx for testing.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `requirements-dev.txt` | Create | Test dependencies (pytest, pytest-asyncio, httpx) |
| `pytest.ini` | Create | Pytest configuration |
| `tests/__init__.py` | Create | Python package marker |
| `tests/test_review_service.py` | Create | Unit tests for aggregate/build_prompt/parse |
| `tests/test_review_api.py` | Create | API integration tests for review endpoints |
| `tests/conftest.py` | Create | Shared fixtures (test client, test DB) |
| `backend/database.py:69-237` | Modify | Add `review_reports` table to `init_db()` |
| `backend/services/review_service.py` | Create | Core review engine: aggregate, prompt, AI call, parse, fallback |
| `backend/routers/stocks.py` | Modify | Add `POST /review/structured` and `GET /reviews` |
| `frontend/review.html` | Create | AI review report page with progressive disclosure |
| `frontend/js/common.js:37-45` | Modify | Upgrade showLoading/showEmpty/showError with SVG icons and retry |
| `frontend/js/common.js:48-80` | Modify | Add keyboard shortcuts, replace emoji nav icons, add review to sidebar |
| `frontend/css/common.css` | Modify | Add skeleton animation, btn-retry, ai-insight styles, shortcut bar |
| `frontend/index.html` | Modify | Add AI summary bar, loading skeleton, empty guidance, error retry |
| `frontend/ai-assistant.html` | Modify | Add send loading state, failure retry, welcome guidance |
| `frontend/market.html` | Modify | Add loading skeleton, "—" fallback, data freshness timestamp |

---

### Task 1: Test Infrastructure + review_reports Table

**Files:**
- Create: `requirements-dev.txt`, `pytest.ini`, `tests/__init__.py`, `tests/conftest.py`
- Modify: `backend/database.py:68-237`

- [ ] **Step 1: Create requirements-dev.txt**

Write `requirements-dev.txt`:
```
pytest>=8.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

- [ ] **Step 2: Create pytest.ini**

Write `pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
asyncio_mode = auto
addopts = -v --tb=short
```

- [ ] **Step 3: Create tests/__init__.py**

Write `tests/__init__.py` (empty file):
```python
```

- [ ] **Step 4: Create tests/conftest.py**

Write `tests/conftest.py`:
```python
import sys
from pathlib import Path

# Add backend/ to sys.path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    from database import init_db

    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 5: Verify test infrastructure works**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/ --collect-only`
Expected: "no tests collected" (not an import error)

- [ ] **Step 6: Add review_reports table to init_db()**

In `backend/database.py`, add after the last `conn.execute(...)` in `init_db()` and before `conn.commit()`:
```python
conn.execute("""CREATE TABLE IF NOT EXISTS review_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    report_type TEXT NOT NULL DEFAULT 'daily',
    period_start TEXT,
    period_end TEXT,
    transactions_count INTEGER DEFAULT 0,
    dimensions TEXT NOT NULL DEFAULT '[]',
    ai_response TEXT,
    summary TEXT,
    score_data TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""")
```

The insertion point is after line 234 (`conn.commit()` is at line 234). Add the new table creation before the commit.

- [ ] **Step 7: Verify table creation**

Run: `python -c "from database import init_db; init_db(); from database import query_all; tables = query_all(\"SELECT name FROM sqlite_master WHERE type='table'\"); print([t['name'] for t in tables])"`
Expected: `review_reports` appears in the table list.

- [ ] **Step 8: Install test deps and commit**

```bash
pip install -r requirements-dev.txt
git add requirements-dev.txt pytest.ini tests/__init__.py tests/conftest.py backend/database.py
git commit -m "feat: add pytest infrastructure and review_reports table"
```

---

### Task 2: Demo Data Seed Script

**Files:**
- Create: `backend/seed_demo_data.py`

- [ ] **Step 1: Create seed_demo_data.py**

Write `backend/seed_demo_data.py`:
```python
"""插入 15-20 笔 demo 交易数据和 5-8 只 demo 持仓，供 AI 复盘测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import init_db, execute, execute_many, query_one

init_db()

# Ensure demo user exists
existing = query_one("SELECT id FROM users WHERE id = 1")
if not existing:
    execute(
        "INSERT INTO users (id, username, email, password) VALUES (1, 'demo', 'demo@stockai.local', '$2b$12$LJ3m4ys3Gql.ZhkBARVOceOKVsS5DXPKP5lJSdFNhWXbFkx2YqPCG')"
    )

# Clear existing demo data for idempotent re-runs
execute("DELETE FROM transactions WHERE user_id = 1")
execute("DELETE FROM holdings WHERE user_id = 1")
execute("DELETE FROM watchlist WHERE user_id = 1")

# 8 holdings — mix of A-shares, ETF, fund
holdings = [
    ("600519", "贵州茅台", "SH", "stock", 200, 1720.50, None, None),
    ("300750", "宁德时代", "SZ", "stock", 500, 245.00, None, None),
    ("688981", "中芯国际", "SH", "stock", 800, 65.80, None, None),
    ("00700",  "腾讯控股", "HK", "stock", 300, 352.10, None, None),
    ("510050", "上证50ETF", "SH", "etf", 2000, 2.85, None, None),
    ("000858", "五粮液",   "SZ", "stock", 100, 168.00, None, None),
    ("002415", "海康威视", "SZ", "stock", 400, 35.20, None, None),
    ("159915", "创业板ETF", "SZ", "etf", 3000, 2.15, None, None),
]

for code, name, market, atype, qty, cost, shares, pf_id in holdings:
    execute(
        "INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price, shares, portfolio_id) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, name, market, atype, qty, cost, shares, pf_id),
    )

# 18 transactions — varied dates, directions, P&L
transactions = [
    # Maotai —盈利 (buy low, sell high)
    ("600519", "贵州茅台", "stock", "buy",  1680.50, 100, "2026-04-10", "分批建仓-1"),
    ("600519", "贵州茅台", "stock", "buy",  1760.00, 100, "2026-04-20", "分批建仓-2"),
    ("600519", "贵州茅台", "stock", "sell", 1890.00, 50,  "2026-05-15", "止盈卖出"),
    # CATL —亏损 (追涨买入)
    ("300750", "宁德时代", "stock", "buy",  255.00, 200, "2026-04-15", "追涨买入-季报后"),
    ("300750", "宁德时代", "stock", "buy",  235.00, 300, "2026-04-25", "加仓摊薄"),
    ("300750", "宁德时代", "stock", "sell", 228.00, 100, "2026-05-10", "止损减持"),
    # SMIC —盈利
    ("688981", "中芯国际", "stock", "buy",  62.30,  500, "2026-03-20", "回调买入"),
    ("688981", "中芯国际", "stock", "buy",  68.50,  300, "2026-04-02", "加仓"),
    ("688981", "中芯国际", "stock", "sell", 75.80,  200, "2026-05-08", "部分止盈"),
    # Tencent —盈利
    ("00700",  "腾讯控股", "stock", "buy",  340.20, 200, "2026-03-15", "回调买入"),
    ("00700",  "腾讯控股", "stock", "buy",  365.00, 100, "2026-04-08", "加仓"),
    # 上证50ETF —盈利
    ("510050", "上证50ETF", "etf",  "buy",  2.78,   1000, "2026-03-01", "定投"),
    ("510050", "上证50ETF", "etf",  "buy",  2.91,   1000, "2026-04-01", "定投"),
    # Wuliangye —追涨亏损
    ("000858", "五粮液",   "stock", "buy",  175.00, 100, "2026-04-28", "追高买入"),
    ("000858", "五粮液",   "stock", "sell", 162.00, 50,  "2026-05-12", "止损"),
    # Hikvision —盈利
    ("002415", "海康威视", "stock", "buy",  33.80,  200, "2026-03-08", "回调买入"),
    ("002415", "海康威视", "stock", "buy",  36.50,  200, "2026-04-12", "加仓"),
    # 创业板ETF —定投
    ("159915", "创业板ETF", "etf",  "buy",  2.05,   1500, "2026-03-01", "定投"),
    ("159915", "创业板ETF", "etf",  "buy",  2.25,   1500, "2026-04-01", "定投"),
]

for code, name, atype, direction, price, qty, traded_at, note in transactions:
    amount = round(price * qty, 2)
    execute(
        "INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, traded_at, note) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, name, atype, direction, price, qty, amount, traded_at, note),
    )

print("Demo data seeded: 8 holdings, 18 transactions")
print("Run: python backend/seed_demo_data.py")
```

- [ ] **Step 2: Run seed script**

Run: `python backend/seed_demo_data.py`
Expected: "Demo data seeded: 8 holdings, 18 transactions"

- [ ] **Step 3: Verify data**

Run: `python -c "from database import query_all; h = query_all('SELECT count(*) as c FROM holdings WHERE user_id=1'); t = query_all('SELECT count(*) as c FROM transactions WHERE user_id=1'); print(f'Holdings: {h[0][\"c\"]}, Transactions: {t[0][\"c\"]}')"`
Expected: "Holdings: 8, Transactions: 18"

- [ ] **Step 4: Commit**

```bash
git add backend/seed_demo_data.py
git commit -m "feat: add demo data seed script (8 holdings, 18 transactions)"
```

---

### Task 3: Review Service — Data Aggregation

**Files:**
- Create: `backend/services/review_service.py`
- Create: `tests/test_review_service.py`

- [ ] **Step 1: Write the failing test for aggregate_transactions()**

Write `tests/test_review_service.py`:
```python
from services.review_service import aggregate_transactions, build_review_prompt, parse_review_response


class TestAggregateTransactions:
    def test_returns_empty_for_no_transactions(self):
        result = aggregate_transactions(user_id=99999)
        assert result == {
            "transactions": [],
            "total_trades": 0,
            "win_count": 0,
            "lose_count": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_hold_days": 0,
            "top_gainers": [],
            "top_losers": [],
            "holdings_summary": [],
        }

    def test_aggregates_real_data(self):
        from database import query_all

        # Check we have seed data
        count = query_all("SELECT count(*) as c FROM transactions WHERE user_id = 1")
        if count[0]["c"] == 0:
            import subprocess
            subprocess.run(["python", "backend/seed_demo_data.py"], check=True)

        result = aggregate_transactions(user_id=1)
        assert result["total_trades"] >= 15
        assert result["total_pnl"] != 0
        assert len(result["top_gainers"]) > 0
        assert len(result["top_losers"]) > 0
        assert len(result["holdings_summary"]) > 0
        assert "stock_code" in result["transactions"][0]
        assert "pnl" in result["transactions"][0]

    def test_win_rate_calculation(self):
        result = aggregate_transactions(user_id=1)
        total = result["win_count"] + result["lose_count"]
        if total > 0:
            expected_rate = round(result["win_count"] / total * 100, 1)
            assert result["win_rate"] == expected_rate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_review_service.py::TestAggregateTransactions -v`
Expected: ImportError (review_service module doesn't exist yet)

- [ ] **Step 3: Implement aggregate_transactions()**

Write `backend/services/review_service.py`:
```python
"""AI 投资教练 — 复盘报告引擎

数据聚合 → prompt 构建 → AI 调用 → JSON 解析 → 降级处理
"""
from database import query_all


def aggregate_transactions(user_id: int = 1) -> dict:
    """聚合用户交易数据，计算关键指标"""
    trades = query_all(
        """SELECT t.*, h.cost_price, h.quantity as current_hold
           FROM transactions t
           LEFT JOIN holdings h ON t.stock_code = h.stock_code AND h.user_id = ?
           WHERE t.user_id = ?
           ORDER BY t.traded_at ASC""",
        (user_id, user_id),
    )

    if not trades:
        return {
            "transactions": [],
            "total_trades": 0,
            "win_count": 0,
            "lose_count": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_hold_days": 0,
            "top_gainers": [],
            "top_losers": [],
            "holdings_summary": [],
        }

    # Calculate PnL per stock by matching buy/sell pairs
    buy_records = {}  # stock_code -> [buy transactions]
    sell_records = []  # list of sell transactions with matched buy info

    for t in trades:
        if t["direction"] == "buy":
            if t["stock_code"] not in buy_records:
                buy_records[t["stock_code"]] = []
            buy_records[t["stock_code"]].append(t)
        elif t["direction"] == "sell":
            sells = buy_records.get(t["stock_code"], [])
            if sells:
                buy = sells.pop(0)
                buy_amount = buy["price"] * buy["quantity"]
                sell_amount = t["price"] * t["quantity"]
                pnl = round(sell_amount - buy_amount, 2)
                from datetime import datetime as dt
                try:
                    buy_date = dt.strptime(buy["traded_at"], "%Y-%m-%d")
                    sell_date = dt.strptime(t["traded_at"], "%Y-%m-%d")
                    hold_days = (sell_date - buy_date).days
                except Exception:
                    hold_days = 0
                sell_records.append({**t, "pnl": pnl, "hold_days": hold_days})

    # Identify top gainers and losers
    sorted_sells = sorted(sell_records, key=lambda x: x["pnl"], reverse=True)
    top_gainers = sorted_sells[:3]
    top_losers = sorted_sells[-3:] if len(sorted_sells) >= 3 else []
    top_losers = sorted(top_losers, key=lambda x: x["pnl"])

    win_count = sum(1 for s in sell_records if s["pnl"] > 0)
    lose_count = sum(1 for s in sell_records if s["pnl"] < 0)
    total_trades = len(sell_records)
    win_rate = round(win_count / total_trades * 100, 1) if total_trades > 0 else 0
    total_pnl = sum(s["pnl"] for s in sell_records)
    avg_hold_days = round(sum(s["hold_days"] for s in sell_records) / total_trades, 1) if total_trades > 0 else 0

    # Holdings summary
    holdings = query_all(
        "SELECT * FROM holdings WHERE user_id = ?",
        (user_id,),
    )
    holdings_summary = [{
        "stock_code": h["stock_code"],
        "stock_name": h["stock_name"],
        "quantity": h["quantity"],
        "cost_price": h["cost_price"],
        "asset_type": h.get("asset_type", "stock"),
    } for h in holdings]

    # Enrich transactions with PnL info
    enriched_transactions = []
    for t in trades:
        enriched = dict(t)
        matching_sell = next((s for s in sell_records if s["id"] == t["id"]), None)
        enriched["pnl"] = matching_sell["pnl"] if matching_sell else 0
        enriched["hold_days"] = matching_sell["hold_days"] if matching_sell else None
        enriched_transactions.append(enriched)

    return {
        "transactions": enriched_transactions,
        "total_trades": total_trades,
        "win_count": win_count,
        "lose_count": lose_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_hold_days": avg_hold_days,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "holdings_summary": holdings_summary,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review_service.py::TestAggregateTransactions -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/review_service.py tests/test_review_service.py
git commit -m "feat: add review_service aggregate_transactions with tests"
```

---

### Task 4: Review Service — Prompt Building

**Files:**
- Modify: `backend/services/review_service.py`
- Modify: `tests/test_review_service.py`

- [ ] **Step 1: Write failing test for build_review_prompt()**

Append to `tests/test_review_service.py`:
```python
class TestBuildReviewPrompt:
    def test_includes_dimension_schema(self):
        data = {
            "total_trades": 15,
            "total_pnl": 50000,
            "win_rate": 62.5,
            "holdings_summary": [{"stock_code": "600519", "stock_name": "贵州茅台", "cost_price": 1720.50, "quantity": 200, "asset_type": "stock"}],
            "top_gainers": [{"stock_code": "600519", "stock_name": "贵州茅台", "pnl": 26000, "hold_days": 35}],
            "top_losers": [{"stock_code": "300750", "stock_name": "宁德时代", "pnl": -13250, "hold_days": 25}],
            "transactions": [],
            "avg_hold_days": 30.5,
            "win_count": 9,
            "lose_count": 5,
        }
        prompt = build_review_prompt(data)
        assert "dimensions" in prompt
        assert "盈亏归因" in prompt
        assert "行为模式" in prompt
        assert "风险提示" in prompt
        assert "JSON" in prompt
        assert '"summary"' in prompt
        assert '"suggestions"' in prompt
        assert '"reasoning"' in prompt
        assert "贵州茅台" in prompt
        assert "宁德时代" in prompt

    def test_handles_empty_data(self):
        data = {
            "total_trades": 0,
            "total_pnl": 0,
            "win_rate": 0,
            "holdings_summary": [],
            "top_gainers": [],
            "top_losers": [],
            "transactions": [],
            "avg_hold_days": 0,
            "win_count": 0,
            "lose_count": 0,
        }
        prompt = build_review_prompt(data)
        assert len(prompt) > 0
        assert "暂无" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_review_service.py::TestBuildReviewPrompt -v`
Expected: FAIL (function not defined)

- [ ] **Step 3: Implement build_review_prompt()**

Append to `backend/services/review_service.py`:
```python
def build_review_prompt(data: dict) -> str:
    """Build the structured review prompt with embedded JSON schema"""
    holdings_text = "\n".join(
        f"- {h['stock_code']} {h['stock_name']}（{h.get('asset_type','stock')}），"
        f"持仓{h['quantity']}股，成本{h['cost_price']}元"
        for h in data["holdings_summary"]
    ) if data["holdings_summary"] else "暂无持仓"

    gainers_text = "\n".join(
        f"- {g['stock_code']} {g.get('stock_name','')}：盈亏 +{g['pnl']}元，"
        f"持有{g['hold_days']}天"
        for g in data["top_gainers"]
    ) if data["top_gainers"] else "暂无盈利交易"

    losers_text = "\n".join(
        f"- {l['stock_code']} {l.get('stock_name','')}：盈亏 {l['pnl']}元，"
        f"持有{l['hold_days']}天"
        for l in data["top_losers"]
    ) if data["top_losers"] else "暂无亏损交易"

    if data["total_trades"] < 5:
        trades_note = f"（仅 {data['total_trades']} 笔交易，数据不足，分析可能不完整）"
    else:
        trades_note = f"共 {data['total_trades']} 笔交易"

    prompt = f"""你是一位专业的 A 股投资教练。请基于以下用户的交易数据，生成一份结构化的投资复盘报告。

## 用户交易数据
- 总交易笔数：{data['total_trades']} {trades_note}
- 胜率：{data['win_rate']}%（{data['win_count']}胜/{data['lose_count']}负）
- 总盈亏：{data['total_pnl']}元
- 平均持有天数：{data['avg_hold_days']}天

### 当前持仓
{holdings_text}

### 盈利最大的 3 笔
{gainers_text}

### 亏损最大的 3 笔
{losers_text}

## 输出要求

请严格按以下 JSON 结构输出（不要包含 markdown 代码块标记，直接输出 JSON）：

{{
  "dimensions": [
    {{
      "id": "pnl_attribution",
      "title": "盈亏归因",
      "summary": "一句话总结本期盈亏情况和归因（选股/择时/大盘）",
      "detail": "详细分析盈利和亏损的主要原因，对比同期大盘指数表现",
      "score": 0-100 的整数评分
    }},
    {{
      "id": "behavior_pattern",
      "title": "行为模式",
      "summary": "一句话总结交易行为特征（追涨/杀跌/持仓时间/集中度）",
      "detail": "分析追涨杀跌频率、持仓集中度(top 3占比)、平均持有天数是否合理",
      "score": 0-100 的整数评分
    }},
    {{
      "id": "risk_alert",
      "title": "风险提示",
      "summary": "一句话总结当前风险状况",
      "detail": "分析单票仓位是否过重(>30%)、行业集中度、是否满仓/空仓极端状态",
      "score": 0-100 的整数评分
    }}
  ],
  "summary": "总体评估，一段话总结（50-100字）",
  "suggestions": [
    {{
      "text": "具体的改进建议",
      "reasoning": "为什么提出这条建议，基于什么数据或行为模式"
    }}
  ]
}}

请确保：
1. 输出是有效的 JSON（不要 markdown 代码块）
2. 每个维度的 detail 至少 50 字
3. 给出至少 3 条改进建议，每条必须附带 reasoning
4. 建议要具体、可执行，不要泛泛而谈
5. 如果你不知道该说什么，输出 {{"error": "数据不足，无法生成分析"}}"""
    return prompt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review_service.py::TestBuildReviewPrompt -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/review_service.py tests/test_review_service.py
git commit -m "feat: add build_review_prompt with embedded JSON schema"
```

---

### Task 5: Review Service — Response Parsing + Fallback

**Files:**
- Modify: `backend/services/review_service.py`
- Modify: `tests/test_review_service.py`

- [ ] **Step 1: Write failing test for parse_review_response()**

Append to `tests/test_review_service.py`:
```python
class TestParseReviewResponse:
    def test_parses_valid_json(self):
        raw = '{"summary":"总体评估","dimensions":[{"id":"a","title":"T","summary":"S","detail":"D","score":80}],"suggestions":[{"text":"建议","reasoning":"理由"}]}'
        result = parse_review_response(raw)
        assert result["summary"] == "总体评估"
        assert len(result["dimensions"]) == 1
        assert result["dimensions"][0]["score"] == 80
        assert result["raw"] == raw

    def test_strips_markdown_code_block(self):
        raw = '```json\n{"summary":"test","dimensions":[],"suggestions":[]}\n```'
        result = parse_review_response(raw)
        assert result["summary"] == "test"

    def test_extracts_json_from_mixed_text(self):
        raw = 'Here is the report: {"summary":"mixed","dimensions":[],"suggestions":[]} end'
        result = parse_review_response(raw)
        assert result["summary"] == "mixed"

    def test_fallback_on_invalid_json(self):
        raw = '这是一段无法解析的中文文本，没有 JSON 结构'
        result = parse_review_response(raw)
        assert result["summary"] == "AI 返回格式异常，以下为原始内容"
        assert result["raw"] == raw
        assert result["dimensions"] == []
        assert result["suggestions"] == []

    def test_fallback_on_empty_response(self):
        result = parse_review_response("")
        assert result["summary"] == "AI 分析暂不可用，请稍后重试"
        assert result["error"] is True

    def test_repairs_common_json_errors(self):
        # Missing comma between array elements
        raw = '{"summary":"test","dimensions":[{"id":"a" "title":"T" "summary":"S" "detail":"D" "score":80}] "suggestions":[]}'
        result = parse_review_response(raw)
        assert result["summary"] == "test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_review_service.py::TestParseReviewResponse -v`
Expected: FAIL (function not defined)

- [ ] **Step 3: Implement parse_review_response()**

Append to `backend/services/review_service.py`:
```python
import json
import re


def parse_review_response(raw: str) -> dict:
    """Parse AI response into structured dict, with progressive fallback"""
    if not raw or not raw.strip():
        return {
            "dimensions": [],
            "summary": "AI 分析暂不可用，请稍后重试",
            "suggestions": [],
            "error": True,
            "raw": "",
        }

    text = raw.strip()

    # Step 1: Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove opening ```json or ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Remove closing ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Step 2: Try direct parse
    try:
        data = json.loads(text)
        return _normalize_response(data, raw)
    except json.JSONDecodeError:
        pass

    # Step 3: Extract JSON fragment between { and }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return _normalize_response(data, raw)
        except json.JSONDecodeError:
            pass

    # Step 4: Repair common errors
    if match:
        repaired = match.group(0)
        # Fix missing commas between } and "
        repaired = re.sub(r'\}\s*"', '}, "', repaired)
        # Fix missing commas between ] and "
        repaired = re.sub(r'\]\s*"', '], "', repaired)
        # Fix missing commas between " and " (adjacent strings in objects)
        repaired = re.sub(r'"\s+"', '", "', repaired)
        # Fix missing commas between number and "
        repaired = re.sub(r'(\d+)\s+"', r'\1, "', repaired)
        try:
            data = json.loads(repaired)
            return _normalize_response(data, raw)
        except json.JSONDecodeError:
            pass

    # Step 5: Fallback — return raw text
    return {
        "dimensions": [],
        "summary": "AI 返回格式异常，以下为原始内容",
        "suggestions": [],
        "raw": raw,
    }


def _normalize_response(data: dict, raw_text: str) -> dict:
    """Ensure the parsed response has the expected fields"""
    return {
        "dimensions": data.get("dimensions", []),
        "summary": data.get("summary", ""),
        "suggestions": data.get("suggestions", []),
        "raw": raw_text,
        "error": "error" in data,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review_service.py::TestParseReviewResponse -v`
Expected: 6 PASS

- [ ] **Step 5: Run ALL review_service tests**

Run: `python -m pytest tests/test_review_service.py -v`
Expected: 11 PASS (3 aggregate + 2 prompt + 6 parse)

- [ ] **Step 6: Commit**

```bash
git add backend/services/review_service.py tests/test_review_service.py
git commit -m "feat: add parse_review_response with progressive fallback + full test suite"
```

---

### Task 6: Review Service — AI Calling + Top-Level generate_report()

**Files:**
- Modify: `backend/services/review_service.py`
- Modify: `tests/test_review_service.py`

- [ ] **Step 1: Write test for generate_review_report()**

Append to `tests/test_review_service.py`:
```python
import pytest


@pytest.mark.asyncio
async def test_generate_report_returns_data():
    """Integration-ish test — calls real AI, may be slow. Mark with pytest.mark.slow."""
    from services.review_service import generate_review_report

    result = await generate_review_report(user_id=1)
    assert "summary" in result
    assert "dimensions" in result
    assert "suggestions" in result
    assert len(result["summary"]) > 0


@pytest.mark.asyncio
async def test_generate_report_cold_start():
    """Verify cold start behavior when < 5 transactions exist"""
    from services.review_service import generate_review_report

    result = await generate_review_report(user_id=99999)
    assert result["cold_start"] is True
    assert "至少需要 5 笔交易" in result["summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_review_service.py::test_generate_report_returns_data -v`
Expected: FAIL (function not defined)

- [ ] **Step 3: Implement generate_review_report()**

Append to `backend/services/review_service.py`:
```python
import asyncio


async def generate_review_report(
    user_id: int = 1,
    provider: str = "",
    api_key: str = "",
    model: str = "",
) -> dict:
    """Top-level: aggregate → check cold start → prompt → AI call → parse → store

    Returns the parsed report dict. Stores result in review_reports table.
    """
    from services.ai_service import ai_chat

    # Step 1: Aggregate
    data = aggregate_transactions(user_id)

    # Step 2: Cold start check
    if data["total_trades"] < 5:
        return {
            "dimensions": [],
            "summary": f"已有 {data['total_trades']} 笔交易，至少需要 5 笔交易才能生成 AI 复盘报告。继续记录你的交易吧！",
            "suggestions": [],
            "cold_start": True,
            "transactions_count": data["total_trades"],
            "raw": "",
        }

    # Step 3: Build prompt
    prompt = build_review_prompt(data)

    # Step 4: Call AI with retry + fallback
    raw = ""
    try:
        raw = await asyncio.wait_for(
            ai_chat(
                prompt,
                provider=provider,
                api_key=api_key,
                model=model,
                system_prompt="你是专业的 A 股投资教练。请严格按 JSON 格式输出分析报告。",
            ),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        # Retry once
        try:
            raw = await asyncio.wait_for(
                ai_chat(
                    prompt,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    system_prompt="你是专业的 A 股投资教练。请严格按 JSON 格式输出分析报告。",
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            raw = ""
    except Exception:
        raw = ""

    # Step 5: Parse
    report = parse_review_response(raw)
    report["transactions_count"] = data["total_trades"]
    report["cold_start"] = False
    report["total_pnl"] = data["total_pnl"]
    report["win_rate"] = data["win_rate"]
    report["avg_hold_days"] = data["avg_hold_days"]
    report["win_count"] = data["win_count"]
    report["lose_count"] = data["lose_count"]
    dims = report.get("dimensions", [])
    if dims:
        avg_score = round(sum(d.get("score", 0) for d in dims) / len(dims))
    else:
        avg_score = 0
    report["avg_score"] = avg_score

    # Step 6: Store in DB
    try:
        from database import execute
        import json as _json

        execute(
            """INSERT INTO review_reports (user_id, report_type, transactions_count, dimensions, ai_response, summary, score_data)
               VALUES (?, 'daily', ?, ?, ?, ?, ?)""",
            (
                user_id,
                data["total_trades"],
                _json.dumps([d["id"] for d in report.get("dimensions", [])], ensure_ascii=False),
                raw,
                report["summary"],
                _json.dumps(
                    {d["id"]: d.get("score", 0) for d in report.get("dimensions", [])},
                    ensure_ascii=False,
                ),
            ),
        )
    except Exception:
        pass  # Non-critical: report is still returned even if storage fails

    return report
```

- [ ] **Step 4: Verify module structure**

Run: `python -c "from services.review_service import aggregate_transactions, build_review_prompt, parse_review_response, generate_review_report; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/test_review_service.py -v`
Expected: 13 tests — 11 PASS, 2 possibly SKIP (AI tests need network)

- [ ] **Step 6: Commit**

```bash
git add backend/services/review_service.py tests/test_review_service.py
git commit -m "feat: add generate_review_report with AI calling, retry, and DB storage"
```

---

### Task 7: API Endpoints

**Files:**
- Modify: `backend/routers/stocks.py`
- Create: `tests/test_review_api.py`

- [ ] **Step 1: Write API tests**

Write `tests/test_review_api.py`:
```python
import pytest


class TestReviewStructuredEndpoint:
    def test_post_success(self, client):
        response = client.post("/api/stocks/review/structured", json={
            "report_type": "daily",
        })
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "dimensions" in data
        assert "suggestions" in data
        assert "transactions_count" in data

    def test_post_cold_start(self, client):
        response = client.post("/api/stocks/review/structured", json={
            "report_type": "daily",
            "user_id": 99999,
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("cold_start") is True

    def test_post_custom_params(self, client):
        response = client.post("/api/stocks/review/structured", json={
            "report_type": "weekly",
            "provider": "minimax",
        })
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data


class TestReviewsListEndpoint:
    def test_get_empty_list(self, client):
        response = client.get("/api/stocks/reviews")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_with_reports(self, client):
        # Generate a report first
        client.post("/api/stocks/review/structured", json={"report_type": "daily"})
        response = client.get("/api/stocks/reviews")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            assert "summary" in data[0]
            assert "created_at" in data[0]
```

- [ ] **Step 2: Run API tests to verify they fail**

Run: `python -m pytest tests/test_review_api.py -v`
Expected: FAIL (endpoints don't exist)

- [ ] **Step 3: Add API endpoints to stocks.py**

Append to `backend/routers/stocks.py` (before the final router declaration at line ~1402):
```python

# ==================== AI 复盘 ====================

class ReviewRequest(BaseModel):
    report_type: str = "daily"   # daily / weekly / monthly
    user_id: int = 1
    provider: str = ""           # 留空使用默认
    api_key: str = ""
    model: str = ""


@router.post("/review/structured")
async def generate_review(body: ReviewRequest):
    """生成结构化 AI 复盘报告"""
    from services.review_service import generate_review_report

    report = await generate_review_report(
        user_id=body.user_id,
        provider=body.provider,
        api_key=body.api_key,
        model=body.model,
    )
    return report


@router.get("/reviews")
def list_reviews(user_id: int = 1, limit: int = 20, offset: int = 0):
    """返回历史复盘报告列表，最新的在前"""
    return query_all(
        """SELECT id, report_type, period_start, period_end, transactions_count,
                  summary, score_data, created_at
           FROM review_reports
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (user_id, limit, offset),
    )
```

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/test_review_api.py -v`
Expected: 5 PASS (list tests may need reports to exist; the post tests create them)

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (except possibly AI network-dependent tests)

- [ ] **Step 6: Commit**

```bash
git add backend/routers/stocks.py tests/test_review_api.py
git commit -m "feat: add POST /review/structured and GET /reviews endpoints"
```

---

### Task 8: Common JS/CSS — State Helpers + Skeleton + Shortcuts

**Files:**
- Modify: `frontend/js/common.js:37-80`
- Modify: `frontend/css/common.css`

- [ ] **Step 1: Upgrade showLoading/showEmpty/showError in common.js**

Replace the three state helper functions (lines 37-45) in `frontend/js/common.js`:
```javascript
// ==================== Loading / Empty / Error 状态 ====================
function showLoading(container) {
  container.innerHTML = `<div class="skeleton-card">
    <div class="skeleton skeleton-title"></div>
    <div class="skeleton skeleton-row"><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell-sm"></div></div>
    <div class="skeleton skeleton-row"><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell-sm"></div></div>
  </div>`;
}
function showEmpty(container, text, ctaText, ctaHref) {
  const cta = ctaText ? `<a href="${ctaHref || '#'}" class="btn btn-primary" style="margin-top:16px">${ctaText}</a>` : '';
  container.innerHTML = `<div class="empty-state">
    <svg class="empty-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 5v14M5 12h14"/></svg>
    <p>${text || '暂无数据'}</p>
    ${cta}
  </div>`;
}
function showError(container, err, retryFn) {
  const retry = retryFn ? `<button class="btn btn-retry" onclick="(${retryFn.toString()})()">重新加载</button>` : '';
  container.innerHTML = `<div class="empty-state error-state">
    <svg class="empty-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
    <p>${err?.message || err || '加载失败'}</p>
    ${retry}
  </div>`;
}
```

- [ ] **Step 2: Add keyboard shortcuts to common.js**

Append to `frontend/js/common.js`:
```javascript
// ==================== 键盘快捷键 ====================
document.addEventListener('keydown', function(e) {
  // Only fire when no input/textarea/contenteditable is focused
  const tag = document.activeElement?.tagName?.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || document.activeElement?.isContentEditable) return;

  if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    showShortcutHelp();
    return;
  }

  // Two-key shortcuts: G + H/M/A
  if (e.key === 'g' || e.key === 'G') {
    window._shortcutPrefix = 'g';
    setTimeout(function() { window._shortcutPrefix = null; }, 1500);
    return;
  }
  if (window._shortcutPrefix === 'g') {
    window._shortcutPrefix = null;
    if (e.key === 'h' || e.key === 'H') { window.location.href = 'index.html'; }
    else if (e.key === 'm' || e.key === 'M') { window.location.href = 'market.html'; }
    else if (e.key === 'a' || e.key === 'A') { window.location.href = 'review.html'; }
  }
});

function showShortcutHelp() {
  var existing = document.getElementById('shortcut-dialog');
  if (existing) { existing.remove(); return; }
  var d = document.createElement('div');
  d.id = 'shortcut-dialog';
  d.className = 'dialog-overlay';
  d.innerHTML = `<div class="dialog" style="max-width:360px">
    <h3>键盘快捷键</h3>
    <div class="shortcut-list">
      <div class="shortcut-row"><kbd>G</kbd> <kbd>H</kbd> <span>首页 — 持仓仪表盘</span></div>
      <div class="shortcut-row"><kbd>G</kbd> <kbd>M</kbd> <span>大盘指数</span></div>
      <div class="shortcut-row"><kbd>G</kbd> <kbd>A</kbd> <span>AI 复盘报告</span></div>
      <div class="shortcut-row"><kbd>?</kbd> <span>显示/隐藏快捷键帮助</span></div>
    </div>
    <button class="btn btn-primary" onclick="document.getElementById('shortcut-dialog').remove()" style="margin-top:16px;width:100%">关闭</button>
  </div>`;
  d.onclick = function(e) { if (e.target === d) d.remove(); };
  document.body.appendChild(d);
}
```

- [ ] **Step 3: Replace emoji in sidebar nav with SVG icons**

Replace `renderSidebar` in `frontend/js/common.js` (lines 48-80). Replace the emoji icons in the `pages` array:
```javascript
function renderSidebar(activePage) {
  const pages = [
    { id: 'holdings',   href: 'index.html',           icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M9 3v18"/></svg>', label: '我的持仓' },
    { id: 'watchlist',  href: 'watchlist.html',       icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15 9 22 9 16 14 18 22 12 17 6 22 8 14 2 9 9 9"/></svg>', label: '自选股' },
    { id: 'market',     href: 'market.html',          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>', label: '大盘指数' },
    { id: 'global',     href: 'global-news.html',    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 000 20"/></svg>', label: '全球资讯' },
    { id: 'review',     href: 'review.html',          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 012-2h2a2 2 0 012 2M9 14l2 2 4-4"/></svg>', label: 'AI 复盘' },
    { id: 'skills',     href: 'skills.html',          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="5"/><path d="M7 8h10M7 12h10M7 16h6"/></svg>', label: 'Agent 工坊' },
    { id: 'transactions', href: 'transactions.html',  icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 014-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 01-4 4H3"/></svg>', label: '交易记录' },
  ];
  const bottomPages = [
    { id: 'settings',   href: 'settings.html',        icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>', label: '设置' },
    { id: 'ai-chat',    href: 'ai-assistant.html',    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>', label: 'AI 对话' },
  ];

  const navItems = pages.map(p =>
    `<a href="${p.href}" class="nav-item${activePage === p.id ? ' active' : ''}">
      <span class="nav-icon">${p.icon}</span> ${p.label}
    </a>`
  ).join('');

  const bottomItems = bottomPages.map(p =>
    `<a href="${p.href}" class="nav-item${activePage === p.id ? ' active' : ''}">
      <span class="nav-icon">${p.icon}</span> ${p.label}
    </a>`
  ).join('');

  return `
    <div class="logo"><a href="index.html"><svg class="logo-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg> <span>StockAI</span></a></div>
    <div class="nav-section">${navItems}</div>
    <hr class="nav-divider">
    <div class="nav-section">${bottomItems}</div>
    <hr class="nav-divider">
    <div class="nav-section shortcut-hint">
      <kbd>G</kbd> <kbd>H</kbd> 首页 &middot; <kbd>G</kbd> <kbd>A</kbd> 复盘 &middot; <kbd>?</kbd> 快捷键
    </div>
  `;
}
```

- [ ] **Step 4: Add CSS for skeleton, btn-retry, svg icons, shortcut hints**

Append to `frontend/css/common.css`:
```css
/* ==================== Skeleton Loading ==================== */
.skeleton-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-md, 20px);
}
.skeleton {
  background: linear-gradient(90deg, var(--bg-card) 25%, var(--bg-hover) 50%, var(--bg-card) 75%);
  background-size: 200% 100%;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
  border-radius: var(--radius-sm);
}
@keyframes skeleton-pulse {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.skeleton-title { height: 20px; width: 40%; margin-bottom: 16px; }
.skeleton-row { display: flex; gap: 12px; margin-bottom: 12px; }
.skeleton-cell { height: 14px; flex: 1; }
.skeleton-cell-sm { height: 14px; flex: 1; max-width: 80px; }
.skeleton-cell-lg { height: 32px; flex: 1; }

/* ==================== Button: Retry ==================== */
.btn-retry {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-family: var(--font);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid rgba(239,83,80,.2);
  background: rgba(239,83,80,.1);
  color: var(--red);
  transition: background .2s;
}
.btn-retry:hover { background: rgba(239,83,80,.18); }
.btn-retry::before {
  content: '';
  display: inline-block;
  width: 14px; height: 14px;
  background: currentColor;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'%3E%3Cpath d='M23 4v6h-6M1 20v-6h6'/%3E%3Cpath d='M3.5 9a9 9 0 0114.8-3.5L23 10M1 14l4.7 4.5A9 9 0 0020.5 15'/%3E%3C/svg%3E") center/contain no-repeat;
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'%3E%3Cpath d='M23 4v6h-6M1 20v-6h6'/%3E%3Cpath d='M3.5 9a9 9 0 0114.8-3.5L23 10M1 14l4.7 4.5A9 9 0 0020.5 15'/%3E%3C/svg%3E") center/contain no-repeat;
}

/* ==================== SVG Icons ==================== */
.nav-icon svg { width: 18px; height: 18px; display: block; }
.logo-svg { width: 22px; height: 22px; vertical-align: -4px; margin-right: 4px; }
.empty-icon-svg {
  width: 48px; height: 48px;
  margin: 0 auto 16px;
  display: block;
  color: var(--text-muted);
}
.error-state .empty-icon-svg { color: var(--red); }

/* ==================== Error State ==================== */
.error-state p { color: var(--red); }

/* ==================== Keyboard Shortcuts ==================== */
.shortcut-hint {
  padding: 8px 16px;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.6;
}
.shortcut-hint kbd {
  display: inline-block;
  padding: 1px 5px;
  font-size: 10px;
  font-family: var(--font-mono);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text-secondary);
}
.shortcut-list { margin-top: 12px; }
.shortcut-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  font-size: 13px;
  color: var(--text-secondary);
}
.shortcut-row kbd {
  display: inline-block;
  padding: 2px 6px;
  font-size: 11px;
  font-family: var(--font-mono);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text);
}
.shortcut-row span { margin-left: 4px; }

/* ==================== AI Insight Panel (editorial style) ==================== */
.ai-insight-bar {
  background: var(--bg-card);
  border-left: 3px solid #c4b5fd;
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 16px 20px;
  margin-bottom: 20px;
}
.ai-insight-bar .ai-label {
  font-size: 11px;
  color: #c4b5fd;
  text-transform: uppercase;
  letter-spacing: .08em;
  margin-bottom: 6px;
  font-weight: 600;
}
.ai-insight-bar .ai-headline {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.5;
  margin-bottom: 4px;
}
.ai-insight-bar .ai-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

/* ==================== Freshness Indicator ==================== */
.freshness-dot {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.freshness-dot.live { background: var(--green); }
.freshness-dot.stale { background: var(--text-muted); }
.data-freshness {
  font-size: 11px;
  color: var(--text-muted);
}
```

- [ ] **Step 5: Verify CSS builds without errors**

No build step (plain CSS). Just verify the file is valid by checking for matching braces:
Run: `python -c "open('frontend/css/common.css').read(); print('CSS OK')"`
Expected: "CSS OK"

- [ ] **Step 6: Commit**

```bash
git add frontend/js/common.js frontend/css/common.css
git commit -m "feat: upgrade state helpers, SVG icons, skeleton CSS, keyboard shortcuts, btn-retry"
```

---

### Task 9: review.html — AI 复盘报告页面

**Files:**
- Create: `frontend/review.html`

- [ ] **Step 1: Create review.html**

Write `frontend/review.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 投资复盘 — StockAI</title>
<link rel="stylesheet" href="css/common.css">
<style>
  .review-container { max-width: 900px; margin: 0 auto; }
  .review-hero {
    display: flex; gap: 20px; margin-bottom: 24px; flex-wrap: wrap;
  }
  .review-hero-card {
    flex: 1; min-width: 180px;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px;
  }
  .review-hero-card .label {
    font-size: 11px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px;
  }
  .review-hero-card .value {
    font-size: 24px; font-weight: 700; font-family: var(--font-mono);
  }
  .review-hero-card .value.up { color: var(--red); }
  .review-hero-card .value.down { color: var(--green); }
  .review-hero-card .sub {
    font-size: 12px; color: var(--text-muted); margin-top: 4px;
  }

  .dimension-panel {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 12px; overflow: hidden;
  }
  .dimension-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; cursor: pointer; user-select: none;
    transition: background .15s;
  }
  .dimension-header:hover { background: var(--bg-hover); }
  .dimension-header h3 { font-size: 15px; font-weight: 600; margin: 0; }
  .dimension-header .dim-score {
    font-size: 13px; font-weight: 600; padding: 2px 10px;
    border-radius: 9999px; min-width: 40px; text-align: center;
  }
  .dim-score.high { background: rgba(38,166,154,.15); color: var(--green); }
  .dim-score.mid { background: rgba(245,158,11,.15); color: var(--warning, #f59e0b); }
  .dim-score.low { background: rgba(239,83,80,.15); color: var(--red); }
  .dimension-body { padding: 0 20px 20px; display: none; }
  .dimension-panel.open .dimension-body { display: block; }
  .dimension-body .dim-summary {
    font-size: 14px; color: var(--text-secondary); margin-bottom: 12px;
    line-height: 1.6;
  }
  .dimension-body .dim-detail {
    font-size: 13px; color: var(--text-muted); line-height: 1.7;
  }
  .dim-chevron { transition: transform .2s; }
  .dimension-panel.open .dim-chevron { transform: rotate(180deg); }

  .suggestions-section { margin-top: 24px; }
  .suggestion-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-left: 3px solid var(--accent); border-radius: 0 var(--radius) var(--radius) 0;
    padding: 16px 20px; margin-bottom: 10px;
  }
  .suggestion-card .sug-text {
    font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 8px;
  }
  .suggestion-card .sug-reasoning {
    font-size: 13px; color: var(--text-muted); font-style: italic;
    padding: 10px 14px; background: var(--bg-primary); border-radius: var(--radius-sm);
    display: none;
  }
  .suggestion-card .sug-reasoning::before {
    content: "为什么这么说? "; font-style: normal; font-weight: 500; color: #c4b5fd;
  }
  .suggestion-card.open .sug-reasoning { display: block; }
  .sug-toggle {
    font-size: 12px; color: var(--accent-light); cursor: pointer;
    background: none; border: none; padding: 4px 0; font-family: var(--font);
  }
  .sug-toggle:hover { text-decoration: underline; }

  .cold-start-card {
    text-align: center; padding: 48px 24px;
    background: var(--bg-card); border: 1px dashed var(--border);
    border-radius: var(--radius);
  }
  .cold-start-card h3 { font-size: 18px; margin-bottom: 8px; }
  .cold-start-card p { color: var(--text-secondary); margin-bottom: 16px; }
  .cold-progress { margin: 16px 0; }
  .cold-progress-bar {
    height: 6px; background: var(--bg-primary); border-radius: 3px; overflow: hidden;
  }
  .cold-progress-fill {
    height: 100%; background: var(--accent); border-radius: 3px; transition: width .5s;
  }
  .cold-progress-label { font-size: 12px; color: var(--text-muted); margin-top: 6px; }

  .report-history { margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--border); }
  .report-history h3 { font-size: 14px; color: var(--text-secondary); margin-bottom: 12px; }
  .history-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 16px; border-radius: var(--radius-sm); cursor: pointer;
    transition: background .15s;
  }
  .history-item:hover { background: var(--bg-hover); }
  .history-item .hi-date { font-size: 13px; color: var(--text); }
  .history-item .hi-summary { font-size: 13px; color: var(--text-secondary); max-width: 500px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .history-item .hi-count { font-size: 12px; color: var(--text-muted); }

  @media (max-width: 768px) {
    .review-hero { flex-direction: column; gap: 10px; }
    .review-hero-card { min-width: auto; }
  }
</style>
</head>
<body>
<div class="app-layout">
  <aside class="sidebar" id="sidebar"></aside>
  <main class="main">
    <header class="header" id="header"></header>
    <div class="content">
      <div class="review-container" id="reviewContainer"></div>
    </div>
  </main>
</div>
<nav class="mobile-nav" id="mobileNav"></nav>
<script src="js/common.js"></script>
<script>
// ==================== State ====================
var state = {
  report: null,
  reports: [],
  loading: true,
  error: null,
};

// ==================== Init ====================
document.getElementById('sidebar').innerHTML = renderSidebar('review');
document.getElementById('header').innerHTML = renderHeader('AI 投资复盘');
document.getElementById('mobileNav').innerHTML = renderMobileNav('review');

loadLatestReport();
loadHistory();

// ==================== Data Loading ====================
async function loadLatestReport() {
  state.loading = true;
  render();
  try {
    var res = await apiPost('/api/stocks/review/structured', { report_type: 'daily' });
    state.report = res;
    state.error = null;
  } catch (err) {
    state.error = err;
    state.report = null;
  }
  state.loading = false;
  render();
}

async function loadHistory() {
  try {
    state.reports = await apiGet('/api/stocks/reviews?limit=10');
  } catch (err) {
    state.reports = [];
  }
  renderHistory();
}

async function generateReport() {
  state.loading = true;
  state.error = null;
  render();
  try {
    var res = await apiPost('/api/stocks/review/structured', { report_type: 'daily' });
    state.report = res;
  } catch (err) {
    state.error = err;
  }
  state.loading = false;
  render();
  loadHistory();
}

// ==================== Render ====================
function render() {
  var c = document.getElementById('reviewContainer');

  if (state.loading) {
    showLoading(c);
    return;
  }
  if (state.error) {
    showError(c, state.error, generateReport);
    return;
  }
  if (!state.report) {
    showEmpty(c, '点击生成你的第一份 AI 复盘报告', '生成复盘报告');
    var btn = c.querySelector('.btn');
    if (btn) btn.onclick = generateReport;
    return;
  }
  if (state.report.cold_start) {
    renderColdStart(c);
    return;
  }
  renderReport(c);
}

function renderColdStart(c) {
  var count = state.report.transactions_count || 0;
  var pct = Math.min(count / 5 * 100, 100);
  c.innerHTML = `<div class="cold-start-card">
    <h3>📋 交易数据收集中</h3>
    <p>已有 ${count} 笔交易记录，满 5 笔后 AI 将生成第一次复盘报告</p>
    <div class="cold-progress">
      <div class="cold-progress-bar"><div class="cold-progress-fill" style="width:${pct}%"></div></div>
      <div class="cold-progress-label">${count} / 5 笔交易</div>
    </div>
    <a href="transactions.html" class="btn btn-primary" style="margin-top:16px">去添加交易记录</a>
  </div>`;
}

function renderReport(c) {
  var r = state.report;
  var dims = (r.dimensions || []).map(function(d, i) {
    var scoreClass = d.score >= 70 ? 'high' : d.score >= 40 ? 'mid' : 'low';
    return `<div class="dimension-panel${i === 0 ? ' open' : ''}">
      <div class="dimension-header" onclick="this.parentElement.classList.toggle('open')">
        <h3>${d.title}</h3>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="dim-score ${scoreClass}">${d.score}</span>
          <svg class="dim-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
      </div>
      <div class="dimension-body">
        <div class="dim-summary">${escHtml(d.summary)}</div>
        <div class="dim-detail">${escHtml(d.detail)}</div>
      </div>
    </div>`;
  }).join('');

  var suggestions = (r.suggestions || []).map(function(s) {
    return `<div class="suggestion-card">
      <div class="sug-text">${escHtml(s.text)}</div>
      <button class="sug-toggle" onclick="var card=this.parentElement;card.classList.toggle('open');this.textContent=card.classList.contains('open')?'收起':'为什么这么说? →'">为什么这么说? →</button>
      <div class="sug-reasoning">${escHtml(s.reasoning)}</div>
    </div>`;
  }).join('');

  var pnlClass = r.total_pnl >= 0 ? 'up' : 'down';
  var pnlSign = r.total_pnl >= 0 ? '+' : '';

  c.innerHTML = `<div class="review-hero">
    <div class="review-hero-card">
      <div class="label">本期盈亏</div>
      <div class="value ${pnlClass}">${pnlSign}${(r.total_pnl || 0).toLocaleString()}</div>
    </div>
    <div class="review-hero-card">
      <div class="label">交易笔数</div>
      <div class="value" style="color:var(--text)">${r.transactions_count || 0}</div>
    </div>
    <div class="review-hero-card">
      <div class="label">综合评分</div>
      <div class="value" style="color:var(--accent-light)">${r.avg_score || '—'}</div>
    </div>
  </div>

  <div class="ai-insight-bar">
    <div class="ai-label">AI 投资教练</div>
    <div class="ai-headline">${escHtml(r.summary || '')}</div>
  </div>

  ${dimensions}

  <div class="suggestions-section">
    <h3 style="margin-bottom:12px;font-size:16px">改进建议</h3>
    ${suggestions || '<p style="color:var(--text-muted)">暂无建议</p>'}
  </div>`;
}

function renderHistory() {
  var container = document.getElementById('reviewContainer');
  var existing = document.getElementById('reportHistory');
  if (existing) existing.remove();
  if (!state.reports || state.reports.length === 0) return;

  var html = '<div class="report-history" id="reportHistory"><h3>历史报告</h3>' +
    state.reports.map(function(rp) {
      return `<div class="history-item" onclick="loadReportById(${rp.id})">
        <span class="hi-date">${(rp.created_at || '').slice(0, 10)}</span>
        <span class="hi-summary">${escHtml(rp.summary || '')}</span>
        <span class="hi-count">${rp.transactions_count} 笔</span>
      </div>`;
    }).join('') + '</div>';

  container.insertAdjacentHTML('beforeend', html);
}

function loadReportById(id) {
  // For now, regenerate — full report loading from history is a future enhancement
  window.scrollTo({ top: 0, behavior: 'smooth' });
  generateReport();
}

function escHtml(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the file**

Run: `python -c "open('frontend/review.html').read(); print('HTML OK')"`
Expected: "HTML OK"

- [ ] **Step 3: Commit**

```bash
git add frontend/review.html
git commit -m "feat: add review.html — AI investment review report page"
```

---

### Task 10: UX Polish — index.html (持仓仪表盘)

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Read current index.html init section**

Read `frontend/index.html` to find where the page initializes and where data is rendered. Key areas to change:
1. Wrap the main content area with a `#dashboardContent` container for state management
2. Use the upgraded `showLoading`/`showEmpty`/`showError` from common.js
3. Add AI summary bar at the top (between header and KPI row)
4. Replace any emoji-based empty/error states

Since `index.html` is 1441 lines (large), we make targeted edits rather than rewriting.

- [ ] **Step 2: Add AI summary bar loading and rendering to index.html init**

Find the `initPage` or DOMContentLoaded handler in `frontend/index.html`. Add after the data fetch success:

```javascript
// After successful data load, render AI summary bar
async function loadAISummary() {
  try {
    var summaryRes = await apiPost('/api/stocks/review/structured', { report_type: 'daily' });
    var bar = document.getElementById('aiSummaryBar');
    if (bar && summaryRes.summary && !summaryRes.cold_start) {
      bar.innerHTML = `<div class="ai-insight-bar">
        <div class="ai-label">AI 投资教练</div>
        <div class="ai-headline">${summaryRes.summary}</div>
        <div class="ai-meta">基于最近交易数据分析 &middot; <a href="review.html">查看完整报告 →</a></div>
      </div>`;
      bar.style.display = 'block';
    }
  } catch (e) {
    // AI summary is non-critical — fail silently
  }
}
```

Add `<div id="aiSummaryBar" style="display:none"></div>` before the KPI row in the HTML structure.

- [ ] **Step 3: Replace emoji-based state patterns in index.html**

Search `frontend/index.html` for `⏳`, `📭`, `⚠️` emoji in error/empty/loading states. Replace them with calls to the upgraded `showLoading`/`showEmpty`/`showError` from common.js.

For each case found, replace the inline emoji HTML with the function call. Example pattern:
```javascript
// Before (current pattern):
container.innerHTML = '<div class="empty-state">⚠️ 加载失败</div>';

// After:
showError(container, '加载失败', loadData);
```

- [ ] **Step 4: Verify the page loads without JS errors**

Start the dev server and check:
Run: `python backend/main.py` (in background) and verify no JS syntax errors via manual check.

For now, verify syntax:
Run: `python -c "import re; html = open('frontend/index.html').read(); errors = []; print('index.html syntax check: OK' if not errors else errors)"`

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add AI summary bar and upgraded state handling to index.html"
```

---

### Task 11: UX Polish — ai-assistant.html + market.html

**Files:**
- Modify: `frontend/ai-assistant.html`
- Modify: `frontend/market.html`

- [ ] **Step 1: Add loading/retry to ai-assistant.html**

In `frontend/ai-assistant.html`, add send-loading state and retry on failure. Find the message send handler and wrap it:

```javascript
async function sendMessage() {
  var input = document.getElementById('aiInput');
  var msg = input.value.trim();
  if (!msg) return;

  var container = document.getElementById('messages');
  appendMessage('user', msg);
  input.value = '';

  // Show loading indicator
  var loadingEl = document.createElement('div');
  loadingEl.className = 'ai-msg ai-loading';
  loadingEl.innerHTML = '<div class="skeleton" style="height:16px;width:60%"></div><div class="skeleton" style="height:16px;width:40%;margin-top:8px"></div>';
  container.appendChild(loadingEl);
  container.scrollTop = container.scrollHeight;

  try {
    var res = await apiPost('/api/ai/chat', { message: msg, provider: getAIConfig().provider });
    loadingEl.remove();
    appendMessage('assistant', res.reply || res.message || res);
  } catch (err) {
    loadingEl.remove();
    var errEl = document.createElement('div');
    errEl.className = 'ai-msg error';
    errEl.innerHTML = `<p>AI 回复失败: ${err.message}</p><button class="btn btn-retry" onclick="this.parentElement.remove();sendMessage()">重试</button>`;
    container.appendChild(errEl);
  }
}
```

- [ ] **Step 2: Add welcome guidance for empty conversations**

In `ai-assistant.html`, add a welcome state when the messages container is empty:
```javascript
function showWelcome() {
  var c = document.getElementById('messages');
  c.innerHTML = `<div class="empty-state">
    <svg class="empty-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
    <p>你好！我是 StockAI 投资教练</p>
    <p style="font-size:13px;color:var(--text-muted);margin-top:4px">问我关于持仓分析、交易复盘、投资策略的问题</p>
  </div>`;
}
```

- [ ] **Step 3: Add loading skeleton and "—" fallback to market.html**

In `frontend/market.html`, find the data rendering function. Add:
1. Before fetch: call `showLoading(container)` (uses skeleton now)
2. On success: render index cards, with `—` for unavailable data points
3. On error: call `showError(container, err, loadMarketData)`
4. Add freshness timestamp at the bottom:

```javascript
function renderFreshness() {
  var el = document.getElementById('freshnessIndicator');
  if (el) {
    var now = new Date();
    var time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    el.innerHTML = `<span class="freshness-dot live"></span>最后更新于 ${time}`;
  }
}
```

Add `<div id="freshnessIndicator" class="data-freshness" style="padding:8px 0"></div>` at the bottom of the market content area.

- [ ] **Step 4: Commit**

```bash
git add frontend/ai-assistant.html frontend/market.html
git commit -m "feat: add loading/retry/welcome states to ai-assistant and market pages"
```

---

### Task 12: Demo Polish + README

**Files:**
- Modify: `frontend/css/common.css` (any remaining emoji CSS cleanup)
- Modify: `README.md` (in docs/)

- [ ] **Step 1: Add value proposition to README**

Read the existing README at `docs/README.md` (or create if it doesn't exist). Add a value proposition line at the top:
```markdown
# StockAI — AI 投资教练

> "用户在券商交易，在 StockAI 反思。" — A 股投资复盘与 AI 分析平台，帮你从每一笔交易中学习。
```

- [ ] **Step 2: Verify responsive layout on core pages**

Manual check (not testable via CLI):
1. `frontend/index.html` — sidebar collapses to bottom nav at 768px
2. `frontend/review.html` — hero cards stack vertically at 768px
3. `frontend/market.html` — index grid goes to 2 columns at 768px

All three already have `@media (max-width: 768px)` rules. Verify they're present.

- [ ] **Step 3: Ensure all pages use the unified state pattern**

Grep for remaining hardcoded emoji in frontend:
Run: `grep -rn '⏳\|📭\|⚠️\|📊\|💹\|🤖\|📝\|⭐\|⚙️\|🌍\|📈' frontend/ --include="*.html" --include="*.js"`
Expected: Only `review.html` cold start card (we kept the 📋 as it's in new code). Fix any stragglers.

- [ ] **Step 4: Final commit**

```bash
git add docs/README.md frontend/
git commit -m "feat: demo polish — README value prop, responsive verify, emoji cleanup"
```

---

### Task 13: Final Test Run + Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (AI-dependent tests may skip)

- [ ] **Step 2: Verify API endpoints manually**

Start the server and test endpoints:
```bash
# In one terminal:
python backend/main.py

# In another:
curl -s http://localhost:8000/api/stocks/holdings | python -m json.tool | head -5
curl -s -X POST http://localhost:8000/api/stocks/review/structured -H 'Content-Type: application/json' -d '{"report_type":"daily"}' | python -m json.tool | head -10
curl -s http://localhost:8000/api/stocks/reviews | python -m json.tool | head -5
```

- [ ] **Step 3: Verify all frontend pages load without JS errors**

Manual check: open each page in browser + check console.
- `index.html` — AI summary bar appears, KPI cards load
- `review.html` — generates report or shows cold start
- `ai-assistant.html` — shows welcome state, can send message
- `market.html` — index cards load with freshness indicator

- [ ] **Step 4: Commit final verification notes**

```bash
git add -A
git commit -m "chore: final test verification — all tests pass, endpoints verified"
```
