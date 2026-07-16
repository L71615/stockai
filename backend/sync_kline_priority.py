#!/usr/bin/env python3
"""一次性补全沪深 300 + 中证 500 的 historical_kline（不在 git，跑完即用）

策略:
  - 数据源: HS300 (000300) + ZZ500 (000905) = ~800 只主票
  - 只补 < 252 根的 (剩下 ~410 只大约 6 分钟跑完)
  - 直接复用 sync_kline_full.fetch_one (Baostock 主 + Akshare 兜底)
  - ThreadPoolExecutor 12 workers 并发

用法: cd backend && python sync_kline_priority.py
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
log = logging.getLogger("sync_priority")

from sync_kline_full import fetch_one, DB, TARGET_DAYS, MAX_WORKERS

MIN_BARS = TARGET_DAYS  # 252 — 不到 1 年的视为需要补


def get_index_constituents() -> list[str]:
    """拉 HS300 + ZZ500 成分股，去重后返回代码列表（去掉交易所后缀）"""
    import akshare as ak

    raw_codes: set[str] = set()
    for symbol in ("000300", "000905"):
        df = ak.index_stock_cons_csindex(symbol=symbol)
        for code in df["成分券代码"].tolist():
            # 格式: '000001.SZ' 或 'sh600519'
            s = str(code).strip()
            if "." in s:
                raw_codes.add(s.split(".")[0])
            else:
                # 处理 'sh600519' / 'sz000001' 风格
                for prefix in ("sh", "sz", "SH", "SZ"):
                    if s.startswith(prefix):
                        raw_codes.add(s[len(prefix):])
                        break
                else:
                    raw_codes.add(s)
    return sorted(raw_codes)


def find_codes_to_fill(conn, target_codes: set[str]) -> list[str]:
    needs = []
    in_db = [
        r[0]
        for r in conn.execute(
            "SELECT stock_code FROM stock_info WHERE stock_code IN (" +
            ",".join("?" * len(target_codes)) + ")",
            tuple(target_codes),
        )
    ]
    for code in in_db:
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

    log.info("fetching HS300 + ZZ500 constituents from Akshare ...")
    codes = get_index_constituents()
    log.info("HS300+ZZ500 unique codes: %d", len(codes))

    target_set = set(codes)
    log.info("finding codes with < %d bars in DB ...", MIN_BARS)
    needs = find_codes_to_fill(conn, target_set)
    log.info("to-fill: %d / %d (HS300+ZZ500)", len(needs), len(codes))

    if not needs:
        log.info("nothing to fill, exit.")
        conn.close()
        return

    start = time.time()
    done = ok = 0
    failures: list[tuple[str, str]] = []

    workers = min(MAX_WORKERS * 2, 16)  # 重点补可用更高并发
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_one, conn, code): code for code in needs}
        for fut in as_completed(futures):
            code, n, info = fut.result()
            done += 1
            if n > 0:
                ok += 1
            else:
                failures.append((code, info))
            if done % 25 == 0 or done == len(needs):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta_min = (len(needs) - done) / rate / 60 if rate > 0 else 0
                log.info(
                    "  progress %d/%d (ok=%d, fail=%d) %.1f/s ETA %.1fmin",
                    done, len(needs), ok, len(failures), rate, eta_min,
                )

    elapsed = time.time() - start
    log.info(
        "=== DONE: %d processed, %d ok, %d failed in %.0fs ===",
        done, ok, len(failures), elapsed,
    )

    if failures:
        log.warning("first 10 failures:")
        for c, info in failures[:10]:
            log.warning("  %s -> %s", c, info)

    conn.close()


if __name__ == "__main__":
    main()
