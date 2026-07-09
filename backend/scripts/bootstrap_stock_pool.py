"""股票池初始化脚本 — 拉沪深300+中证500成分股，过滤后写入 watchlist

过滤条件:
  1. 只保留沪深主板 (600/601/603/605/000/001/002/003)
  2. 排除 ST / *ST
  3. 股价 < 100 元（一手不超过1万）
  4. A 股（排除 ETF/可转债等）

用法:
  python backend/scripts/bootstrap_stock_pool.py
  python backend/scripts/bootstrap_stock_pool.py --init-kline  # 同时下载日线
"""

import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import query_all, query_one, execute

# 板块过滤规则（来自 screener_service）
import re
_BOARD_MAIN = {"main_sh", "main_sz"}
_BOARD_RULES = {
    "main_sh": r"^60[0-9]{4}$",
    "main_sz": r"^00[0-39][0-9]{3}$",
    "gem":     r"^30[0-9]{4}$",
    "star":    r"^68[0-9]{4}$",
    "bse":     r"^8[0-9]{5}$",
    "nq":      r"^4[0-9]{5}$",
}

def detect_board(code: str) -> str:
    for board_id, pat in _BOARD_RULES.items():
        if re.match(pat, code):
            return board_id
    return "other"


def main(init_kline: bool = False):
    from services.futu_client import FutuClient
    futu = FutuClient()

    # 1. 检查 Futu 连通性
    hc = futu.healthcheck()
    if not hc["ok"]:
        print(f"❌ Futu OpenD 不可用: {hc.get('message')}")
        print("  请先启动 Futu OpenD，默认地址 127.0.0.1:11111")
        return
    print("🟢 Futu OpenD 已连接")

    # 2. 拉取沪深300 + 中证500成分股
    all_codes: set[str] = set()
    for plate_code, plate_name in [("SH.000300", "沪深300"), ("SH.000905", "中证500")]:
        try:
            ret, data = futu._make_ctx().get_plate_stock(plate_code)
            if ret == 0 and not data.empty:
                codes = []
                for _, row in data.iterrows():
                    code = row["code"]
                    if "." in code:
                        code = code.split(".", 1)[1]
                    codes.append(code)
                all_codes.update(codes)
                print(f"  {plate_name}: {len(codes)} 只")
            else:
                print(f"  {plate_name}: 获取失败")
        except Exception as e:
            print(f"  {plate_name}: 异常 {e}")
        futu._make_ctx().close()

    print(f"\n合并去重: {len(all_codes)} 只")

    # 3. 板块过滤（只保留主板）
    main_codes = [c for c in all_codes if detect_board(c) in _BOARD_MAIN]
    excluded = len(all_codes) - len(main_codes)
    print(f"板块过滤(仅主板): {len(main_codes)} 只 (排除 {excluded} 只)")

    # 4. 分批获取快照（价格+名称+ST判断），每批300只
    codes_list = sorted(main_codes)
    valid = []
    batch_size = 300

    for i in range(0, len(codes_list), batch_size):
        batch = codes_list[i:i + batch_size]
        try:
            snapshots = futu.get_snapshot(batch)
            for s in snapshots:
                if "error" in s:
                    continue
                name = str(s.get("name", ""))
                price = s.get("price")
                if price is None:
                    continue
                # 过滤 ST
                if "ST" in name.upper():
                    continue
                # 过滤高价
                if price >= 100:
                    continue
                valid.append({"code": s["code"], "name": name, "price": price})
        except Exception as e:
            print(f"  批次 {i//batch_size + 1}: 异常 {e}")

        # 请求间隔
        if i + batch_size < len(codes_list):
            time.sleep(0.5)

    print(f"价格<100 + 非ST: {len(valid)} 只")

    # 5. 写入 watchlist（幂等，UNIQUE(user_id, stock_code) 自动去重）
    inserted = 0
    for s in valid:
        existing = query_one(
            "SELECT id FROM watchlist WHERE user_id = 1 AND stock_code = ?",
            (s["code"],),
        )
        if not existing:
            execute(
                "INSERT INTO watchlist (user_id, stock_code, stock_name, market, asset_type) VALUES (1, ?, ?, ?, 'stock')",
                (s["code"], s["name"], "SH" if s["code"].startswith("6") else "SZ"),
            )
            inserted += 1

    print(f"\n✅ 写入 watchlist: {inserted} 只新股票")
    total = query_all("SELECT COUNT(*) as n FROM watchlist WHERE user_id = 1")
    print(f"   自选股总数: {total[0]['n']} 只")

    # 6. 可选：初始化日线数据
    if init_kline:
        print("\n📊 开始下载日线数据...")
        from services.futu_ingest_service import sync_daily_kline
        success = 0
        for i, s in enumerate(valid):
            try:
                result = sync_daily_kline(s["code"])
                if result.get("status") == "ok":
                    success += 1
                if (i + 1) % 50 == 0:
                    print(f"  进度 {i + 1}/{len(valid)} 成功 {success}")
            except Exception:
                pass
        print(f"   日线下载完成: {success}/{len(valid)}")

    print("\n🎉 股票池初始化完成")


if __name__ == "__main__":
    init_kline = "--init-kline" in sys.argv
    main(init_kline=init_kline)
