"""批量海龟+因子分析（从 cheap_stocks.json 读取）"""
from dotenv import load_dotenv
load_dotenv('.env')
import sys, json, time
from pathlib import Path
sys.path.insert(0, '.')

from services.utils import get_market
from services.factor_service import compute_all_factors
from services.baostock_adapter import get_stock_factors, _ensure_login
# Use fast Tencent K-line directly (avoid slow Baostock fallback)
from services.akshare_adapter import get_kline as fetch_kline

_ensure_login()

# Load cheap stocks
with open('data/cheap_stocks.json', 'r') as f:
    cheap = json.load(f)
print('Total to analyze: {}'.format(len(cheap)))

# Turtle calculation (inlined for speed)
def calc_atr(h, l, c, period=20):
    n = len(c)
    if n < period+1: return None
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1,n)]
    return round(sum(trs[-period:])/period, 4) if len(trs)>=period else None

def calc_turtle(highs, lows, closes):
    n = len(closes)
    if n < 60: return {'turtle_score':0, 'signal':'data_insufficient', 'details':[]}
    price = closes[-1]; prev = closes[-2] if n>=2 else price
    atr_val = calc_atr(highs, lows, closes, 20)
    ph20 = max(highs[-22:-2]) if n>=22 else (max(highs[-21:-1]) if n>=21 else None)
    s1e = round(max(highs[-21:-1]),2) if n>=21 else None
    s1_enter = bool(ph20 and price>ph20 and prev<=ph20)
    ph55 = max(highs[-57:-2]) if n>=57 else (max(highs[-56:-1]) if n>=56 else None)
    s2e = round(max(highs[-56:-1]),2) if n>=56 else None
    s2_enter = bool(ph55 and price>ph55 and prev<=ph55)
    pl10 = min(lows[-12:-2]) if n>=12 else (min(lows[-11:-1]) if n>=11 else None)
    s1x = round(min(lows[-11:-1]),2) if n>=11 else None
    s1_exit = bool(pl10 and price<pl10 and prev>=pl10)
    pl20 = min(lows[-22:-2]) if n>=22 else (min(lows[-21:-1]) if n>=21 else None)
    s2x = round(min(lows[-21:-1]),2) if n>=21 else None
    s2_exit = bool(pl20 and price<pl20 and prev>=pl20)
    dist_s1 = round((s1e-price)/s1e*100,2) if s1e and s1e>0 else None
    dist_s2 = round((s2e-price)/s2e*100,2) if s2e and s2e>0 else None
    pos = None
    if s1e and s1x and (s1e-s1x)>0:
        pos = round((price-s1x)/(s1e-s1x),4); pos = max(0.0, min(1.0, pos))

    score = 0; details = []
    if s1_enter: score+=30; details.append('S1_ENTRY')
    elif dist_s1 is not None and dist_s1<3: score+=15; details.append('NearS1({}%)'.format(dist_s1))
    elif dist_s1 is not None and dist_s1<5: score+=8; details.append('WatchS1({}%)'.format(dist_s1))
    if s2_enter: score+=25; details.append('S2_ENTRY')
    elif dist_s2 is not None and dist_s2<5: score+=12; details.append('NearS2({}%)'.format(dist_s2))
    if pos is not None:
        if pos>0.8: score+=25; details.append('Strong(>80%)')
        elif pos>0.5: score+=18; details.append('BiasStrong(50-80%)')
        elif pos>0.3: score+=10; details.append('Neutral(30-50%)')
        else: score+=3; details.append('Weak(<30%)')
    if s1_exit: score-=20; details.append('S1_EXIT!')
    if s2_exit: score-=15; details.append('S2_EXIT!')
    if atr_val and price>0:
        vr = atr_val/price*100
        if 1.5<=vr<=5: score+=10; details.append('ATR_OK({:.1f}%)'.format(vr))
        elif vr<1.5: score+=5
        else: score+=3
    if s1e and s1x and s1e>0:
        cw = (s1e-s1x)/s1e*100
        if 5<=cw<=25: score+=10
        elif cw>25: score+=5
        else: score+=3
    turtle_score = max(0, min(100, score))
    if s1_exit or s2_exit: sig = 'short'
    elif s1_enter or s2_enter: sig = 'strong_long'
    elif turtle_score>=50 and (pos is None or pos>0.4): sig = 'long'
    elif turtle_score>=35: sig = 'weak_long'
    else: sig = 'neutral'
    return {'turtle_score':turtle_score, 'signal':sig, 'details':details,
            'sys1_entry':s1e, 'sys2_entry':s2e, 'sys1_exit':s1x, 'sys2_exit':s2x,
            'channel_position':pos, 'atr_20':atr_val, 'distance_sys1_pct':dist_s1, 'distance_sys2_pct':dist_s2,
            'sys1_triggered':s1_enter, 'sys2_triggered':s2_enter, 'sys1_exit_triggered':s1_exit, 'sys2_exit_triggered':s2_exit}

