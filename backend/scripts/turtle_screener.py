"""海龟+因子 联合选股脚本 (批量优化版)
筛选条件：
  1. 现价 < 35元
  2. 海龟交易法则做多信号
  3. 因子体系判定做多

用法：
  cd backend
  python -u scripts/turtle_screener.py
"""

import sys
import os
import time
import json
import io
import re
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 确保 backend 在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 加载 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 强制 UTF-8 输出 (仅交互模式)
if sys.stdout.isatty():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
else:
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)

from services.utils import get_market
from services.technical import fetch_kline
from services.factor_service import compute_all_factors
from services.baostock_adapter import get_stock_factors, _ensure_login

UA = "Mozilla/5.0"


# ============================================================
# 批量获取实时价格 (腾讯API，单次最多50个)
# ============================================================

def batch_get_prices(codes, batch_size=50):
    """批量获取实时价格，返回 {code: (price, name), ...}"""
    result = {}
    total = len(codes)

    for batch_start in range(0, total, batch_size):
        batch = codes[batch_start:batch_start + batch_size]
        symbols = []
        code_to_symbol = {}
        for c in batch:
            c = str(c).strip()
            if c.startswith(("51", "56", "58", "60", "68")):
                sym = "sh" + c
            else:
                sym = "sz" + c
            symbols.append(sym)
            code_to_symbol[sym] = c

        try:
            url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="replace")

            for line in raw.strip().split("\n"):
                m = re.search(r'="(.+)"', line)
                if not m:
                    continue
                parts = m.group(1).split("~")
                if len(parts) < 33:
                    continue
                # parts[2]=code, parts[1]=name, parts[3]=price
                code = parts[2].strip()
                try:
                    price = float(parts[3])
                except (ValueError, TypeError):
                    continue
                if price > 0:
                    name = parts[1].strip()
                    result[code] = (price, name)
        except Exception as e:
            print("  批量查询失败 (batch {}): {}".format(batch_start // batch_size + 1, str(e)[:80]))
            continue

        # 温柔限速
        time.sleep(0.3)
        if (batch_start // batch_size + 1) % 5 == 0:
            print("  价格查询: {}/{} 批".format(batch_start // batch_size + 1, (total + batch_size - 1) // batch_size))

    return result


# ============================================================
# 海龟交易法计算
# ============================================================

def calc_atr(highs, lows, closes, period=20):
    n = len(closes)
    if n < period + 1:
        return None
    trs = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return None
    return round(sum(trs[-period:]) / period, 4)


def calc_turtle(highs, lows, closes):
    n = len(closes)
    if n < 60:
        return {"error": "K线不足60天", "turtle_score": 0, "signal": "data_insufficient"}

    price = closes[-1]
    prev = closes[-2] if n >= 2 else price
    atr_val = calc_atr(highs, lows, closes, 20)

    # S1 入场: 20日高点突破
    ph20 = max(highs[-22:-2]) if n >= 22 else max(highs[-21:-1]) if n >= 21 else None
    s1e = round(max(highs[-21:-1]), 2) if n >= 21 else None
    s1_enter = bool(ph20 and price > ph20 and prev <= ph20)

    # S2 入场: 55日高点突破
    ph55 = max(highs[-57:-2]) if n >= 57 else max(highs[-56:-1]) if n >= 56 else None
    s2e = round(max(highs[-56:-1]), 2) if n >= 56 else None
    s2_enter = bool(ph55 and price > ph55 and prev <= ph55)

    # S1 出场: 10日低点跌破
    pl10 = min(lows[-12:-2]) if n >= 12 else min(lows[-11:-1]) if n >= 11 else None
    s1x = round(min(lows[-11:-1]), 2) if n >= 11 else None
    s1_exit = bool(pl10 and price < pl10 and prev >= pl10)

    # S2 出场: 20日低点跌破
    pl20 = min(lows[-22:-2]) if n >= 22 else min(lows[-21:-1]) if n >= 21 else None
    s2x = round(min(lows[-21:-1]), 2) if n >= 21 else None
    s2_exit = bool(pl20 and price < pl20 and prev >= pl20)

    # 距入场距离
    dist_s1 = round((s1e - price) / s1e * 100, 2) if s1e and s1e > 0 else None
    dist_s2 = round((s2e - price) / s2e * 100, 2) if s2e and s2e > 0 else None

    # 通道位置 (0~1)
    pos = None
    if s1e and s1x and (s1e - s1x) > 0:
        pos = round((price - s1x) / (s1e - s1x), 4)
        pos = max(0.0, min(1.0, pos))

    # === 海龟评分 ===
    score = 0
    details = []

    if s1_enter:
        score += 30
        details.append("S1入场触发(20日高点突破)")
    elif dist_s1 is not None and dist_s1 < 3:
        score += 15
        details.append("近S1入场(距{}%)".format(dist_s1))
    elif dist_s1 is not None and dist_s1 < 5:
        score += 8
        details.append("观察区S1(距{}%)".format(dist_s1))

    if s2_enter:
        score += 25
        details.append("S2入场触发(55日高点突破)")
    elif dist_s2 is not None and dist_s2 < 5:
        score += 12
        details.append("近S2入场(距{}%)".format(dist_s2))

    if pos is not None:
        if pos > 0.8:
            score += 25; details.append("强势区间(>80%)")
        elif pos > 0.5:
            score += 18; details.append("偏强区间(50-80%)")
        elif pos > 0.3:
            score += 10; details.append("中性区间(30-50%)")
        else:
            score += 3; details.append("弱势区间(<30%)")

    if s1_exit:
        score -= 20; details.append("S1出场触发!")
    if s2_exit:
        score -= 15; details.append("S2出场触发!")

    if atr_val and price > 0:
        vol_r = atr_val / price * 100
        if 1.5 <= vol_r <= 5:
            score += 10; details.append("ATR适中({:.1f}%)".format(vol_r))
        elif vol_r < 1.5:
            score += 5; details.append("ATR偏低({:.1f}%)".format(vol_r))
        else:
            score += 3; details.append("ATR偏高({:.1f}%)".format(vol_r))

    if s1e and s1x and s1e > 0:
        cw = (s1e - s1x) / s1e * 100
        if 5 <= cw <= 25:
            score += 10; details.append("通道适中({:.1f}%)".format(cw))
        elif cw > 25:
            score += 5; details.append("通道偏宽({:.1f}%)".format(cw))
        else:
            score += 3; details.append("通道偏窄({:.1f}%)".format(cw))

    turtle_score = max(0, min(100, score))

    # 做多信号判定
    if s1_exit or s2_exit:
        long_signal = "short"
    elif s1_enter or s2_enter:
        long_signal = "strong_long"
    elif turtle_score >= 50 and (pos is None or pos > 0.4):
        long_signal = "long"
    elif turtle_score >= 35:
        long_signal = "weak_long"
    else:
        long_signal = "neutral"

    return {
        "atr_20": atr_val, "sys1_entry": s1e, "sys2_entry": s2e,
        "sys1_exit": s1x, "sys2_exit": s2x,
        "sys1_triggered": s1_enter, "sys2_triggered": s2_enter,
        "sys1_exit_triggered": s1_exit, "sys2_exit_triggered": s2_exit,
        "distance_sys1_pct": dist_s1, "distance_sys2_pct": dist_s2,
        "channel_position": pos, "turtle_score": turtle_score,
        "signal": long_signal, "details": details,
    }


# ============================================================
# 因子评分
# ============================================================

def quick_factor_score(code, closes, highs, lows, volumes, fundamentals):
    try:
        raw = compute_all_factors(code, closes, highs, lows, volumes, fundamentals)
    except Exception:
        return {"score": None, "hit_count": 0, "error": "factor computation failed"}

    factors = raw.get("factors", {})
    hit_count = raw.get("hit_count", 0)
    scores = []

    # 20日动量
    v = factors.get("momentum_20d")
    if v is not None:
        try:
            scores.append(min(100, max(0, 50 + float(v) * 500)))
        except (TypeError, ValueError):
            pass

    # 60日动量
    v = factors.get("momentum_60d")
    if v is not None:
        try:
            scores.append(min(100, max(0, 50 + float(v) * 200)))
        except (TypeError, ValueError):
            pass

    # RSI
    v = factors.get("rsi_14")
    if v is not None:
        try:
            v = float(v)
            if 30 <= v <= 70:
                pts = 80
            elif v < 30:
                pts = 40 + v * 1.3
            else:
                pts = 40 + (100 - v) * 1.3
            scores.append(min(100, max(0, pts)))
        except (TypeError, ValueError):
            pass

    # MACD
    v = factors.get("macd")
    if v is not None:
        try:
            scores.append(min(100, max(0, 50 + float(v) * 2000)))
        except (TypeError, ValueError):
            pass

    # 波动率 (负向)
    v = factors.get("volatility_20d")
    if v is not None:
        try:
            scores.append(min(100, max(0, 100 - float(v) * 200)))
        except (TypeError, ValueError):
            pass

    # 量比
    v = factors.get("volume_ratio")
    if v is not None:
        try:
            scores.append(min(100, max(0, 50 + (float(v) - 1) * 30)))
        except (TypeError, ValueError):
            pass

    # 均线位置
    v = factors.get("ma_disposition")
    if v is not None:
        try:
            scores.append(min(100, max(0, 50 + float(v) * 80)))
        except (TypeError, ValueError):
            pass

    if not scores:
        return {"score": None, "hit_count": hit_count, "error": "no scorable factors"}

    return {"score": round(sum(scores) / len(scores)), "hit_count": hit_count}


# ============================================================
# 分析单只股票
# ============================================================

def analyze_stock(stock_info):
    code = stock_info["code"]
    price = stock_info["price"]
    name = stock_info["name"]
    market = get_market(code)

    try:
        kline = fetch_kline(code, market, days=120)
        if "error" in kline:
            return None

        closes = kline.get("closes", [])
        highs = kline.get("highs", [])
        lows = kline.get("lows", [])
        volumes = kline.get("volumes", [])

        if len(closes) < 60:
            return None

        turtle = calc_turtle(highs, lows, closes)

        try:
            fundamentals = get_stock_factors(code)
        except Exception:
            fundamentals = {}

        factor_result = quick_factor_score(code, closes, highs, lows, volumes, fundamentals)

        return {"code": code, "name": name, "price": price, "turtle": turtle, "factor": factor_result}
    except Exception:
        return None


# ============================================================
# 主流程
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("  Turtle + Multi-Factor Combined Screener")
    print("  Filters: Price<35 | Turtle LONG | Factor LONG")
    print("=" * 70)

    # [1] 获取股票列表
    print("\n[1/4] Fetching A-share list...")
    from services.screener_service import get_all_stock_list
    all_stocks = get_all_stock_list()
    core = [s for s in all_stocks if s.get("code") and len(s["code"]) == 6]
    print("  Core pool (6-digit): {} stocks".format(len(core)))

    # [2] 批量获取价格
    print("\n[2/4] Batch fetching prices (Tencent API, 50/batch)...")
    codes = [s["code"] for s in core]
    price_map = batch_get_prices(codes, batch_size=50)
    print("  Valid quotes: {}".format(len(price_map)))

    cheap = []
    for code, (price, name) in price_map.items():
        if price < 35:
            cheap.append({"code": code, "name": name, "price": price})
    print("  Price < 35: {} stocks".format(len(cheap)))

    if not cheap:
        print("\n  No stocks under 35 yuan found!")
        return

    # [3] 海龟+因子
    print("\n[3/4] Turtle channels + Factor scoring (concurrent, 5 workers)...")

    _ensure_login()

    results = []
    completed = 0
    total = len(cheap)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(analyze_stock, s): s for s in cheap}
        for future in as_completed(futures):
            completed += 1
            if completed % 20 == 0 or completed == total:
                print("  Progress: {}/{} ({}%)".format(completed, total, 100 * completed // total))
            try:
                r = future.result()
                if r:
                    results.append(r)
            except Exception:
                pass

    print("  Analyzed: {} stocks".format(len(results)))

    # [4] 综合筛选
    print("\n[4/4] Composite screening...")

    qualified = []
    for r in results:
        turtle = r["turtle"]
        factor = r["factor"]
        ts = turtle.get("turtle_score", 0)
        sig = turtle.get("signal", "neutral")
        fs = factor.get("score") or 0

        # 条件：海龟评分>=35 且不是short，因子>=40
        if ts >= 35 and sig != "short" and fs >= 40:
            composite = ts * 0.45 + fs * 0.35
            if not turtle.get("sys1_triggered"):
                dist = turtle.get("distance_sys1_pct")
                if dist is not None and dist > 0:
                    composite += max(0, (5 - dist) * 2)

            qualified.append({
                "code": r["code"], "name": r["name"], "price": r["price"],
                "turtle_score": ts, "turtle_signal": sig,
                "turtle_details": turtle.get("details", []),
                "sys1_entry": turtle.get("sys1_entry"),
                "sys2_entry": turtle.get("sys2_entry"),
                "sys1_exit": turtle.get("sys1_exit"),
                "sys2_exit": turtle.get("sys2_exit"),
                "channel_position": turtle.get("channel_position"),
                "atr_20": turtle.get("atr_20"),
                "distance_sys1_pct": turtle.get("distance_sys1_pct"),
                "distance_sys2_pct": turtle.get("distance_sys2_pct"),
                "sys1_triggered": turtle.get("sys1_triggered"),
                "sys2_triggered": turtle.get("sys2_triggered"),
                "factor_score": fs, "factor_hits": factor.get("hit_count", 0),
                "composite_score": round(composite, 1),
            })

    qualified.sort(key=lambda x: x["composite_score"], reverse=True)

    # === 输出 ===
    print("\n" + "=" * 70)
    print("  RESULTS: {} stocks meet ALL criteria".format(len(qualified)))
    print("=" * 70)

    if not qualified:
        print("\n  No stocks meet all three criteria simultaneously.")
        print("  Relaxed view - Top 10 by Turtle Score:")
        by_turtle = sorted(results, key=lambda x: x["turtle"].get("turtle_score", 0), reverse=True)[:10]
        print("\n  {:6s} {:8s} {:>8s} {:>6s} {:>6s} {:12s}".format(
            "CODE", "NAME", "PRICE", "TURTLE", "FACTOR", "SIGNAL"))
        print("  " + "-" * 55)
        for r in by_turtle:
            t = r["turtle"]
            f = r["factor"]
            print("  {:6s} {:8s} {:>8.2f} {:>6d} {:>6s} {:12s}".format(
                r['code'], r['name'], r['price'],
                t.get('turtle_score', 0), str(f.get('score') or 'N/A'),
                t.get('signal', '?')))
        return

    # 分级
    strong = [q for q in qualified if q["composite_score"] >= 70]
    good = [q for q in qualified if 55 <= q["composite_score"] < 70]
    watch = [q for q in qualified if q["composite_score"] < 55]

    def print_group(title, stocks):
        if not stocks:
            return
        print("\n  " + "-" * 65)
        print("  {} ({} stocks)".format(title, len(stocks)))
        print("  " + "-" * 65)
        for i, s in enumerate(stocks):
            print("\n  {}. {} {}  CNY {:.2f}".format(i + 1, s['code'], s['name'], s['price']))
            print("     Composite: {:.0f} | Turtle: {} | Factor: {}".format(
                s['composite_score'], s['turtle_score'], s['factor_score']))
            print("     Turtle: {}".format(', '.join(s['turtle_details'])))
            print("     Channel: S1e={} S1x={} S2e={} S2x={}".format(
                s['sys1_entry'], s['sys1_exit'], s['sys2_entry'], s['sys2_exit']))
            if s.get("channel_position") is not None:
                print("     Pos: {:.1%} | ATR20: {} | dS1: {}% | dS2: {}%".format(
                    s['channel_position'], s['atr_20'],
                    s['distance_sys1_pct'], s['distance_sys2_pct']))
            s1m = "YES" if s['sys1_triggered'] else "no"
            s2m = "YES" if s['sys2_triggered'] else "no"
            print("     Triggered: S1={} S2={}".format(s1m, s2m))

    print_group("*** STRONG BUY (composite>=70)", strong)
    print_group("**  BUY (composite 55-69)", good)
    print_group("*   WATCH (composite<55)", watch)

    # 保存结果
    output_file = Path(__file__).resolve().parent.parent / "data" / "turtle_screener_result.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "screened_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_screened": len(cheap),
            "qualified": len(qualified),
            "elapsed_seconds": round(time.time() - t0),
            "results": qualified,
        }, f, ensure_ascii=False, indent=2)
    print("\n  Results saved to: {}".format(output_file))

    # 汇总表
    print("\n" + "=" * 70)
    print("  SUMMARY TABLE")
    print("=" * 70)
    print("\n  {:4s} {:6s} {:8s} {:>8s} {:>8s} {:>8s} {:>8s}".format(
        "RANK", "CODE", "NAME", "PRICE", "TURTLE", "FACTOR", "COMPOS"))
    print("  " + "-" * 55)
    for i, s in enumerate(qualified):
        print("  {:4d} {:6s} {:8s} {:>8.2f} {:>8d} {:>8d} {:>8.0f}".format(
            i + 1, s['code'], s['name'], s['price'],
            s['turtle_score'], s['factor_score'], s['composite_score']))

    print("\n  Total time: {:.1f} seconds".format(time.time() - t0))
    print("=" * 70)


if __name__ == "__main__":
    main()
