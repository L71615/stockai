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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", help="逗号分隔的股票代码")
    parser.add_argument("--top", type=int, help="取 stock_info 前 N 只")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    only_codes = [c.strip() for c in args.codes.split(",")] if args.codes else None
    codes = get_target_codes(args.top, only_codes)
    trade_date = datetime.now().strftime("%Y-%m-%d")

    log.info("DB = %s", DB)
    log.info("target: %d stocks (date=%s)", len(codes), trade_date)

    if not codes:
        log.info("nothing to do.")
        return

    from services.cache import save_inst_holding_batch

    start = time.time()
    done = ok = 0
    records = []
    failures: list[str] = []

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
                    "  progress %d/%d (ok=%d fail=%d) %.1f/s ETA %.1fmin",
                    done, len(codes), ok, len(failures), rate, eta_min,
                )

    n = save_inst_holding_batch(records, trade_date)
    elapsed = time.time() - start
    log.info(
        "=== DONE: %d processed, %d ok, %d failed, saved %d in %.0fs ===",
        done, ok, len(failures), n, elapsed,
    )

    if failures:
        log.warning("first 10 failures: %s", failures[:10])


if __name__ == "__main__":
    main()