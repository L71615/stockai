"""一次性构建历史 K 线数据库 — 从 Baostock 拉取 800 只股票各 252 天数据"""

import sys, os, time
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import get_db, init_db
from services.screener_service import get_all_stock_list
from services.baostock_adapter import get_kline

init_db()
stocks = get_all_stock_list()
print(f"股票池: {len(stocks)} 只, 开始拉取历史K线...")

conn = get_db()
total = 0

try:
    for i, s in enumerate(stocks):
        code = s["code"]
        try:
            kline = get_kline(code, days=300)
            if "error" in kline:
                continue
            dates = kline.get("dates", [])
            opens = kline.get("opens", [])
            highs = kline.get("highs", [])
            lows = kline.get("lows", [])
            closes = kline.get("closes", [])
            volumes = kline.get("volumes", [])

            count = 0
            for j, d in enumerate(dates):
                conn.execute(
                    """INSERT OR IGNORE INTO historical_kline
                       (stock_code, trade_date, open, high, low, close, volume)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (code, d, opens[j], highs[j], lows[j], closes[j], volumes[j]),
                )
                count += 1
            total += count
        except Exception as e:
            print(f"  {code}: 失败 - {e}")

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  {i+1}/{len(stocks)} 已完成, {total} 条K线", flush=True)

    conn.commit()
    print(f"完成! 共 {total} 条K线记录")
finally:
    conn.close()
