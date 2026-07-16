#!/usr/bin/env python3
"""一次性补全 historical_kline 全市场 K 线（不在 git，跑完即用）

策略:
  - 多源 fallback: Baostock (主) → Akshare (兜底)
  - 找出 historical_kline 中 < 60 根的 code，全部补到 252 天
  - ThreadPoolExecutor 8 worker 加速；INSERT OR IGNORE 保留已有数据
  - 进度日志每 50 只打一次

用法: cd backend && python sync_kline_full.py
"""
import sys
import time
import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("sync_kline")

DB = BACKEND_DIR.parent / "database" / "stockai.db"
MIN_BARS = 60       # 少于 60 根视为覆盖不足
TARGET_DAYS = 252
MAX_WORKERS = 8

# INSERT OR IGNORE: 已存在的 (stock_code, trade_date) 不会重复写入
INSERT_SQL = (
    "INSERT OR IGNORE INTO historical_kline "
    "(stock_code, trade_date, open, high, low, close, volume) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def fetch_one(conn, code: str) -> tuple[str, int, str]:
    """返回 (code, 写入行数, 来源/错误信息)

    用 KLineChain (Baostock 主 → Akshare 兜底) 拉 K 线，写入 DB。
    每线程独立连接 (check_same_thread=False)。
    """
    from services.providers import build_kline_chain

    chain = build_kline_chain()
    records, source_name = chain.fetch(code, days=TARGET_DAYS)
    if not records:
        return (code, 0, "no_data (" + source_name + ")")

    rows = [rec.to_row(code) for rec in records]
    thread_conn = sqlite3.connect(str(DB), timeout=30, check_same_thread=False)
    try:
        cur = thread_conn.executemany(INSERT_SQL, rows)
        thread_conn.commit()
        written = max(cur.rowcount, 0) if cur.rowcount is not None else 0
        if written == 0:
            written = len(rows)
        return (code, written, source_name)
    except Exception as e:
        return (code, 0, "insert_err: " + str(e)[:80])
    finally:
        thread_conn.close()


def find_codes_to_fill(conn) -> list[str]:
    all_codes = [r[0] for r in conn.execute("SELECT stock_code FROM stock_info")]
    needs = []
    for code in all_codes:
        n = conn.execute(
            "SELECT COUNT(*) FROM historical_kline WHERE stock_code = ?",
            (code,),
        ).fetchone()[0]
        if n < MIN_BARS:
            needs.append(code)
    return needs


def main():
    log.info("DB = %s", DB)
    conn = sqlite3.connect(str(DB))
    log.info("finding codes with < %d bars ...", MIN_BARS)
    needs = find_codes_to_fill(conn)
    log.info("to-fill: %d / stock_info total", len(needs))

    if not needs:
        log.info("nothing to fill, exit.")
        conn.close()
        return

    start = time.time()
    done = ok = 0
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_one, conn, code): code for code in needs}
        for fut in as_completed(futures):
            code, n, info = fut.result()
            done += 1
            if n > 0:
                ok += 1
            else:
                failures.append((code, info))
            if done % 50 == 0 or done == len(needs):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta_min = (len(needs) - done) / rate / 60 if rate > 0 else 0
                log.info(
                    "  progress %d/%d (ok=%d, fail=%d) %.1f/s ETA %.1fmin",
                    done, len(needs), ok, len(failures), rate, eta_min,
                )

    elapsed = time.time() - start
    log.info("=== DONE: %d processed, %d ok, %d failed in %.0fs ===",
             done, ok, len(failures), elapsed)

    if failures:
        log.warning("first 10 failures:")
        for c, info in failures[:10]:
            log.warning("  %s -> %s", c, info)

    conn.close()


if __name__ == "__main__":
    main()
