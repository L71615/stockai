---
name: run-stockai
description: Run StockAI server, smoke-test APIs, verify endpoints. Use when asked to start/run/launch/test the app.
---

# Run StockAI

StockAI is a Python FastAPI backend + static HTML frontend for A-share investment analysis.

## Prerequisites

```bash
# Python 3.11+ with pip
python --version

# On fresh Ubuntu: apt-get install -y python3 python3-pip
```

## Run (agent path)

The driver launches the server on a temporary port, hits all key API endpoints, and shuts down cleanly:

```bash
cd stocks
python .claude/skills/run-stockai/driver.py
```

This verifies:
- Server startup (health check)
- Global indices (11/15 live)
- Stock insight (K-line + indicators + factors)
- Factor data (PE/ROE/market cap)
- HK stock quotes (Tencent 00700)
- Fund NAV
- Portfolio risk (structure)
- Frontend static files

## Run (human path)

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload
# Open http://localhost:3000
```

## Test

```bash
cd stocks
python -m pytest tests/ -q
# 45 passed, 2 skipped
```

## Gotchas

- **Port conflict**: The driver uses port 8765 to avoid clashing with a running dev server on 3000.
- **Baostock login**: First API call triggers a Baostock login (prints `login success!`). This is normal.
- **No holdings = empty portfolio risk**: `GET /api/quant/portfolio-risk` returns `{"error":"无持仓数据"}` when the database has no holdings. This is expected — add holdings via the frontend first.
- **ETF volumes**: ETFs (510050, 159915) don't return volume data from any current data source. The volume chart shows a "(no data)" message.
- **Windows terminal**: GBK encoding can't print emoji/special chars. The driver uses ASCII-only output for compatibility.
