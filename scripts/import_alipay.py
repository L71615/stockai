# -*- coding: utf-8 -*-
"""支付宝交易明细导入 StockAI"""

import csv, json, re, sys, time, urllib.request, urllib.error
from collections import defaultdict
from datetime import datetime, timedelta
from io import StringIO

import os
SERVER = os.environ.get("STOCKAI_SERVER", "http://localhost:3000")
EMAIL = os.environ.get("STOCKAI_EMAIL", "admin@stockai.com")
PASSWORD = os.environ.get("STOCKAI_PASSWORD", "")

FUND_MAP = {
    "摩根标普500指数(QDII)C": "019305",
    "摩根标普500": "019305",
    "大成纳斯达克100ETF联接(QDII)A": "000834",
    "广发全球精选股票(QDII)C": "021277",
    "天弘纳斯达克100指数(QDII)C": "018044",
    "华安纳斯达克100ETF联接(QDII)A": "040046",
    "华安纳斯达克100ETF联接(QDII)C": "014978",
    "广发纳斯达克100ETF联接(QDII)C": "006479",
    "易方达机器人ETF联接C": "020973",
    "南方中证A500ETF联接A": "022434",
    "信澳业绩驱动混合C": "016371",
}

SKIP_KEYWORDS = [
    "景顺长城中证500",
    "天弘国证绿色电力",
    "广发电力公用",
    "收益发放", "转入", "转出",
]

def api(method, path, body=None, token=None):
    url = SERVER + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:200]
        raise RuntimeError("%s %s: %s %s" % (method, path, e.code, msg))

def login():
    r = api("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    return r.get("token")

def fetch_nav(fund_code, pages=5):
    nav = {}
    for page in range(1, pages + 1):
        url = ("https://api.fund.eastmoney.com/f10/lsjz?"
               "fundCode=%s&pageIndex=%d&pageSize=100") % (fund_code, page)
        req = urllib.request.Request(url, headers={
            "Referer": "https://fundf10.eastmoney.com/",
            "User-Agent": "Mozilla/5.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
                for item in data.get("Data", {}).get("LSJZList", []):
                    nav[item["FSRQ"]] = float(item["DWJZ"])
        except Exception as e:
            print("  nav page %d error: %s" % (page, e))
            break
        time.sleep(0.3)
    return nav

def match_fund(name):
    for key, code in FUND_MAP.items():
        if key in name:
            return code
    return None

def should_skip(name):
    for kw in SKIP_KEYWORDS:
        if kw in name:
            return True
    return False

def effective_nav(trade_time, nav_map):
    dt = datetime.strptime(trade_time, "%Y-%m-%d %H:%M:%S")
    nav_date = dt.strftime("%Y-%m-%d")
    if dt.hour >= 15:
        nav_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    for _ in range(5):
        if nav_date in nav_map and nav_map[nav_date] > 0:
            return nav_date, nav_map[nav_date]
        nav_date = (datetime.strptime(nav_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return None, None

def main():
    if len(sys.argv) < 2:
        print("Usage: python import_alipay.py <CSV file>")
        sys.exit(1)

    # Parse CSV
    with open(sys.argv[1], 'r', encoding='gbk') as f:
        lines = f.readlines()

    hdr = None
    for i, line in enumerate(lines):
        if '交易时间' in line:  # 交易时间
            hdr = i
            break

    reader = csv.DictReader(StringIO(''.join(lines[hdr:])))

    funds = defaultdict(list)
    skipped = defaultdict(list)

    for row in reader:
        if '投资理财' not in row.get('交易分类', ''):  # 投资理财
            continue
        desc = row.get('商品说明', '').strip()  # 商品说明
        if not desc.startswith('蚂蚁财富'):  # 蚂蚁财富
            continue

        # Extract fund name
        m = re.search(r'蚂蚁财富-(.+?)-买入', desc)  # 蚂蚁财富-XXX-买入
        if not m:
            continue
        name = m.group(1)

        if should_skip(name):
            skipped[name].append(row)
            continue

        try:
            amount = float(row.get('金额', '0'))  # 金额
        except:
            continue
        if amount <= 0:
            continue

        funds[name].append({
            "date": row['交易时间'].strip(),  # 交易时间
            "amount": amount,
        })

    print("Parsed %d funds, %d skipped" % (len(funds), len(skipped)))
    for name, txs in skipped.items():
        total = sum(float(t.get('金额', 0)) for t in txs)
        print("  SKIP %s: %d txs, %.2f" % (name, len(txs), total))

    # Login
    print("\nLogin...")
    token = login()
    print("OK")

    # Process each fund
    for name, txs in sorted(funds.items()):
        code = match_fund(name)
        if not code:
            print("\nUNMATCHED: %s - skipping" % name)
            continue

        total = sum(t["amount"] for t in txs)
        print("\n--- %s -> %s (%d txs, %.2f)" % (name[:40], code, len(txs), total))

        # Fetch NAVs
        nav_map = fetch_nav(code)
        if not nav_map:
            print("  no NAV data, skip")
            continue
        print("  NAV: %d days, %s ~ %s" % (len(nav_map),
              min(nav_map.keys()), max(nav_map.keys())))

        # Create holding
        try:
            api("POST", "/api/stocks/holdings", {
                "stock_code": code,
                "stock_name": name[:20],
                "market": "SH",
                "asset_type": "fund",
                "shares": 0,
                "cost_price": 0,
            }, token)
            print("  holding created")
        except RuntimeError:
            print("  holding exists (or error)")

        # Find holding ID
        holdings = api("GET", "/api/stocks/holdings", token=token)
        hid = None
        for h in holdings:
            if h.get("stock_code") == code:
                hid = h["id"]
                break
        if not hid:
            print("  cannot find holding id!")
            continue

        # Prepare lots
        lots = []
        missing = 0
        for tx in txs:
            nd, nv = effective_nav(tx["date"], nav_map)
            if nv is None or nv <= 0:
                missing += 1
                continue
            lots.append({"traded_at": nd, "amount": tx["amount"], "nav": nv})

        if not lots:
            print("  all %d txs missing NAV" % missing)
            continue

        # Import
        try:
            result = api("POST", "/api/stocks/holdings/%d/import-lots" % hid, {
                "lots": lots, "note": "支付宝定投导入"
            }, token)
            print("  imported %d lots: total %.2f, shares %.4f, cost %.4f" % (
                len(lots), result["total_amount"], result["total_shares"], result["new_cost_price"]))
            if missing:
                print("  %d txs missing NAV (likely T+1 pending)" % missing)
        except RuntimeError as e:
            print("  import error: %s" % e)

    print("\nDone!")

if __name__ == "__main__":
    main()
