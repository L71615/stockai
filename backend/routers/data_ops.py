"""数据运维路由 — v3.9 全市场浏览 + K线补齐

5 个 endpoint:
  GET  /api/data-ops/stocks              - 全市场股票列表（带板块/价格/涨跌幅/完整性）
  GET  /api/data-ops/freshness           - 各板块 K 线新鲜度仪表盘
  GET  /api/data-ops/sector-performance  - 行业涨幅榜 TOP N
  GET  /api/stocks/{code}/sparkline      - 单只股票最近 N 天收盘价序列
  POST /api/data-ops/sync-stocks         - 异步补齐 K 线（单只 / 板块 / 全市场）
"""
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from database import query_all, query_one
from services.screener_service import detect_board
from services.akshare_adapter import get_kline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-ops", tags=["DataOps"])

# 板块定义（与 screener_service._BOARD_RULES 一致 + 补充 ETF/指数）
_SECTOR_LABELS = {
    "main_sh": "沪深主板",
    "main_sz": "深证主板",
    "gem": "创业板",
    "star": "科创板",
    "bse": "北交所",
    "nq": "三板",
    "etf": "ETF/基金",
    "index": "指数",
    "other": "其他",
}
_SECTOR_ORDER = ["main_sh", "main_sz", "gem", "star", "bse", "nq", "etf", "index", "other"]


def _classify_sector(code: str) -> str:
    """分类股票到板块（含 ETF/指数）"""
    if code.startswith(("60", "68")):
        if code.startswith("688"):
            return "star"
        if code.startswith("60"):
            return "main_sh"
    if code.startswith(("00", "30")):
        if code.startswith("300") or code.startswith("301"):
            return "gem"
        if code.startswith("00"):
            return "main_sz"
    if code.startswith(("83", "87", "43")):
        return "bse"
    if code.startswith(("51", "15")):
        return "etf"
    # 000/300/399 开头可能是指数
    if code in ("000001", "000300", "000905", "399001", "399006", "399905"):
        return "index"
    return "other"


def _integrity_status(days_ago: int | None, kline_count: int) -> str:
    """根据滞后天数 + K线数量判定数据完整性"""
    if days_ago is None:
        return "missing"
    if kline_count < 60:
        return "missing"
    if days_ago <= 3:
        return "fresh"
    if days_ago <= 7:
        return "stale"
    return "stale"  # >7 天一律视为陈旧


