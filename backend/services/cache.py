"""Screener 数据缓存层 — 把"每只股票调一次外网"换成"全市场一次调用"

缓存表:
  factor_snapshot     55 因子 (screener 跳过 compute_all_factors)
  daily_north_flow    北向资金 (akshare 批量, 1 次调用拉全市场)
  daily_inst_holding  机构持仓 (akshare 批量)

收益:
  - screener 首次: ~20 分钟 → ~5 分钟 (北向/机构走批量)
  - screener 二次: ~5 分钟 → ~30 秒 (factor_snapshot 命中)
"""
import logging
import time
from typing import Optional

from database import execute, execute_many, query_all, query_one

logger = logging.getLogger(__name__)

SNAPSHOT_TTL_SECONDS = 24 * 3600


# ═══════════════════════════════════════════════════════════
#  55 因子快照
# ═══════════════════════════════════════════════════════════

def get_factor_snapshot(code: str) -> Optional[dict]:
    """读某只股票的完整 55 因子快照, 过期返回 None"""
    rows = query_all(
        "SELECT factor_name, value, updated_at FROM factor_snapshot WHERE stock_code = ?",
        (code,),
    )
    if not rows:
        return None
    latest_ts = max((row[2] for row in rows if row[2]), default="")
    try:
        ts = time.mktime(time.strptime(latest_ts[:19], "%Y-%m-%d %H:%M:%S"))
        if time.time() - ts > SNAPSHOT_TTL_SECONDS:
            return None
    except (ValueError, TypeError):
        pass
    return {row[0]: row[1] for row in rows if row[1] is not None}


def save_factor_snapshot(code: str, factors: dict) -> int:
    """保存某只股票的 55 因子快照"""
    if not factors:
        return 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    statements = [
        ("INSERT OR REPLACE INTO factor_snapshot "
         "(stock_code, factor_name, value, updated_at) VALUES (?, ?, ?, ?)",
         (code, name, val, now))
        for name, val in factors.items()
    ]
    try:
        execute_many(statements)
        return len(statements)
    except Exception as e:
        logger.warning("save_factor_snapshot(%s): %s", code, str(e)[:120])
        return 0


# ═══════════════════════════════════════════════════════════
#  北向资金日级缓存
# ═══════════════════════════════════════════════════════════

def get_north_flow(code: str, trade_date: Optional[str] = None) -> Optional[dict]:
    """读某只股票的北向资金缓存

    Args:
        code: 股票代码
        trade_date: 指定日期 (默认最近可用)

    Returns:
        {net_flow, change_qty, rank} 或 None
    """
    if trade_date:
        row = query_one(
            "SELECT net_flow, change_qty, rank FROM daily_north_flow "
            "WHERE stock_code = ? AND trade_date = ?",
            (code, trade_date),
        )
    else:
        row = query_one(
            "SELECT net_flow, change_qty, rank FROM daily_north_flow "
            "WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 1",
            (code,),
        )
    if not row:
        return None
    return {
        "net_flow": row[0],       # 亿元
        "change_qty": row[1],     # 股
        "rank": row[2],
    }


def save_north_flow_batch(records: list[dict], trade_date: str) -> int:
    """批量保存某日的北向资金 (records: [{code, net_flow, change_qty, rank}, ...])"""
    if not records:
        return 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    statements = [
        ("INSERT OR REPLACE INTO daily_north_flow "
         "(stock_code, trade_date, net_flow, change_qty, rank, updated_at) "
         "VALUES (?, ?, ?, ?, ?, ?)",
         (r["code"], trade_date, r.get("net_flow"), r.get("change_qty"),
          r.get("rank"), now))
        for r in records
    ]
    try:
        execute_many(statements)
        return len(statements)
    except Exception as e:
        logger.warning("save_north_flow_batch(%s): %s", trade_date, str(e)[:120])
        return 0


# ═══════════════════════════════════════════════════════════
#  机构持仓日级缓存
# ═══════════════════════════════════════════════════════════

def get_inst_holding(code: str, trade_date: Optional[str] = None) -> Optional[dict]:
    """读某只股票的机构持仓缓存"""
    if trade_date:
        row = query_one(
            "SELECT hold_pct, change_pct FROM daily_inst_holding "
            "WHERE stock_code = ? AND trade_date = ?",
            (code, trade_date),
        )
    else:
        row = query_one(
            "SELECT hold_pct, change_pct FROM daily_inst_holding "
            "WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 1",
            (code,),
        )
    if not row:
        return None
    return {"hold_pct": row[0], "change_pct": row[1]}


def save_inst_holding_batch(records: list[dict], trade_date: str) -> int:
    """批量保存某日的机构持仓 (records: [{code, hold_pct, change_pct}, ...])"""
    if not records:
        return 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    statements = [
        ("INSERT OR REPLACE INTO daily_inst_holding "
         "(stock_code, trade_date, hold_pct, change_pct, updated_at) "
         "VALUES (?, ?, ?, ?, ?)",
         (r["code"], trade_date, r.get("hold_pct"), r.get("change_pct"), now))
        for r in records
    ]
    try:
        execute_many(statements)
        return len(statements)
    except Exception as e:
        logger.warning("save_inst_holding_batch(%s): %s", trade_date, str(e)[:120])
        return 0


# ═══════════════════════════════════════════════════════════
#  统计 / 维护
# ═══════════════════════════════════════════════════════════

def clear_factor_snapshot() -> int:
    """清空因子快照 — 强制重算"""
    cur = execute("DELETE FROM factor_snapshot")
    return cur.rowcount if hasattr(cur, "rowcount") else 0


def get_cache_stats() -> dict:
    """统计缓存覆盖率"""
    f_total = query_one("SELECT COUNT(*) AS n FROM factor_snapshot")
    f_codes = query_one("SELECT COUNT(DISTINCT stock_code) AS n FROM factor_snapshot")
    n_total = query_one("SELECT COUNT(*) AS n FROM daily_north_flow")
    n_latest = query_one("SELECT MAX(trade_date) AS d FROM daily_north_flow")
    i_total = query_one("SELECT COUNT(*) AS n FROM daily_inst_holding")
    i_latest = query_one("SELECT MAX(trade_date) AS d FROM daily_inst_holding")
    return {
        "factor_snapshot": {
            "rows": f_total["n"] if f_total else 0,
            "stocks": f_codes["n"] if f_codes else 0,
        },
        "daily_north_flow": {
            "rows": n_total["n"] if n_total else 0,
            "latest_date": n_latest["d"] if n_latest else None,
        },
        "daily_inst_holding": {
            "rows": i_total["n"] if i_total else 0,
            "latest_date": i_latest["d"] if i_latest else None,
        },
    }