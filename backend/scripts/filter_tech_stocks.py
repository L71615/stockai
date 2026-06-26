"""筛选：股价<30 + 主板 + 科技股"""
import sys
sys.path.insert(0, '.')
from services.screener_service import get_all_stock_list
from services.akshare_adapter import get_batch_quotes

# 科技相关行业关键词
TECH_INDUSTRIES = [
    '计算机', '软件', '信息技术', 'IT', '互联网', '通信', '5G', '电信',
    '电子', '半导体', '芯片', '集成电路', '元器件', '光电', '光学',
    '人工智能', '机器人', '自动化', '智能', '数控',
    '航天', '航空', '军工', '卫星', '导航', '雷达', '无人机',
    '消费电子', '电器', '电气', '仪器仪表', '精密',
    '新能源', '光伏', '风电', '电池', '储能', '氢能', '核电',
    '新材料', '稀土', '磁性', '石墨烯',
    '生物', '医药', '制药', '基因', '疫苗',  # 生物科技
    '传媒', '数字', '数据', '云', '大数据', '区块链', '网络安全',
    '新能源汽车', '汽车电子', '无人驾驶', '车联网',
    '高端装备', '高端制造',
]

# 疑似非科技行业（用于二次排除）
NON_TECH_INDUSTRIES = [
    '银行', '保险', '证券', '房地产', '建筑', '建材', '水泥',
    '钢铁', '煤炭', '石油', '化工', '化纤', '化肥',
    '食品', '饮料', '白酒', '啤酒', '乳业', '农业', '养殖', '种植',
    '纺织', '服装', '造纸', '印刷', '包装',
    '零售', '百货', '超市', '贸易', '物流', '港口', '高速', '铁路', '航空运输',
    '电力', '水务', '燃气', '供热',
    '酒店', '旅游', '餐饮',
    '环保', '园林',
    '有色金属', '黄金', '矿业',
]

def is_tech_by_name(name, industry=''):
    """根据名称和行业判断是否为科技股"""
    # 先检查行业
    if industry:
        for kw in TECH_INDUSTRIES:
            if kw in industry:
                # 二次检查：排除伪科技
                for nkw in NON_TECH_INDUSTRIES:
                    if nkw in industry and nkw not in ['新能源', '新材料', '汽车']:
                        return False
                return True

    # 按名称关键词
    tech_name_kw = [
        '科技', '电子', '软件', '数据', '通信', '信息', '网',
        '微', '光电', '半导体', '芯片', '集成',
        '航天', '航空', '卫星', '导航', '雷达',
        '机器人', '智能', '数控', '自动化',
        '新能源', '光伏', '风电', '电池', '储能', '锂',
        '光电', '光学', '激光', '精密', '仪器',
        '材料', '稀土', '磁',
        '生物', '医药', '药', '基因',
        '传媒', '数字', '互联',
    ]
    for kw in tech_name_kw:
        if kw in name:
            return True
    return False

# 1. 获取股票列表
all_stocks = get_all_stock_list(force_refresh=False)
print(f'全池: {len(all_stocks)}')

# 2. 主板过滤
def is_regular(code):
    if code.startswith('688'): return False
    if code.startswith('8'): return False
    if code.startswith('4'): return False
    if code.startswith('300') or code.startswith('301'): return False
    return True

regular = [s for s in all_stocks if is_regular(s['code'])]
print(f'主板: {len(regular)}')

# 3. 获取行情并价格过滤
codes = [s['code'] for s in regular]
quoted_stocks = []

for i in range(0, len(codes), 100):
    batch = codes[i:i+100]
    try:
        quotes = get_batch_quotes(batch)
        for s in regular[i:i+100]:
            q = quotes.get(s['code'])
            if q and q.get('price') and q['price'] > 0 and q['price'] < 30:
                s['price'] = q['price']
                s['change_pct'] = q.get('change_pct', 0)
                quoted_stocks.append(s)
    except Exception as e:
        print(f'  Batch {i} err: {e}')

print(f'股价<30: {len(quoted_stocks)}')

# 4. 科技行业过滤
tech_stocks = []
non_tech_stocks = []

for s in quoted_stocks:
    name = s.get('name', '')
    industry = s.get('industry', '')
    if is_tech_by_name(name, industry):
        tech_stocks.append(s)
    else:
        non_tech_stocks.append(s)

print(f'科技股: {len(tech_stocks)}')
print(f'非科技: {len(non_tech_stocks)}')

# 按板块统计
sh = [x for x in tech_stocks if x['code'].startswith('60')]
sz = [x for x in tech_stocks if x['code'].startswith('00')]
print(f'  沪市: {len(sh)}, 深市: {len(sz)}')

# 输出
tech_stocks.sort(key=lambda x: x['code'])
print(f'\n=== 科技股列表 ({len(tech_stocks)}只) ===')
for s in tech_stocks:
    ind = s.get('industry', '')
    ind_str = f' [{ind}]' if ind else ''
    print(f'{s["code"]} {s["name"]:10s} {s["price"]:8.2f} {s["change_pct"]:+.2f}%{ind_str}')