@router.get("/stocks")
def list_stocks(
    sector: str = Query("", description="板块过滤（main_sh / main_sz / gem / star / bse / etf）"),
    search: str = Query("", description="按代码/名称模糊搜索"),
    integrity: str = Query("", description="fresh/stale/missing 过滤"),
    limit: int = Query(5000, description="返回数量上限"),
):
    """全市场股票列表 + 最新价 + 涨跌幅 + 完整性"""
    # 一次性查所有股票（带最新价 + 涨跌幅 + K线数）
    sql = """
        WITH latest AS (
            SELECT stock_code, MAX(trade_date) AS d, COUNT(*) AS n
            FROM historical_kline GROUP BY stock_code
        ),
        prev AS (
            SELECT k.stock_code, k.close AS prev_close
            FROM historical_kline k
            JOIN latest l ON k.stock_code = l.stock_code AND k.trade_date < l.d
            WHERE k.trade_date = (
                SELECT MAX(k2.trade_date) FROM historical_kline k2
                WHERE k2.stock_code = k.stock_code AND k2.trade_date < l.d
            )
        ),
        today AS (
            SELECT k.stock_code, k.trade_date, k.close, k.volume
            FROM historical_kline k
            JOIN latest l ON k.stock_code = l.stock_code AND k.trade_date = l.d
        )
        SELECT
            si.stock_code AS code,
            si.name,
            si.industry,
            t.trade_date AS latest_date,
            t.close AS latest_close,
            t.volume,
            p.prev_close,
            ROUND((t.close - p.prev_close) / p.prev_close * 100, 2) AS change_pct,
            l.n AS kline_count
        FROM stock_info si
        LEFT JOIN latest l ON si.stock_code = l.stock_code
        LEFT JOIN today t ON si.stock_code = t.stock_code
        LEFT JOIN prev p ON si.stock_code = p.stock_code
    """
    rows = query_all(sql)
    today = datetime.now().date()

    out = []
    for r in rows:
        code = r["code"]
        sector_key = _classify_sector(code)
        sector_label = _SECTOR_LABELS.get(sector_key, sector_key)

        # 滞后天数
        days_ago = None
        if r["latest_date"]:
            try:
                d = datetime.strptime(r["latest_date"][:10], "%Y-%m-%d").date()
                days_ago = (today - d).days
            except Exception:
                pass

        integ = _integrity_status(days_ago, r["kline_count"] or 0)

        # 板块过滤
        if sector and sector_key != sector:
            continue
        # 完整性过滤
        if integrity and integ != integrity:
            continue
        # 搜索过滤
        if search:
            s = search.lower()
            if s not in code.lower() and s not in (r["name"] or "").lower():
                continue

        out.append({
            "code": code,
            "name": r["name"] or "",
            "industry": r["industry"] or "",
            "sector": sector_key,
            "sector_label": sector_label,
            "latest_date": r["latest_date"],
            "latest_close": r["latest_close"],
            "prev_close": r["prev_close"],
            "change_pct": r["change_pct"],
            "volume": r["volume"],
            "kline_count": r["kline_count"] or 0,
            "days_ago": days_ago,
            "integrity": integ,
        })

    # 全局 limit（filter 之后再切，避免分页+过滤耦合）
    if limit and len(out) > limit:
        out = out[:limit]

    # 按板块分组（返回 sectors 列表 + stocks by sector）
    by_sector: dict[str, list] = {}
    for s in out:
        by_sector.setdefault(s["sector"], []).append(s)

    sectors = []
    for s_key in _SECTOR_ORDER:
        stocks = by_sector.get(s_key, [])
        if not stocks:
            continue
        fresh_count = sum(1 for x in stocks if x["integrity"] == "fresh")
        stale_count = sum(1 for x in stocks if x["integrity"] == "stale")
        missing_count = sum(1 for x in stocks if x["integrity"] == "missing")
        sectors.append({
            "sector": s_key,
            "label": _SECTOR_LABELS[s_key],
            "total": len(stocks),
            "fresh_count": fresh_count,
            "stale_count": stale_count,
            "missing_count": missing_count,
            "fresh_pct": round(fresh_count * 100 / len(stocks), 1) if stocks else 0,
            "stocks": stocks,
        })

    return {
        "total": len(out),
        "sectors": sectors,
        "sector_labels": _SECTOR_LABELS,
        "as_of": today.isoformat(),
    }


@router.get("/freshness")
def freshness_dashboard():
    """各板块 K 线新鲜度仪表盘"""
    today = datetime.now().date()
    sql = """
        SELECT stock_code, MAX(trade_date) AS d FROM historical_kline GROUP BY stock_code
    """
    rows = query_all(sql)
    by_sector: dict[str, dict] = {}
    for r in rows:
        s = _classify_sector(r["stock_code"])
        if s not in by_sector:
            by_sector[s] = {"total": 0, "dates": []}
        by_sector[s]["total"] += 1
        by_sector[s]["dates"].append(r["d"])

    sectors = []
    for s_key in _SECTOR_ORDER:
        info = by_sector.get(s_key)
        if not info:
            continue
        dates = info["dates"]
        latest = max(dates) if dates else None
        days_ago = None
        if latest:
            try:
                d = datetime.strptime(latest[:10], "%Y-%m-%d").date()
                days_ago = (today - d).days
            except Exception:
                pass

        # 滞后分布
        buckets = {"≤1天": 0, "2-3天": 0, "4-7天": 0, "8-30天": 0, ">30天": 0}
        for dt in dates:
            try:
                d = datetime.strptime(dt[:10], "%Y-%m-%d").date()
                lag = (today - d).days
                if lag <= 1: key = "≤1天"
                elif lag <= 3: key = "2-3天"
                elif lag <= 7: key = "4-7天"
                elif lag <= 30: key = "8-30天"
                else: key = ">30天"
                buckets[key] += 1
            except Exception:
                pass

        sectors.append({
            "sector": s_key,
            "label": _SECTOR_LABELS[s_key],
            "stock_count": info["total"],
            "latest_date": latest,
            "days_ago": days_ago,
            "status": "fresh" if (days_ago is not None and days_ago <= 3) else (
                "stale" if (days_ago is not None and days_ago <= 7) else "missing"
            ),
            "lag_distribution": buckets,
        })

    # 总体统计
    total_stocks = sum(s["stock_count"] for s in sectors)
    fresh_stocks = sum(s["stock_count"] for s in sectors if s["status"] == "fresh")
    overall_pct = round(fresh_stocks * 100 / total_stocks, 1) if total_stocks else 0

    return {
        "as_of": today.isoformat(),
        "total_stocks": total_stocks,
        "fresh_stocks": fresh_stocks,
        "fresh_pct": overall_pct,
        "sectors": sectors,
    }