def quick_factor(code, closes, highs, lows, volumes, fundamentals):
    try:
        raw = compute_all_factors(code, closes, highs, lows, volumes, fundamentals)
    except:
        return {'score':None, 'hit_count':0}
    factors = raw.get('factors', {})
    scores = []

    # 1. Momentum (ret_5d, ret_20d, ret_60d)
    # Positive momentum is bullish, scale: -10% to +10% maps to 0-100
    for key in ['ret_5d', 'ret_20d', 'ret_60d']:
        v = factors.get(key)
        if v is not None:
            try:
                v = float(v)
                pts = 50 + v * 500  # 0.1 (=10%) -> 100, -0.1 -> 0
                scores.append(min(100, max(0, pts)))
            except: pass

    # 2. RSI (30-70 sweet spot)
    v = factors.get('rsi_14')
    if v is not None:
        try:
            v = float(v)
            if 30 <= v <= 70: pts = 80
            elif v < 30: pts = 40 + v * 1.3
            else: pts = 40 + (100 - v) * 1.3
            scores.append(min(100, max(0, pts)))
        except: pass

    # 3. MACD signal (positive = bullish)
    v = factors.get('macd_signal')
    if v is not None:
        try:
            v = float(v)
            pts = 50 + v * 2000  # 0.02 -> 90, -0.02 -> 10
            scores.append(min(100, max(0, pts)))
        except: pass

    # 4. MA disposition (above MA = bullish)
    v = factors.get('ma_disposition')
    if v is not None:
        try:
            v = float(v)
            pts = 50 + v * 80  # 0.5 -> 90, -0.5 -> 10
            scores.append(min(100, max(0, pts)))
        except: pass

    # 5. Volume ratio (1.0 = normal, >1 = high volume)
    v = factors.get('vol_ratio')
    if v is not None:
        try:
            v = float(v)
            pts = 50 + (v - 1) * 30  # 2.0 -> 80, 0.5 -> 35
            scores.append(min(100, max(0, pts)))
        except: pass

    # 6. Historical volatility (low is better for long)
    v = factors.get('hist_vol_20d')
    if v is not None:
        try:
            v = float(v)
            pts = 100 - v * 150  # 0.2 -> 70, 0.5 -> 25
            scores.append(min(100, max(0, pts)))
        except: pass

    # 7. Strength (20-day price relative strength)
    v = factors.get('strength_20d')
    if v is not None:
        try:
            v = float(v)
            pts = 50 + v * 25  # 1.0 -> 75, 0 -> 50
            scores.append(min(100, max(0, pts)))
        except: pass

    # 8. Momentum composite
    v = factors.get('momentum_composite')
    if v is not None:
        try:
            v = float(v)
            pts = 50 + v * 1000  # small values, scale up
            scores.append(min(100, max(0, pts)))
        except: pass

    # 9. Price position in range
    v = factors.get('price_position')
    if v is not None:
        try:
            v = float(v)
            if v > 0.7: pts = 85  # near high
            elif v > 0.4: pts = 65  # mid-high
            elif v > 0.2: pts = 45  # mid-low
            else: pts = 25  # near low
            scores.append(pts)
        except: pass

    if not scores:
        return {'score': None, 'hit_count': raw.get('hit_count', 0)}
    return {'score': round(sum(scores) / len(scores)), 'hit_count': raw.get('hit_count', 0)}

