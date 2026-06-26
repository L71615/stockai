"""v3: 全面科技股筛选 — 行业关键词 + 知名科技公司前缀 + 分类输出"""
import sys
sys.path.insert(0, '.')
from services.screener_service import get_all_stock_list
from services.akshare_adapter import get_batch_quotes

# ── 1. 科技行业关键词（覆盖申万/中信行业分类） ──
TECH_KW = {
    # TMT — 计算机/软件/通信
    '计算机', '软件', 'IT', '互联网', '通信', '5G', '电信', '网络',
    '数据', '云计算', '大数据', '信息安全', '区块链', 'AI', '人工智能',
    '智能交通', '智慧城市', '物联网', 'ERP', 'SAAS',

    # 电子/半导体
    '电子', '半导体', '芯片', '集成电路', 'IC', 'PCB', '元器件',
    '光电', '光学', '光电子', '显示', '面板', 'LED', 'OLED', '传感器',
    '被动元件', '晶圆', '封测',

    # 高端制造/军工/航天
    '航天', '航空', '军工', '卫星', '导航', '雷达', '无人机', '战斗机',
    '机器人', '自动化', '智能制造', '数控', '3D打印', '激光',
    '高端装备', '精密', '仪器仪表',

    # 新能源/新材料
    '新能源', '光伏', '风电', '电池', '储能', '锂电', '氢能', '燃料电池',
    '充电桩', '逆变器', '新材料', '稀土', '磁材', '碳纤维', '石墨烯',
    '核电', '核能',

    # 生物医药科技
    '生物', '医药', '制药', '基因', '疫苗', '医疗器械', 'CXO',
    '创新药', '生物制品', '体外诊断',

    # 传媒/数字科技
    '传媒', '数字媒体', '游戏', '动漫', '影视',

    # 汽车科技
    '新能源汽车', '智能汽车', '无人驾驶', '车联网',

    # 环保科技
    '环保', '节能', '环境',
}

# ── 2. 知名科技公司名称关键词（用于捕获无行业数据的科技股） ──
KNOWN_TECH_NAMES = [
    # 电子/元器件
    '京东方', 'TCL', '立讯', '歌尔', '韦尔', '汇顶', '兆易',
    '卓胜微', '圣邦', '北方华创', '中微', '长电', '通富', '华天',
    '紫光', '深南电路', '鹏鼎', '景旺', '生益', '沪电',
    '蓝思', '领益', '东山', '水晶', '欧菲',

    # 计算机/软件/IT
    '浪潮', '中科曙光', '紫光', '同方', '长城', '神州',
    '用友', '金蝶', '广联达', '恒生', '石基',
    '东华', '太极', '中软', '宝信',

    # 通信
    '中兴', '烽火', '亨通', '中天',

    # 军工/航天
    '中航', '航发', '航天', '中国卫星', '北斗',
    '中兵', '中国船舶', '中国动力', '中船',
    '光启',

    # 新能源
    '宁德', '比亚迪', '阳光电源', '隆基', '通威',
    '晶澳', '晶科', '天合', '亿纬', '国轩',
    '赣锋', '天齐', '华友', '当升', '容百',
    '恩捷', '天赐', '新宙邦', '星源',

    # 生物医药
    '恒瑞', '迈瑞', '药明', '百济', '君实',
    '爱尔', '通策', '智飞', '康泰', '沃森',
    '长春高新', '片仔癀', '云南白药', '同仁堂',
    '凯莱英', '康龙化成', '泰格',

    # 智能制造/机器人
    '汇川', '埃斯顿', '新松', '拓斯达', '格力', '美的',

    # 其他科技
    '海康', '大华', '科大讯飞', '商汤',
    '大疆', '柔宇', '旷视',
]

# ── 3. 非科技排除词 ——
NON_TECH_EXCLUDE = [
    '银行', '保险', '证券', '期货', '信托', '金融',
    '房地产', '地产', '建筑', '装修', '建材', '水泥', '玻璃',
    '钢铁', '煤炭', '石油', '石化', '化工', '化纤', '化肥', '农药',
    '食品', '饮料', '白酒', '啤酒', '红酒', '乳业', '奶',
    '农业', '养殖', '畜牧', '种业', '渔业', '种植', '糖', '盐',
    '纺织', '服装', '鞋', '造纸', '印刷', '包装', '家居',
    '零售', '百货', '超市', '贸易', '物流', '快递',
    '港口', '高速', '公路', '铁路', '机场', '航空运输',
    '电力', '发电', '水务', '燃气', '供热', '供水',
    '酒店', '旅游', '餐饮', '景点',
    '园林', '绿化',
    '矿业', '黄金', '有色金属', '铝业', '铜业', '铅锌',
    '白酒', '啤酒', '黄酒',
]

def is_tech_stock(s):
    name = s.get('name', '')
    industry = s.get('industry', '') or ''

    # 先排除明显非科技的
    for nkw in NON_TECH_EXCLUDE:
        if nkw in name:
            return False

    # 行业匹配
    if industry:
        for kw in TECH_KW:
            if kw in industry:
                return True

    # 已知科技公司匹配
    for kn in KNOWN_TECH_NAMES:
        if kn in name:
            return True

    # 通用科技关键词（名称中）
    for kw in TECH_KW:
        if len(kw) >= 2 and kw in name:
            return True

    return False


