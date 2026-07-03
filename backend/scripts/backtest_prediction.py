"""回测验证预测引擎 — 用历史数据模拟真实预测场景"""

import sys, os, time
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import query_all
from services.historical_panel import build_panel_for_date
from services.similarity_service import find_similar_periods, aggregate_prediction
from services.screener_service import get_all_stock_list

# ═══════════════════════════════════════════════════════════
# 1. 构建历史面板（最近 N 个交易日）
# ═══════════════════════════════════════════════════════════

print("Loading dates...")
dates = query_all(
    "SELECT DISTINCT trade_date FROM historical_kline ORDER BY trade_date ASC"
)
all_dates = [d["trade_date"] for d in dates]
print(f"Available: {len(all_dates)} trading days ({all_dates[0]} ~ {all_dates[-1]})")

# 用最后 60 天中每隔 5 天取一个作为测试日（避免构建太多面板）
test_dates = all_dates[-60::5]  # ~12 test dates
print(f"Will test {len(test_dates)} dates")

pool = get_all_stock_list()
codes = [s["code"] for s in pool[:100]]  # Top 100 for speed
print(f"Stock pool: {len(codes)}")

# 构建面板
print("\nBuilding historical panels...")
panels = []
for i, d in enumerate(test_dates):
    panel = build_panel_for_date(d, codes)
    panels.append(panel)
    if panel["count"] > 0:
        print(f"  {i+1}/{len(test_dates)}: {d} — {panel['count']} stocks")

print(f"\nTotal panels: {len(panels)}")

# ═══════════════════════════════════════════════════════════
# 2. 模拟预测
# ═══════════════════════════════════════════════════════════

print("\n--- Backtest: Simulating Predictions ---")
results_all = []

for panel in panels:
    date = panel["date"]
    stocks = panel.get("stocks", {})
    if len(stocks) < 10:
        continue

    # 对每只股票，用其他面板的历史数据找相似时刻
    other_panels = [p for p in panels if p["date"] != date]

    predictions = []
    for code, data in stocks.items():
        factors = data.get("factors", {})
        if len(factors) < 10:
            continue
        matches = find_similar_periods(factors, other_panels, top_k=20)
        pred = aggregate_prediction(matches)
        pred["code"] = code
        pred["fwd_ret_1d_actual"] = data.get("fwd_ret_1d")
        pred["fwd_ret_3d_actual"] = data.get("fwd_ret_3d")
        predictions.append(pred)

    # 按预测概率排序，取 Top 10
    predictions.sort(key=lambda x: x.get("probability_1d") or 0, reverse=True)
    top10 = predictions[:10]
    top5 = predictions[:5]

    r = {
        "date": date,
        "total_stocks": len(stocks),
        "top5": top5,
        "top10": top10,
        "top5_avg_prob": round(sum(p.get("probability_1d") or 0 for p in top5) / max(len(top5), 1), 4),
        "top5_avg_ret": round(sum(p.get("fwd_ret_1d_actual") or 0 for p in top5) / max(len(top5), 1), 4),
        "top10_avg_prob": round(sum(p.get("probability_1d") or 0 for p in top10) / max(len(top10), 1), 4),
        "top10_avg_ret": round(sum(p.get("fwd_ret_1d_actual") or 0 for p in top10) / max(len(top10), 1), 4),
    }
    results_all.append(r)
    print(f"  {date}: Top5 prob={r['top5_avg_prob']} ret={r['top5_avg_ret']:.2%}  "
          f"Top10 prob={r['top10_avg_prob']} ret={r['top10_avg_ret']:.2%}")

# ═══════════════════════════════════════════════════════════
# 3. 汇总统计
# ═══════════════════════════════════════════════════════════

print("\n--- Summary ---")
valid = [r for r in results_all if r["top5_avg_ret"] != 0]
if valid:
    avg_top5_ret = sum(r["top5_avg_ret"] for r in valid) / len(valid)
    avg_top10_ret = sum(r["top10_avg_ret"] for r in valid) / len(valid)
    avg_top5_prob = sum(r["top5_avg_prob"] for r in valid) / len(valid)

    # Win rate: how many days did top5 have positive return?
    top5_wins = sum(1 for r in valid if r["top5_avg_ret"] > 0)
    top10_wins = sum(1 for r in valid if r["top10_avg_ret"] > 0)

    print(f"Test dates: {len(valid)}")
    print(f"Top 5 平均收益: {avg_top5_ret:.2%}")
    print(f"Top 10 平均收益: {avg_top10_ret:.2%}")
    print(f"Top 5 胜率(正收益天数): {top5_wins}/{len(valid)} = {top5_wins/len(valid):.0%}")
    print(f"Top 10 胜率(正收益天数): {top10_wins}/{len(valid)} = {top10_wins/len(valid):.0%}")
    print(f"Top 5 平均预测概率: {avg_top5_prob:.2%}")
else:
    print("No valid results — need more historical data with forward return labels")
