"""8月3日盘后回放: 多策略对比分析

扫描 30+ 只热门股 × 13 个策略, 输出:
1. 策略触发分布(哪些策略最活跃)
2. 股票触发分布(哪些股票最容易触发信号)
3. 详细每只股票 × 每策略 矩阵

数据源: factor_service.MINUTE_FACTOR_REGISTRY + historical_kline (240 根日 K)
       (v4.2 M2 阶段, 真正的 1m/5m K 线留 v5.0-rc)
"""
import sys
sys.path.insert(0, "backend")

from database import init_db, execute
from services.realtime_factor_minute import compute_minute_factors_with_cache, fetch_recent_bars
from services.strategy_backtest_service import _load_strategy_conditions
from services.condition_engine import evaluate

init_db()

STOCKS = [
    # 白酒/消费
    "600519", "000858", "000568", "002304",
    # 银行
    "000001", "600036", "601318", "601398", "601166",
    # 地产
    "000002", "600048", "001979",
    # 医药
    "600276", "000538", "600436", "002415",
    # 科技
    "000725", "002415", "300750", "002594", "002475", "300059",
    # 资源/材料
    "601899", "601088", "600028", "601857",
    # 新能源
    "002460", "601012",
    # 其他
    "600664", "600887", "600030", "601628",
]
STOCKS = sorted(set(STOCKS))

ALL_STRATEGIES = [
    "turtle_s1", "turtle_s2",
    "breakout_pullback",
    "boll_mean",
    "momentum_leader",
    "trend_continuation",
    "ma_bullish",
    "gap_reversal", "rsi_oversold", "oversold_bounce",
    "deep_value",
    "high_div",
    "swing_short",
]

print("=" * 80)
print(f"8月3日盘后回放: {len(STOCKS)} 只股票 × {len(ALL_STRATEGIES)} 个策略")
print("=" * 80)

# 清缓存
for code in STOCKS:
    execute("DELETE FROM minute_factor_cache WHERE stock_code = ?", (code,))

# 加载全部策略 condition tree
strategy_trees = {}
for sid in ALL_STRATEGIES:
    tree = _load_strategy_conditions([sid])
    if tree:
        strategy_trees[sid] = tree
    else:
        print(f"[WARN] {sid} 无法加载")

# 扫描
results_matrix = {}
factor_cache = {}

for code in STOCKS:
    try:
        closes, highs, lows, opens, volumes = fetch_recent_bars(code, limit=240)
        if not closes or len(closes) < 30:
            continue
        factors = compute_minute_factors_with_cache(
            code=code, closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
        )
        factor_cache[code] = factors
        results_matrix[code] = {}
        for sid, tree in strategy_trees.items():
            try:
                hit = evaluate(factors, tree)
                results_matrix[code][sid] = hit
            except Exception:
                results_matrix[code][sid] = None
    except Exception:
        pass

# ========================
# 输出 1: 策略触发分布
# ========================
print()
print("=" * 80)
print("【1】策略触发分布")
print("=" * 80)
strategy_trigger_count = {}
for code, results in results_matrix.items():
    for sid, hit in results.items():
        if hit:
            strategy_trigger_count[sid] = strategy_trigger_count.get(sid, 0) + 1

print(f"{'策略 ID':<22} {'触发数':<8} {'触发率':<10}")
print("-" * 50)
for sid in ALL_STRATEGIES:
    cnt = strategy_trigger_count.get(sid, 0)
    rate = cnt / len(STOCKS) * 100
    bar = "#" * int(cnt * 2)
    print(f"  {sid:<20} {cnt:>3}       {rate:>5.1f}%  {bar}")

# ========================
# 输出 2: 股票触发分布
# ========================
print()
print("=" * 80)
print("【2】股票触发分布")
print("=" * 80)
stock_trigger_count = []
for code, results in results_matrix.items():
    triggered = [sid for sid, hit in results.items() if hit]
    stock_trigger_count.append((code, len(triggered), triggered))

stock_trigger_count.sort(key=lambda x: -x[1])
print(f"{'代码':<8} {'触发数':<8} {'触发的策略'}")
print("-" * 80)
for code, cnt, triggered in stock_trigger_count:
    if cnt > 0:
        print(f"  {code:<6} {cnt:>3}       {','.join(triggered)}")
print()
print("未触发股票 (25 只):")
for code, cnt, triggered in stock_trigger_count:
    if cnt == 0:
        factors = factor_cache.get(code, {})
        rsi = factors.get('rsi_14', 0)
        ret_20 = (factors.get('ret_20d') or 0) * 100
        print(f"  {code:<6} RSI={rsi:5.1f}  ret_20d={ret_20:+6.2f}%")

# ========================
# 输出 3: 详细矩阵
# ========================
print()
print("=" * 80)
print("【3】股票 × 策略 详细矩阵 (X = 触发)")
print("=" * 80)

header = f"{'代码':<7}"
for sid in ALL_STRATEGIES:
    header += f"{sid[:5]:<6}"
print(header)
print("-" * len(header))

for code in sorted(results_matrix.keys()):
    row = f"  {code:<5}"
    for sid in ALL_STRATEGIES:
        hit = results_matrix[code].get(sid)
        if hit is True:
            row += "X    "
        elif hit is False:
            row += ".    "
        else:
            row += "?    "
    print(row)

# ========================
# 输出 4: 关键股票因子摘要
# ========================
print()
print("=" * 80)
print("【4】所有 31 只股票 因子摘要")
print("=" * 80)
print(f"{'代码':<8} {'close':<8} {'RSI':<6} {'ret_20d%':<10} {'ret_5d%':<9} {'ma5%':<8} {'ma20%':<8} {'boll_pos':<10} {'vol_ratio':<10}")
print("-" * 100)
for code in sorted(factor_cache.keys()):
    factors = factor_cache[code]
    print(f"  {code:<6} {factors.get('close',0):<8.2f} {factors.get('rsi_14',0):<6.1f} "
          f"{(factors.get('ret_20d') or 0)*100:<+10.2f} {(factors.get('ret_5d') or 0)*100:<+9.2f} "
          f"{(factors.get('ma5') or 0)*100:<+8.2f} {(factors.get('ma20') or 0)*100:<+8.2f} "
          f"{factors.get('boll_position',0):<10.3f} {factors.get('vol_ratio',0):<10.3f}")

# 汇总
total_signals = sum(strategy_trigger_count.values())
print()
print("=" * 80)
print(f"汇总: {total_signals} 个信号触发 / {len(STOCKS) * len(strategy_trees)} 评估")
print(f"平均每只股票触发 {total_signals / len(STOCKS):.2f} 个策略")
print("=" * 80)