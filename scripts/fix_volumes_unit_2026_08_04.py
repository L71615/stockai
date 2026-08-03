"""修复 historical_kline 最近 ~10 天 volume 单位异常 bug (2026-08-04)

Bug 描述:
  2026-07-06/07 之间某个夜间脚本从 akshare/sina 写入历史 K 线,volume 单位是"手",
  但 build_history.py 用 baostock 写入的单位是"股"。两个数据源不一致导致 vol_ratio
  (5日均量/20日均量) 计算异常 — scanner 31 只热门股只触发 1 个信号。

修复策略:
  1. 找到 volume 单位切换点 (本例: 2026-07-07)
  2. 该点之后: volume × 100 (手 → 股)
  3. 写入 audit log + 重建 minute_factor_cache

使用:
  python scripts/fix_volumes_unit_2026_08_04.py
"""
import sys
sys.path.insert(0, "backend")

from database import init_db, execute, query_all, get_db
from datetime import datetime

init_db()

# 1. 找到切换点: 同一只股票连续两天 volume 差异 100x 就是切换
print("=" * 70)
print("Step 1: 检测切换点")
print("=" * 70)

# 用 000001 测
rows = query_all("""
    SELECT trade_date, volume
    FROM historical_kline
    WHERE stock_code = '000001'
    ORDER BY trade_date DESC
    LIMIT 30
""")

# 找连续两天 ratio > 50 的日期
cutoff_date = None
for i in range(len(rows) - 1):
    v_new = rows[i]["volume"]
    v_old = rows[i + 1]["volume"]
    if v_old and v_old > 0 and v_new and v_new > 0:
        ratio = v_old / v_new
        if ratio > 50:  # 100x 容错
            cutoff_date = rows[i]["trade_date"]
            print(f"  检测到切换: {rows[i+1]['trade_date']} ({v_old:.0f}) -> {rows[i]['trade_date']} ({v_new:.0f}), ratio={ratio:.1f}x")
            break

if not cutoff_date:
    # 默认 fallback: 2026-07-07 (从 akshare 写入开始)
    cutoff_date = "2026-07-07"
    print(f"  未检测到明显切换, 使用默认 cutoff: {cutoff_date}")

print(f"\nCutoff date (含): {cutoff_date}")

# 2. 看 cutoff_date 之后的统计
print("\n" + "=" * 70)
print(f"Step 2: 修复前 {cutoff_date} 之后的数据")
print("=" * 70)

count_before = query_one_count = query_all(f"""
    SELECT COUNT(*) as cnt, AVG(volume) as avg_v
    FROM historical_kline
    WHERE trade_date >= '{cutoff_date}' AND volume IS NOT NULL
""")[0]
print(f"  cutoff 后总记录: {count_before['cnt']}")
print(f"  平均 volume: {count_before['avg_v']:,.0f}")

# 3. 修复: volume × 100
print("\n" + "=" * 70)
print(f"Step 3: 执行修复 (volume × 100) [DRY RUN = False]")
print("=" * 70)

DRY_RUN = False  # 改成 True 试运行

conn = get_db()
try:
    if DRY_RUN:
        # 只打印不修改
        rows = query_all(f"""
            SELECT stock_code, trade_date, volume,
                   CAST(volume * 100 AS INTEGER) as new_volume
            FROM historical_kline
            WHERE trade_date >= '{cutoff_date}'
            LIMIT 10
        """)
        for r in rows:
            print(f"  {r['stock_code']} {r['trade_date']} {r['volume']:>15.0f} -> {r['new_volume']:>15.0f}")
        print(f"\n[DRY RUN] 实际未修改。设置 DRY_RUN=False 真实执行")
    else:
        # 真实修改
        cursor = conn.execute(f"""
            UPDATE historical_kline
            SET volume = CAST(volume * 100 AS INTEGER)
            WHERE trade_date >= '{cutoff_date}' AND volume IS NOT NULL
        """)
        affected = cursor.rowcount
        conn.commit()
        print(f"  UPDATE 影响行数: {affected}")

        # 验证
        count_after = query_all(f"""
            SELECT COUNT(*) as cnt, AVG(volume) as avg_v
            FROM historical_kline
            WHERE trade_date >= '{cutoff_date}' AND volume IS NOT NULL
        """)[0]
        print(f"  修复后平均 volume: {count_after['avg_v']:,.0f}")
        print(f"  (修复前: {count_before['avg_v']:,.0f})")
finally:
    conn.close()

# 4. 清掉 minute_factor_cache (强制重算)
print("\n" + "=" * 70)
print("Step 4: 清 minute_factor_cache (5m TTL 失效)")
print("=" * 70)
if not DRY_RUN:
    deleted = execute("DELETE FROM minute_factor_cache")
    print(f"  清掉 cache 行数: {deleted}")

print("\n" + "=" * 70)
print("Step 5: 验证修复 (扫 002460 重新看 vol_ratio)")
print("=" * 70)

from services.realtime_factor_minute import compute_minute_factors_with_cache, fetch_recent_bars

code = "002460"
closes, highs, lows, opens, volumes = fetch_recent_bars(code, limit=240)
factors = compute_minute_factors_with_cache(
    code=code, closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
)
print(f"  [{code}] 修复后:")
print(f"    RSI={factors.get('rsi_14', 0):.1f}")
print(f"    ret_20d={(factors.get('ret_20d') or 0) * 100:+.2f}%")
print(f"    ret_5d={(factors.get('ret_5d') or 0) * 100:+.2f}%")
print(f"    vol_ratio={factors.get('vol_ratio', 0):.3f}")
print(f"    boll_position={factors.get('boll_position', 0):.3f}")

print("\n" + "=" * 70)
print("完成!")
print("=" * 70)