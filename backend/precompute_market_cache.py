#!/usr/bin/env python3
"""机构持仓日级缓存 (akshare 无批量接口, 走并发单只查询)

策略:
  - akshare 没有'全市场机构持仓'批量接口
  - 走 ThreadPoolExecutor 8 worker 并发调 ak.stock_institute_hold_detail()
  - 写入 daily_inst_holding 表 (screener 命中跳过外网)
  - 北向资金走 screener 首次自动填 daily_north_flow (akshare 也无批量接口)

用法:
  cd backend && python precompute_market_cache.py
  cd backend && python precompute_market_cache.py --codes 600519,000001  # 单只/指定
  cd backend && python precompute_market_cache.py --top 1000             # 自选股+持仓优先
"""
import sys
import time
import sqlite3
import argparse
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("precompute_inst")

DB = BACKEND_DIR.parent / "database" / "stockai.db"


def get_target_codes(top: int | None = None, only_codes: list[str] | None = None) -> list[str]:
    """获取目标股票代码 (默认 watchlist + holdings 优先)"""
    if only_codes:
        return only_codes

    con = sqlite3.connect(str(DB))
    try:
        if top:
            rows = con.execute(
                "SELECT DISTINCT stock_code FROM stock_info LIMIT ?", (top,)
            ).fetchall()
            return [r[0] for r in rows]

        # watchlist + holdings
        rows = con.execute("""
            SELECT stock_code FROM watchlist
            UNION
            SELECT stock_code FROM holdings
        """).fetchall()
        if not rows:
            rows = con.execute(
                "SELECT DISTINCT stock_code FROM stock_info LIMIT 200"
            ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def fetch_one(code: str) -> tuple[str, dict | None]:
    """拉一只股票的机构持仓"""
    try:
        from services.akshare_adapter import get_inst_holding
        data = get_inst_holding(code)
        return (code, data)
    except Exception as e:
        log.debug("get_inst_holding(%s) failed: %s", code, str(e)[:80])
        return (code, None)


def fetch_north_one(code: str) -> tuple[str, dict | None]:
    """拉一只股票的最新一日北向资金 (akshare stock_hsgt_individual_em)"""
    try:
        import akshare as ak
        df = ak.stock_hsgt_individual_em(symbol=code)
        if df is None or df.empty:
            return (code, None)
        latest = df.iloc[-1]
        # 列: ['持股日期', '当日收盘价', '当日涨跌幅', '持股数量', '持股市值',
        #       '持股数量占A股百分比', '今日增持股数', '今日增持资金', '今日持股市值变化']
        trade_date = str(latest.iloc[0])  # 持股日期
        net_yuan = float(latest.iloc[7]) if latest.iloc[7] is not None else 0  # 今日增持资金 (元)
        change_qty = float(latest.iloc[6]) if latest.iloc[6] is not None else 0
        return (code, {
            "trade_date": trade_date,
            "net_flow": net_yuan / 1e8,  # 元→亿元
            "change_qty": change_qty,
        })
    except Exception as e:
        log.debug("get_north_flow(%s) failed: %s", code, str(e)[:80])
        return (code, None)


def fetch_north_flow(codes: list[str], trade_date: str, workers: int = 8) -> int:
    """并发拉全市场北向资金, 写入 daily_north_flow 表"""
    from services.cache import save_north_flow_batch

    start = time.time()
    done = ok = 0
    records = []
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_north_one, code): code for code in codes}
        for fut in as_completed(futures):
            code, data = fut.result()
            done += 1
            if data:
                records.append({
                    "code": code,
                    "net_flow": data["net_flow"],
                    "change_qty": data["change_qty"],
                    "rank": None,
                })
                ok += 1
            else:
                failures.append(code)
            if done % 50 == 0 or done == len(codes):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta_min = (len(codes) - done) / rate / 60 if rate > 0 else 0
                log.info(
                    "  north progress %d/%d (ok=%d fail=%d) %.1f/s ETA %.1fmin",
                    done, len(codes), ok, len(failures), rate, eta_min,
                )

    # 按 trade_date 分组保存 (不同股票可能 trade_date 不同)
    # 这里简化为单日, 取最后一个非空 trade_date
    n = save_north_flow_batch(records, trade_date)
    elapsed = time.time() - start
    log.info("=== north DONE: %d ok, %d failed, saved %d in %.0fs ===", ok, len(failures), n, elapsed)
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", help="逗号分隔的股票代码")
    parser.add_argument("--top", type=int, help="取 stock_info 前 N 只")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-north", action="store_true", help="跳过北向资金预热")
    parser.add_argument("--skip-inst", action="store_true", help="跳过机构持仓预热")
    args = parser.parse_args()

    only_codes = [c.strip() for c in args.codes.split(",")] if args.codes else None
    codes = get_target_codes(args.top, only_codes)
    trade_date = datetime.now().strftime("%Y-%m-%d")

    log.info("DB = %s", DB)
    log.info("target: %d stocks (date=%s)", len(codes), trade_date)

    if not codes:
        log.info("nothing to do.")
        return

    from services.cache import save_inst_holding_batch, save_north_flow_batch

    # ── 1) 机构持仓 (akshare 单只接口) ──
    if not args.skip_inst:
        start = time.time()
        done = ok = 0
        records = []
        failures: list[str] = []

        log.info("=== 同步机构持仓 ===")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(fetch_one, code): code for code in codes}
            for fut in as_completed(futures):
                code, data = fut.result()
                done += 1
                if data:
                    records.append({
                        "code": code,
                        "hold_pct": data.get("hold_pct"),
                        "change_pct": data.get("change_pct"),
                    })
                    ok += 1
                else:
                    failures.append(code)
                if done % 50 == 0 or done == len(codes):
                    elapsed = time.time() - start
                    rate = done / elapsed if elapsed > 0 else 0
                    eta_min = (len(codes) - done) / rate / 60 if rate > 0 else 0
                    log.info(
                        "  inst progress %d/%d (ok=%d fail=%d) %.1f/s ETA %.1fmin",
                        done, len(codes), ok, len(failures), rate, eta_min,
                    )

        n = save_inst_holding_batch(records, trade_date)
        elapsed = time.time() - start
        log.info("=== inst DONE: %d ok, %d failed, saved %d in %.0fs ===", ok, len(failures), n, elapsed)

    # ── 2) 北向资金 (akshare stock_hsgt_individual_em 单只, 稳定) ──
    if not args.skip_north:
        log.info("=== 同步北向资金 (akshare stock_hsgt_individual_em) ===")
        fetch_north_flow(codes, trade_date, args.workers)


if __name__ == "__main__":
    main()