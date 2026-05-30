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
    ("00700",  "腾讯控股", "stock", "sell", 380.00, 150, "2026-05-20", "减仓止盈"),
    # 上证50ETF —盈利
    ("510050", "上证50ETF", "etf",  "buy",  2.78,   1000, "2026-03-01", "定投"),
    ("510050", "上证50ETF", "etf",  "buy",  2.91,   1000, "2026-04-01", "定投"),
    ("510050", "上证50ETF", "etf",  "sell", 3.05,   500,  "2026-05-22", "部分止盈"),
    # Wuliangye —追涨亏损
    ("000858", "五粮液",   "stock", "buy",  175.00, 100, "2026-04-28", "追高买入"),
    ("000858", "五粮液",   "stock", "sell", 162.00, 50,  "2026-05-12", "止损"),
    # Hikvision —盈利
    ("002415", "海康威视", "stock", "buy",  33.80,  200, "2026-03-08", "回调买入"),
    ("002415", "海康威视", "stock", "buy",  36.50,  200, "2026-04-12", "加仓"),
    ("002415", "海康威视", "stock", "sell", 38.20,  150, "2026-05-18", "部分止盈"),
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

print("Demo data seeded: 8 holdings, 22 transactions (7 sells, 15 buys)")
print("Run: python backend/seed_demo_data.py")
