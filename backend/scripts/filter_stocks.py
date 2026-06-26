"""筛选：股价<30 + 普通A股用户可买（排除科创板/北交所/创业板）"""
import sys
sys.path.insert(0, '.')
from services.screener_service import get_all_stock_list
from services.akshare_adapter import get_batch_quotes

all_stocks = get_all_stock_list(force_refresh=True)
print(f'全A股总数: {len(all_stocks)}')

def is_regular(code):
    """排除科创板(688)、北交所(8/4)、创业板(300/301)"""
    if code.startswith('688'): return False
    if code.startswith('8'): return False
    if code.startswith('4'): return False
    if code.startswith('300') or code.startswith('301'): return False
    return True

regular = [s for s in all_stocks if is_regular(s['code'])]
print(f'主板A股(排除科创/北交/创业): {len(regular)}')

codes = [s['code'] for s in regular]
price_under_30 = []

for i in range(0, len(codes), 100):
    batch = codes[i:i+100]
    try:
        quotes = get_batch_quotes(batch)
        for s in regular[i:i+100]:
            q = quotes.get(s['code'])
            if q and q.get('price') and q['price'] > 0 and q['price'] < 30:
                price_under_30.append({
                    'code': s['code'],
                    'name': s.get('name', ''),
                    'price': q['price'],
                    'chg': q.get('change_pct', 0),
                })
    except Exception as e:
        print(f'  Batch {i} err: {e}')

price_under_30.sort(key=lambda x: x['code'])
print(f'\n股价<30的主板A股: {len(price_under_30)}')

sh = [x for x in price_under_30 if x['code'].startswith('60')]
sz = [x for x in price_under_30 if x['code'].startswith('00')]
print(f'  沪市主板(60xxxx): {len(sh)}')
print(f'  深市主板(00xxxx): {len(sz)}')

print(f'\n=== 前50只(按代码排序) ===')
for s in price_under_30[:50]:
    print(f'{s["code"]} {s["name"]:10s} {s["price"]:8.2f} {s["chg"]:+.2f}%')