results = []
t0 = time.time()
for idx, s in enumerate(cheap):
    code = s['code']; price = s['price']; name = s['name']
    try:
        mkt = get_market(code)
        kline = fetch_kline(code, days=120)  # akshare get_kline(code, days)
        if 'error' in kline: continue
        closes = kline.get('closes',[])
        if len(closes) < 60: continue
        turtle = calc_turtle(kline.get('highs',[]), kline.get('lows',[]), closes)
        # Skip slow Baostock fundamentals - our scoring uses technical factors only
        fundamentals = {}
        factor = quick_factor(code, closes, kline.get('highs',[]), kline.get('lows',[]), kline.get('volumes',[]), fundamentals)

        ts = turtle.get('turtle_score',0)
        sig = turtle.get('signal','neutral')
        fs = factor.get('score') or 0
        if ts >= 35 and sig != 'short' and fs >= 40:
            composite = ts*0.45 + fs*0.35
            if not turtle.get('sys1_triggered'):
                dist = turtle.get('distance_sys1_pct')
                if dist is not None and dist > 0: composite += max(0, (5-dist)*2)
            results.append({
                'code':code, 'name':name, 'price':price,
                'turtle_score':ts, 'turtle_signal':sig, 'turtle_details':turtle['details'],
                'sys1_entry':turtle['sys1_entry'], 'sys2_entry':turtle['sys2_entry'],
                'sys1_exit':turtle['sys1_exit'], 'sys2_exit':turtle['sys2_exit'],
                'channel_position':turtle['channel_position'], 'atr_20':turtle['atr_20'],
                'distance_sys1_pct':turtle['distance_sys1_pct'], 'distance_sys2_pct':turtle['distance_sys2_pct'],
                'sys1_triggered':turtle['sys1_triggered'], 'sys2_triggered':turtle['sys2_triggered'],
                'sys1_exit_triggered':turtle['sys1_exit_triggered'], 'sys2_exit_triggered':turtle['sys2_exit_triggered'],
                'factor_score':fs, 'factor_hits':factor.get('hit_count',0),
                'composite_score':round(composite,1)
            })
    except Exception as e:
        pass

    if (idx+1) % 50 == 0:
        elapsed = time.time() - t0
        print('Progress: {}/{} ({:.0f}%) - {:.1f}s - found {} qualified'.format(
            idx+1, len(cheap), 100*(idx+1)/len(cheap), elapsed, len(results)))
        # Save checkpoint
        results.sort(key=lambda x: x['composite_score'], reverse=True)
        with open('data/turtle_results_checkpoint.json', 'w') as f:
            json.dump({'progress':idx+1, 'total':len(cheap), 'qualified':len(results), 'results':results}, f, ensure_ascii=False, indent=2)

# Final
results.sort(key=lambda x: x['composite_score'], reverse=True)
elapsed = time.time() - t0
print('')
print('='*60)
print('DONE: {:.1f}s, {} qualified out of {} analyzed'.format(elapsed, len(results), len(cheap)))
print('='*60)

if results:
    print('')
    print('TOP RESULTS:')
    print('{:4s} {:6s} {:8s} {:>7s} {:>7s} {:>7s} {:>7s}'.format('RANK','CODE','NAME','PRICE','TURTLE','FACTOR','COMP'))
    print('-'*50)
    for i, r in enumerate(results):
        print('{:4d} {:6s} {:8s} {:>7.2f} {:>7d} {:>7d} {:>7.0f}'.format(
            i+1, r['code'], r['name'], r['price'], r['turtle_score'], r['factor_score'], r['composite_score']))
        if i >= 29: break

with open('data/turtle_results_final.json', 'w') as f:
    json.dump({'analyzed_at':time.strftime('%Y-%m-%d %H:%M:%S'), 'total':len(cheap), 'qualified':len(results), 'elapsed':round(elapsed), 'results':results}, f, ensure_ascii=False, indent=2)
print('')
print('Full results saved to data/turtle_results_final.json')
