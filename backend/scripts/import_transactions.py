"""导入完整交易记录到数据库（2026-06-05 ~ 2026-06-25）

用法: cd backend && python scripts/import_transactions.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import execute, execute_many, query_all, query_one, get_db
from services.utils import calc_fee, detect_asset_type, get_market

USER_ID = 1

# ═══════════════════════════════════════════════════════════════
# 股票代码映射
# ═══════════════════════════════════════════════════════════════

# 已知股票代码（精确）
STOCK_MAP = {
    "创元科技": ("000551", "stock"),
    "楚江新材": ("002171", "stock"),
    "彩虹股份": ("600707", "stock"),
    "春秋电子": ("603890", "stock"),
    "三安光电": ("600703", "stock"),
    "莲花控股": ("600186", "stock"),
    # ETF（已验证代码）
    "通信ETF": ("515880", "etf"),
    "机器人ETF": ("562500", "etf"),
    "化工ETF": ("159870", "etf"),
    "工业有色ETF": ("560860", "etf"),
    "电网设备ETF": ("159611", "etf"),      # 电力ETF广发
    "创业板新能源ETF": ("159915", "etf"),    # 创业板ETF易方达
    "卫星E": ("512660", "etf"),              # 军工ETF国泰（需确认）
}

def get_code_info(name: str):
    """根据名称获取代码和类型"""
    # 精确匹配
    if name in STOCK_MAP:
        return STOCK_MAP[name]
    # 模糊匹配
    for key, val in STOCK_MAP.items():
        if key[:3] in name or name[:3] in key:
            return val
    print(f"  ⚠ 未知股票: {name}")
    return (None, None)


# ═══════════════════════════════════════════════════════════════
# 交易记录（按时间顺序）
# ═══════════════════════════════════════════════════════════════

# 格式: (日期, 方向, 名称, 价格, 数量, 备注)
# direction: buy/sell/deposit/withdraw
# deposit/withdraw 的 name 用 "CASH"

TRANSACTIONS = [
    # ── 6/5 ──
    ("2026-06-05", "buy",  "卫星E",          1.382, 200),

    # ── 6/8 ──
    ("2026-06-08", "buy",  "机器人ETF",      1.412, 400),
    ("2026-06-08", "buy",  "通信ETF",        1.609, 100),

    # ── 6/10 ──
    ("2026-06-10", "buy",  "通信ETF",        1.626, 400),
    ("2026-06-10", "buy",  "通信ETF",        1.638, 200),
    ("2026-06-10", "buy",  "通信ETF",        1.639, 300),
    ("2026-06-10", "buy",  "卫星E",          1.356, 100),
    ("2026-06-10", "buy",  "机器人ETF",      1.385, 100),
    ("2026-06-10", "buy",  "机器人ETF",      1.386, 100),
    ("2026-06-10", "buy",  "电网设备ETF",    2.213, 100),

    # ── 6/11 ──
    ("2026-06-11", "buy",  "化工ETF",        0.807, 1000),
    ("2026-06-11", "sell", "机器人ETF",      1.323, 600),

    # ── 6/12 ──
    ("2026-06-12", "buy",  "通信ETF",        1.620, 700),
    ("2026-06-12", "buy",  "通信ETF",        1.613, 500),
    ("2026-06-12", "sell", "通信ETF",        1.616, 500),
    ("2026-06-12", "sell", "化工ETF",        0.819, 500),

    # ── 6/16 ──
    ("2026-06-16", "buy",  "创业板新能源ETF", 1.099, 600),
    ("2026-06-16", "buy",  "工业有色ETF",    0.972, 800),
    ("2026-06-16", "sell", "卫星E",          1.350, 300),
    ("2026-06-16", "sell", "化工ETF",        0.870, 500),

    # ── 6/17 ──
    ("2026-06-17", "buy",  "彩虹股份",       12.00, 200),
    ("2026-06-17", "buy",  "彩虹股份",       11.69, 200),
    ("2026-06-17", "sell", "创业板新能源ETF", 1.093, 600),
    ("2026-06-17", "sell", "电网设备ETF",    2.300, 100),
    ("2026-06-17", "sell", "工业有色ETF",    0.963, 800),
    ("2026-06-17", "sell", "通信ETF",        1.701, 1700),

    # ── 6/18 ──
    ("2026-06-18", "buy",  "莲花控股",       14.73, 300),
    ("2026-06-18", "sell", "彩虹股份",       11.91, 400),

    # ── 6/22 ──
    # 撤单: ("2026-06-22", "buy",  "莲花控股", 14.27, 100, "撤单"),
    ("2026-06-22", "sell", "莲花控股",       15.31, 300),

    # ── 6/23 ──
    ("2026-06-23", "buy",  "三安光电",       19.10, 100),
    ("2026-06-23", "buy",  "三安光电",       19.97, 100),

    # ── 6/24 ──
    ("2026-06-24", "buy",  "彩虹股份",       13.34, 100),
    ("2026-06-24", "buy",  "春秋电子",       26.12, 100),
    ("2026-06-24", "buy",  "春秋电子",       26.43, 100),
    ("2026-06-24", "sell", "三安光电",       21.28, 100),
    ("2026-06-24", "sell", "三安光电",       20.00, 100),

    # ── 6/25 ──
    ("2026-06-25", "buy",  "创元科技",       16.91, 100),
    ("2026-06-25", "buy",  "创元科技",       16.81, 100),
    ("2026-06-25", "buy",  "创元科技",       16.71, 100),
    # 撤单: ("2026-06-25", "buy",  "楚江新材", 15.14, 300, "撤单"),
    ("2026-06-25", "sell", "彩虹股份",       13.41, 100),
    ("2026-06-25", "sell", "春秋电子",       28.99, 100),
    ("2026-06-25", "sell", "春秋电子",       28.80, 100),

    # ── 资金转入/转出 ──
    ("2026-06-01", "deposit",  "CASH", 7000.00, 1, "累计转入"),
    ("2026-06-25", "withdraw", "CASH",  700.00, 1, "转出"),
]


def import_all():
    print("=== StockAI 交易记录导入 ===")
    print()

    # ── 1. 清空旧数据 ──
    print("1. 清空旧数据...")
    execute("DELETE FROM transactions WHERE user_id = ?", (USER_ID,))
    execute("DELETE FROM holdings WHERE user_id = ?", (USER_ID,))
    print("   已清空旧交易记录和持仓")

    # ── 2. 导入交易 ──
    print()
    print("2. 导入交易记录...")

    buy_total = 0.0
    sell_total = 0.0
    import_count = 0
    skip_count = 0

    # 使用批量写入
    statements = []
    for entry in TRANSACTIONS:
        traded_at, direction, name, price, quantity = entry[:5]
        note = entry[5] if len(entry) > 5 else ""

        if direction in ("deposit", "withdraw"):
            # 现金操作
            code = "CASH"
            at = "cash"
            amount = price  # price 就是金额
            fee = 0.0
        else:
            code, at = get_code_info(name)
            if code is None:
                skip_count += 1
                continue

            fee_val = calc_fee(price, quantity, direction, at)
            fee = round(fee_val, 2) if fee_val is not None else 0.0
            if direction == "buy":
                amount = round(price * quantity + fee, 2)
                buy_total += amount
            else:
                amount = round(price * quantity - fee, 2)
                sell_total += amount

        statements.append((
            """INSERT INTO transactions (user_id, stock_code, stock_name, asset_type, direction, price, quantity, amount, fee, traded_at, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (USER_ID, code, name, at, direction, price, quantity, amount, fee, traded_at, note),
        ))
        import_count += 1

    execute_many(statements)
    print(f"   已导入 {import_count} 条")
    if skip_count:
        print(f"   ⚠ 跳过 {skip_count} 条（未知代码）")

    # ── 3. 计算持仓 ──
    print()
    print("3. 重新计算持仓...")

    # 获取所有 buy/sell 交易（按代码汇总）
    all_txns = query_all(
        """SELECT stock_code, stock_name, asset_type, direction, price, quantity, fee, traded_at
           FROM transactions WHERE user_id = ? AND direction IN ('buy', 'sell')
           ORDER BY traded_at, id""",
        (USER_ID,),
    )

    # 按代码汇总：先进先出计算持仓
    holdings_map: dict[str, dict] = {}

    for t in all_txns:
        code = t["stock_code"]
        if code == "CASH":
            continue
        if code not in holdings_map:
            holdings_map[code] = {
                "code": code,
                "name": t["stock_name"],
                "at": t["asset_type"] or detect_asset_type(code),
                "buys": [],
                "sells": [],
            }

        if t["direction"] == "buy":
            holdings_map[code]["buys"].append(t)
        else:
            holdings_map[code]["sells"].append(t)

    # 计算每个代码的当前持仓（FIFO）
    holding_statements = []
    for code, hd in holdings_map.items():
        buys = hd["buys"]
        sells = hd["sells"]

        # 总买入量
        total_bought = sum(b["quantity"] for b in buys)
        total_sold = sum(s["quantity"] for s in sells)
        remaining = total_bought - total_sold

        if remaining > 0:
            # FIFO: 按买入顺序累积到 remaining
            remaining_shares = remaining
            total_cost = 0.0
            for b in buys:
                qty = b["quantity"]
                if qty <= remaining_shares:
                    total_cost += qty * b["price"] + (b.get("fee", 0) or 0)
                    remaining_shares -= qty
                else:
                    total_cost += remaining_shares * b["price"]
                    break

            cost_price = round(total_cost / remaining, 4) if remaining > 0 else 0
            market = get_market(code)

            holding_statements.append((
                """INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, quantity, cost_price, shares)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (USER_ID, code, hd["name"], market, hd["at"], remaining, cost_price, 0),
            ))

            print(f"   {code} {hd['name']}: {remaining}股 成本{cost_price}")

    if holding_statements:
        execute_many(holding_statements)
    else:
        print("   (无持仓)")

    # ── 4. 汇总 ──
    print()
    print("=== 导入完成 ===")
    txns_count = query_one("SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?", (USER_ID,))
    holds_count = query_one("SELECT COUNT(*) as cnt FROM holdings WHERE user_id = ?", (USER_ID,))
    print(f"   交易记录: {txns_count['cnt']} 条")
    print(f"   持仓:     {holds_count['cnt']} 只")

    # 资金汇总
    deposits = query_all(
        "SELECT SUM(price) as total FROM transactions WHERE user_id = ? AND direction = 'deposit'",
        (USER_ID,),
    )
    withdrawals = query_all(
        "SELECT SUM(price) as total FROM transactions WHERE user_id = ? AND direction = 'withdraw'",
        (USER_ID,),
    )
    total_in = deposits[0]["total"] or 0 if deposits else 0
    total_out = withdrawals[0]["total"] or 0 if withdrawals else 0

    print(f"   转入:    {total_in:,.0f} 元")
    print(f"   转出:    {total_out:,.0f} 元")
    print(f"   买卖支出: {buy_total:,.2f} 元")
    print(f"   买卖收入: {sell_total:,.2f} 元")


if __name__ == "__main__":
    import_all()