@router.get("/sector-performance")
def sector_performance(
    days: int = Query(1, description="统计窗口（1=今日，5=5日，20=月）"),
    top_n: int = Query(10, description="返回 TOP N 行业"),
):
    """行业涨幅榜 TOP N（按行业聚合）"""
    sql = """
        WITH latest AS (
            SELECT stock_code, MAX(trade_date) AS d FROM historical_kline GROUP BY stock_code
        ),
        prev AS (
            SELECT k.stock_code, k.close AS prev_close
            FROM historical_kline k
            JOIN latest l ON k.stock_code = l.stock_code AND k.trade_date < l.d
            WHERE k.trade_date = (
                SELECT MAX(k2.trade_date) FROM historical_kline k2
                WHERE k2.stock_code = k.stock_code AND k2.trade_date < l.d
            )
        ),
        today AS (
            SELECT k.stock_code, k.close AS today_close
            FROM historical_kline k
            JOIN latest l ON k.stock_code = l.stock_code AND k.trade_date = l.d
        )
        SELECT
            si.industry,
            COUNT(*) AS n,
            ROUND(AVG((t.today_close - p.prev_close) / p.prev_close * 100), 2) AS avg_change_pct
        FROM stock_info si
        JOIN today t ON si.stock_code = t.stock_code
        JOIN prev p ON si.stock_code = p.stock_code
        WHERE si.industry IS NOT NULL AND si.industry != ''
        GROUP BY si.industry
        ORDER BY avg_change_pct DESC
        LIMIT ?
    """
    rows = query_all(sql, (top_n * 2,))  # 多取一些防止过滤后不足

    return {
        "as_of": datetime.now().date().isoformat(),
        "days": days,
        "industries": [
            {
                "industry": r["industry"],
                "stock_count": r["n"],
                "avg_change_pct": r["avg_change_pct"],
            }
            for r in rows[:top_n]
        ],
    }


# ═══════════════════════════════════════════════════════════
#  同步补齐任务管理（线程安全）
# ═══════════════════════════════════════════════════════════

_sync_tasks: dict[str, dict] = {}
_sync_lock = threading.Lock()