def is_regular(code):
    if code.startswith('688'): return False
    if code.startswith('8'): return False
    if code.startswith('4'): return False
    if code.startswith('300') or code.startswith('301'): return False
    return True


# ── Main ──
all_stocks = get_all_stock_list(force_refresh=False)
print(f'全池: {len(all_stocks)}')
regular = [s for s in all_stocks if is_regular(s['code'])]
print(f'主板: {len(regular)}')

codes = [s['code'] for s in regular]
quoted = []
for i in range(0, len(codes), 100):
    batch = codes[i:i+100]
    try:
        quotes_map = get_batch_quotes(batch)
        for s in regular[i:i+100]:
            q = quotes_map.get(s['code'])
            if q and q.get('price') and q['price'] > 0 and q['price'] < 30:
                s['price'] = q['price']
                s['change_pct'] = q.get('change_pct', 0)
                s['high'] = q.get('high', 0)
                s['low'] = q.get('low', 0)
                s['volume'] = q.get('volume', 0)
                quoted.append(s)
    except Exception as e:
        print(f'  Batch {i} err: {e}')

print(f'股价<30: {len(quoted)}')

tech, non_tech = [], []
for s in quoted:
    if is_tech_stock(s):
        tech.append(s)
    else:
        non_tech.append(s)

print(f'科技股: {len(tech)}')
sh = sum(1 for x in tech if x['code'].startswith('60'))
sz = sum(1 for x in tech if x['code'].startswith('00'))
print(f'  沪市: {sh}, 深市: {sz}')

# 分类
categories = {
    '半导体/电子': ['电子', '半导体', '芯片', '集成电路', '元器件', '光电', '光学', '显示', '面板', 'LED', '传感器', 'PCB', '晶圆', '封测', '被动元件', '京东方', 'TCL', '韦尔', '汇顶', '兆易', '卓胜微', '圣邦', '北方华创', '中微', '长电', '通富', '华天', '紫光', '深南', '鹏鼎', '景旺', '生益', '沪电', '蓝思', '领益', '东山', '水晶', '欧菲', '立讯', '歌尔'],
    '计算机/软件': ['计算机', '软件', 'IT', '互联网', '数据', '云计算', '大数据', '信息安全', '区块链', 'AI', '人工智能', '智慧', '物联网', 'ERP', 'SAAS', '浪潮', '中科曙光', '紫光', '用友', '广联达', '恒生', '石基', '太极', '宝信', '海康', '大华', '科大讯飞'],
    '通信/5G': ['通信', '5G', '电信', '网络', '中兴', '烽火', '亨通', '中天'],
    '军工/航天': ['航天', '航空', '军工', '卫星', '导航', '雷达', '无人机', '中航', '航发', '中国卫星', '北斗', '中兵', '光启'],
    '新能源/新材料': ['新能源', '光伏', '风电', '电池', '储能', '锂', '氢能', '核电', '新材料', '稀土', '磁材', '碳纤维', '石墨烯', '宁德', '阳光电源', '隆基', '通威', '亿纬', '赣锋', '天齐', '华友', '当升', '容百', '恩捷', '天赐', '新宙邦', '星源', '国轩', '节能'],
    '生物医药': ['生物', '医药', '制药', '基因', '疫苗', '医疗', 'CXO', '创新药', '恒瑞', '迈瑞', '药明', '百济', '爱尔', '通策', '智飞', '康泰', '沃森', '长春高新', '片仔癀', '凯莱英', '康龙化成', '泰格', '同仁堂'],
    '智能制造/自动化': ['机器人', '自动化', '智能制造', '数控', '3D打印', '激光', '高端装备', '精密', '仪器', '汇川', '埃斯顿', '拓斯达', '格力', '美的'],
    '数字传媒': ['传媒', '数字媒体', '游戏', '动漫', '分众'],
    '汽车科技': ['新能源车', '智能汽车', '无人驾驶', '车联网', '充电桩', '比亚迪'],
    '环保科技': ['环保', '环境'],
}

def classify(name, industry=''):
    text = name + industry
    for cat, kws in categories.items():
        for kw in kws:
            if kw in text:
                return cat
    return '其他科技'

# 输出
print()
print('=' * 90)
print(f'🔍 科技股筛选结果: {len(tech)} 只')
print(f'   条件: 主板(非科创/北交/创业) + 股价<30元 + 科技相关')
print(f'   数据范围: 沪深300+中证500 成分股 (800只)')
print('=' * 90)

for cat in categories:
    stocks_in_cat = [s for s in tech if classify(s['name'], s.get('industry', '')) == cat]
    if stocks_in_cat:
        print(f'\n## {cat} ({len(stocks_in_cat)}只)')
        print(f'{"代码":<8} {"名称":<12} {"价格":>8} {"涨跌%":>8}')
        print('-' * 40)
        for s in sorted(stocks_in_cat, key=lambda x: x['code']):
            print(f'{s["code"]:<8} {s["name"]:<12} {s["price"]:>8.2f} {s["change_pct"]:>+7.2f}')
