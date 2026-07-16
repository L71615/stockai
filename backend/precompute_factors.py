#!/usr/bin/env python3
"""55 因子离线预计算 (全市场)

策略:
  - 对 stock_info 表中所有股票跑 compute_all_factors()
  - 写入 factor_snapshot 表
  - 下次 screener 直接从 snapshot 读 (秒级 vs 分钟级)
  - ThreadPoolExecutor 12 worker 并发
  - 进度日志每 100 只打一次

用法:
  cd backend && python precompute_factors.py
  cd backend && python precompute_factors.py --codes 600519,000001  # 单只/指定
  cd backend && python precompute_factors.py --refresh              # 强制刷新

前置条件:
  - historical_kline 已有 ≥120 根 K 线
  - sync_kline_full.py 已跑过 (数据从 2025-04-01 起)
"""
import sys
import time
import sqlite3
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("precompute_factors")

DB = BACKEND_DIR.parent / "database" / "stockai.db"
MAX_WORKERS = 12
MIN_BARS = 120  # 至少 120 根 K 线


def get_all_codes(conn, only_codes: list[str] | None = None) -> list[str]:
    """从 stock_info 取所有股票代码（或指定的）"""
    if only_codes:
        return only_codes
    rows = conn.execute(
        "SELECT stock_code FROM stock_info WHERE stock_code IS NOT NULL"
    ).fetchall()
    return [r[0] for r in rows]


def has_enough_kline(conn, code: str) -> bool:
    """检查 K 线数量"""
    n = conn.execute(
        "SELECT COUNT(*) FROM historical_kline WHERE stock_code = ?",
        (code,),
    ).fetchone()[0]
    return n >= MIN_BARS


def read_kline(conn, code: str, days: int = 252) -> dict:
    """从 DB 读最近 N 天 K 线"""
    rows = conn.execute(
        """SELECT trade_date, open, high, low, close, volume
           FROM historical_kline
           WHERE stock_code = ?
           ORDER BY trade_date DESC
           LIMIT ?""",
        (code, days),
    ).fetchall()
    if not rows:
        return {}
    # 按时间正序
    rows = list(reversed(rows))
    return {
        "dates":   [r[0] for r in rows],
        "opens":   [r[1] for r in rows],
        "highs":   [r[2] for r in rows],
        "lows":    [r[3] for r in rows],
        "closes":  [r[4] for r in rows],
        "volumes": [r[5] for r in rows],
    }


def preheat_fundamentals(conn, code: str) -> dict:
    """从 DB 取基本面快照 (避免外网调用)"""
    row = conn.execute(
        """SELECT name, industry, pe, pb, roe, eps, market_cap_billion, ps_ttm,
                  gross_margin, debt_ratio, dividend_yield, eps_prev
           FROM local_fundamentals
           WHERE stock_code = ?
           ORDER BY trade_date DESC
           LIMIT 1""",
        (code,),
    ).fetchone()
    if not row:
        return {}
    return {
        "name": row[0] or "",
        "industry": row[1] or "",
        "pe": row[2], "pb": row[3], "roe": row[4],
        "eps": row[5], "market_cap_billion": row[6],
        "ps_ttm": row[7], "gross_margin": row[8],
        "debt_ratio": row[9], "dividend_yield": row[10],
        "prev_eps": row[11],
    }


def compute_one(conn, code: str) -> tuple[str, int, str]:
    """算一只股票的 55 因子 + 写 snapshot

    Returns:
        (code, snapshot_rows, info/error_msg)
    """
    if not has_enough_kline(conn, code):
        return (code, 0, "kline<120")

    kline = read_kline(conn, code)
    fund = preheat_fundamentals(conn, code)

    try:
        from services.factor_service import compute_all_factors
        from services.factor_snapshot import save_snapshot

        result = compute_all_factors(
            code=code,
            closes=kline.get("closes", []),
            highs=kline.get("highs", []),
            lows=kline.get("lows", []),
            volumes=kline.get("volumes", []),
            fundamentals=fund,
            prev_eps=fund.get("prev_eps"),
            dividend=fund.get("dividend_yield"),
        )
        factors = result.get("factors", {})
        n = save_snapshot(code, factors)
        return (code, n, "ok")
    except Exception as e:
        return (code, 0, f"{type(e).__name__}: {str(e)[:80]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", help="逗号分隔的股票代码列表")
    parser.add_argument("--refresh", action="store_true", help="强制重算 (无视现有 cache)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    only_codes = [c.strip() for c in args.codes.split(",")] if args.codes else None

    log.info("DB = %s", DB)
    conn = sqlite3.connect(str(DB))

    if args.refresh:
        from services.factor_snapshot import clear_all
        n = clear_all()
        log.info("refresh: cleared %d old snapshot rows", n)

    codes = get_all_codes(conn, only_codes)
    log.info("target stocks: %d", len(codes))

    if not codes:
        log.info("nothing to do, exit.")
        conn.close()
        return

    start = time.time()
    done = ok = skip = fail = 0
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(compute_one, conn, c): c for c in codes}
        for fut in as_completed(futures):
            code, n, info = fut.result()
            done += 1
            if info == "ok":
                ok += 1
            elif info == "kline<120":
                skip += 1
            else:
                fail += 1
                failures.append((code, info))
            if done % 100 == 0 or done == len(codes):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta_min = (len(codes) - done) / rate / 60 if rate > 0 else 0
                log.info(
                    "  progress %d/%d (ok=%d skip=%d fail=%d) %.1f/s ETA %.1fmin",
                    done, len(codes), ok, skip, fail, rate, eta_min,
                )

    elapsed = time.time() - start
    log.info(
        "=== DONE: %d processed, %d ok, %d skipped, %d failed in %.0fs ===",
        done, ok, skip, fail, elapsed,
    )

    if failures:
        log.warning("first 10 failures:")
        for c, info in failures[:10]:
            log.warning("  %s -> %s", c, info)

    conn.close()


if __name__ == "__main__":
    main()