@router.post("/sync-stocks")
def sync_stocks(
    background: BackgroundTasks,
    scope: str = Query("missing", description="fresh/stale/missing/sector/all"),
    sector: str = Query("", description="板块代码（scope=sector 时必填）"),
    target_date: str = Query("", description="补齐指定日期（默认 = 滞后最近日期）"),
):
    """异步补齐 K 线

    scope:
      - missing: 只补 missing 状态的股票
      - stale:   补 stale + missing
      - sector:  补指定 sector 的所有股票
      - all:     补所有股票
    """
    today = datetime.now().date()

    # 选目标
    if scope == "sector":
        if not sector:
            raise HTTPException(400, "scope=sector 时必须指定 sector")
        target_codes = _codes_by_sector(sector)
    elif scope == "all":
        rows = query_all("SELECT stock_code FROM stock_info")
        target_codes = [r["stock_code"] for r in rows]
    elif scope == "missing":
        target_codes = _codes_by_integrity("missing")
    else:  # stale
        target_codes = _codes_by_integrity("stale") + _codes_by_integrity("missing")

    if not target_codes:
        return {"message": "无目标需要补齐", "task_id": None}

    task_id = f"sync-{uuid.uuid4().hex[:8]}"
    with _sync_lock:
        _sync_tasks[task_id] = {
            "status": "running",
            "total": len(target_codes),
            "completed": 0,
            "failed": 0,
            "started_at": datetime.now().isoformat(),
            "scope": scope,
            "sector": sector,
        }

    def _worker():
        for code in target_codes:
            try:
                # 拉最近 10 天 K 线（覆盖缺失 + 增量）
                kline = get_kline(code, days=10)
                if kline and "closes" in kline and len(kline["closes"]) > 0:
                    from database import execute, execute_many
                    dates = kline.get("dates", [])
                    opens = kline.get("opens", [])
                    highs = kline.get("highs", [])
                    lows = kline.get("lows", [])
                    closes = kline.get("closes", [])
                    volumes = kline.get("volumes", [])
                    statements = [
                        ("INSERT OR REPLACE INTO historical_kline "
                         "(stock_code, trade_date, open, high, low, close, volume) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (code, dates[i], opens[i], highs[i], lows[i], closes[i], volumes[i]))
                        for i in range(len(dates)) if i < len(opens)
                    ]
                    if statements:
                        execute_many(statements)
                    with _sync_lock:
                        _sync_tasks[task_id]["completed"] += 1
                else:
                    with _sync_lock:
                        _sync_tasks[task_id]["failed"] += 1
            except Exception as e:
                logger.warning("sync %s failed: %s", code, str(e)[:100])
                with _sync_lock:
                    _sync_tasks[task_id]["failed"] += 1
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "done"
            _sync_tasks[task_id]["finished_at"] = datetime.now().isoformat()

    background.add_task(_worker)
    return {
        "task_id": task_id,
        "scope": scope,
        "sector": sector,
        "target_count": len(target_codes),
        "message": "补齐任务已启动",
    }


@router.get("/sync-status/{task_id}")
def sync_status(task_id: str):
    """查询同步任务进度"""
    with _sync_lock:
        task = _sync_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在或已过期")
    total = task["total"]
    pct = round((task["completed"] + task["failed"]) * 100 / total, 1) if total else 0
    return {
        "task_id": task_id,
        "status": task["status"],
        "total": total,
        "completed": task["completed"],
        "failed": task["failed"],
        "percent": pct,
        "started_at": task["started_at"],
        "finished_at": task.get("finished_at"),
    }


@router.get("/sparkline/{code}")
def sparkline(code: str, days: int = Query(60, ge=5, le=250)):
    """单只股票最近 N 天收盘价序列（用于前端 sparkline 渲染）

    返回: { dates: [str], closes: [float], min: float, max: float, change_pct: float }
    """
    rows = query_all(
        "SELECT trade_date, close FROM historical_kline "
        "WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?",
        (code, days),
    )
    if not rows:
        return {"code": code, "dates": [], "closes": [], "min": 0, "max": 0, "change_pct": 0}

    dates = [r["trade_date"] for r in reversed(rows)]
    closes = [float(r["close"]) for r in reversed(rows)]
    mn, mx = min(closes), max(closes)
    change_pct = round((closes[-1] - closes[0]) / closes[0] * 100, 2) if closes[0] else 0
    return {
        "code": code,
        "days": len(closes),
        "dates": dates,
        "closes": closes,
        "min": mn,
        "max": mx,
        "change_pct": change_pct,
    }


def _codes_by_sector(sector: str) -> list[str]:
    rows = query_all("SELECT stock_code FROM stock_info")
    return [r["stock_code"] for r in rows if _classify_sector(r["stock_code"]) == sector]


def _codes_by_integrity(target: str) -> list[str]:
    """返回 integrity = target 的股票代码"""
    today = datetime.now().date()
    rows = query_all("""
        SELECT stock_code, MAX(trade_date) AS d, COUNT(*) AS n
        FROM historical_kline GROUP BY stock_code
    """)
    out = []
    for r in rows:
        if not r["d"]:
            if target == "missing":
                out.append(r["stock_code"])
            continue
        try:
            d = datetime.strptime(r["d"][:10], "%Y-%m-%d").date()
            days_ago = (today - d).days
        except Exception:
            continue
        integrity = _integrity_status(days_ago, r["n"])
        if integrity == target:
            out.append(r["stock_code"])
    return out