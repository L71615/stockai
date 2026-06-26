"""v2: 用 akshare 行业分类 + 更精准的科技关键词"""
import sys
sys.path.insert(0, '.')
from services.screener_service import get_all_stock_list
from services.akshare_adapter import get_batch_quotes

# ── 1. 获取股票池 ──
all_stocks = get_all_stock_list(force_refresh=False)
print(f'全池: {len(all_stocks)}')

def is_regular(code):
    if code.startswith('688'): return False
    if code.startswith('8'): return False
    if code.startswith('4'): return False
    if code.startswith('300') or code.startswith('301'): return False
    return True

regular = [s for s in all_stocks if is_regular(s['code'])]
print(f'主板: {len(regular)}')

# ── 2. 尝试用 akshare 获取行业分类 ──
print('获取行业分类...')
industry_map = {}
try:
    import akshare as ak
    df = ak.stock_board_industry_name_em()
    # 这个返回的是行业板块列表，不是个股行业
except Exception:
    pass

# 用东方财富获取个股行业 (通过 stock_individual_info_em)
try:
    import akshare as ak
    # 先获取申万行业分类
    df_sw = ak.stock_info_sz_name_code()  # 深市
except Exception:
    pass

# 尝试用 get_stock_factors_http 获取行业
from services.akshare_adapter import get_stock_factors_http

# ── 3. 获取行情并初步过滤 ──
codes = [s['code'] for s in regular]
quoted = []
print('获取行情...')
for i in range(0, len(codes), 100):
    batch = codes[i:i+100]
    try:
        quotes = get_batch_quotes(batch)
        for s in regular[i:i+100]:
            q = quotes.get(s['code'])
            if q and q.get('price') and q['price'] > 0 and q['price'] < 30:
                s['price'] = q['price']
                s['change_pct'] = q.get('change_pct', 0)
                quoted.append(s)
    except Exception as e:
        print(f'  Batch {i} err: {e}')

print(f'股价<30: {len(quoted)}')

# ── 4. 获取行业(从 Baostock 已有 + akshare 因子接口) ──
print('获取行业数据(通过东方财富因子接口)...')
for i, s in enumerate(quoted):
    code = s['code']
    ind = s.get('industry', '')
    if not ind:
        try:
            fin = get_stock_factors_http(code)
            ind = fin.get('industry', '') or ''
            if ind:
                s['industry'] = ind
        except Exception:
            pass
    if (i+1) % 50 == 0:
        print(f'  行业获取进度: {i+1}/{len(quoted)}')

have_ind = sum(1 for s in quoted if s.get('industry'))
print(f'有行业数据: {have_ind}/{len(quoted)}')

# ── 5. 科技行业关键词（更严格） ──
TECH_INDUSTRY_KW = [
    # 信息技术/计算机/软件
    '计算机', '软件', '信息技术', 'IT服务', '互联网', '通信', '电信',
    '5G', '通讯', '网络', '数据', '云计算', '大数据', '信息安全', '区块链',
    # 电子/半导体
    '电子', '半导体', '芯片', '集成电路', '元件', '器件', '光电', '光学',
    '显示', '面板', 'LED', '传感器', 'PCB', '被动元件',
    # 军工/航天(科技类)
    '航天', '航空', '军工', '卫星', '导航', '雷达', '无人机', '武器',
    # 智能制造/机器人/自动化
    '机器人', '自动化', '智能制造', '数控', '3D打印', '激光',
    # 新能源/新材料(科技类)
    '新能源', '光伏', '风电', '电池', '储能', '锂电', '氢能', '核电',
    '新材料', '稀土', '磁材', '碳纤维', '石墨烯',
    # 生物医药(科技类)
    '生物', '医药', '制药', '基因', '疫苗', '医疗器械', 'CXO', '创新药',
    # 高端制造/装备
    '高端装备', '精密', '仪器', '仪表',
    # 汽车科技
    '新能源汽车', '汽车电子', '无人驾驶', '车联网', '充电桩',
    # 传媒科技
    '传媒', '数字媒体', '游戏',
]

def is_tech_stock(s):
    """综合判断：行业优先，名称兜底"""
    name = s.get('name', '')
    industry = s.get('industry', '')

    # 行业匹配
    if industry:
        for kw in TECH_INDUSTRY_KW:
            if kw in industry:
                return True

    # 名称关键词（行业缺失时的兜底，更精确）
    TECH_NAME_KW = [
        # 明确科技
        '科技', '电子', '软件', '数据', '通信', '信息',
        '微电子', '半导体', '芯片', '光电', '光学',
        '航天', '航空', '卫星', '导航', '雷达', '遥感',
        '机器人', '智能', '数控', '自动化', '精密',
        '新能源', '光伏', '风电', '储能', '电池', '锂',
        '材料', '稀土', '磁材', '纳米',
        '生物', '医药', '药', '基因', '疫苗', '医疗',
        '互联', '网络', '数字', '传媒', '软件',
        '集成', '元器件', '传感', '仪器',
        '激光', '光电', '光纤', '晶圆', '硅',
        '无人', '智造', '数控',
        '电器', '电气',  # 电力电子设备
        '环保',  # 环保科技
    ]
    for kw in TECH_NAME_KW:
        if kw in name:
            # 排除明显非科技的
            if any(x in name for x in ['食品', '饮料', '白酒', '啤酒', '养殖', '种植',
                                         '港口', '高速', '铁路', '公路', '机场',
                                         '银行', '保险', '证券', '信托',
                                         '房地产', '水泥', '钢铁', '煤炭',
                                         '百货', '超市', '零售', '服装', '纺织',
                                         '旅游', '酒店', '餐饮',
                                         ]):
                continue
            return True

    return False

tech = []
non_tech = []
for s in quoted:
    if is_tech_stock(s):
        tech.append(s)
    else:
        non_tech.append(s)

print(f'\n科技股: {len(tech)}')
print(f'非科技: {len(non_tech)}')
sh_t = [x for x in tech if x['code'].startswith('60')]
sz_t = [x for x in tech if x['code'].startswith('00')]
print(f'  沪市: {len(sh_t)}, 深市: {len(sz_t)}')

tech.sort(key=lambda x: x['code'])

# ── 输出 ──
print(f'\n{"="*80}')
print(f'科技股完整列表 ({len(tech)}只)')
print(f'{"="*80}')
print(f'{"代码":<8} {"名称":<12} {"价格":>8} {"涨跌":>8}  {"行业"}')
print(f'{"-"*60}')

for s in tech:
    ind = s.get('industry', '')
    print(f'{s["code"]:<8} {s["name"]:<12} {s["price"]:>8.2f} {s["change_pct"]:>+7.2f}% {ind}')

# 被排除的检查一下
print(f'\n非科技股样本(前30只,检查是否有遗漏):')
for s in non_tech[:30]:
    ind = s.get('industry', '')
    print(f'{s["code"]} {s["name"]:<10s} {s["price"]:.2f} [{ind}]')
