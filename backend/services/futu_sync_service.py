from datetime import datetime

from database import query_all, execute
from services.utils import detect_asset_type
from services.futu_ingest_service import sync_quote, sync_minute_kline, sync_daily_kline
from services.notify_service import send_notification
from services.futu_client import FutuClient


def _normalize_scope(scope: str) -> str:
    return scope if scope in {"watchlist", "holdings", "watchlist+holdings"} else "watchlist+holdings"



def _load_sync_targets(scope: str) -> list[dict]:
    scope = _normalize_scope(scope)
    merged: dict[str, dict] = {}

    if scope in {"watchlist", "watchlist+holdings"}:
        for row in query_all("SELECT stock_code FROM watchlist WHERE stock_code IS NOT NULL AND stock_code != ''"):
            code = (row.get("stock_code") or "").strip()
            if not code or detect_asset_type(code) != "stock":
                continue
            merged.setdefault(code, {"code": code, "from_watchlist": False, "from_holdings": False})
            merged[code]["from_watchlist"] = True

    if scope in {"holdings", "watchlist+holdings"}:
        for row in query_all("SELECT stock_code FROM holdings WHERE stock_code IS NOT NULL AND stock_code != ''"):
            code = (row.get("stock_code") or "").strip()
            if not code or detect_asset_type(code) != "stock":
                continue
            merged.setdefault(code, {"code": code, "from_watchlist": False, "from_holdings": False})
            merged[code]["from_holdings"] = True

    return [merged[k] for k in sorted(merged.keys())]



def _summarize_run(target_count: int, success_count: int, failed_count: int) -> str:
    if target_count == 0:
        return "skipped"
    if failed_count == 0:
        return "success"
    if success_count == 0:
        return "failed"
    return "partial_success"



def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")



def _record_run(run_type: str, scope: str, target_count: int) -> int:
    result = execute(
        """INSERT INTO futu_sync_runs (run_type, scope, target_count, success_count, failed_count, status, started_at)
           VALUES (?, ?, ?, 0, 0, 'skipped', ?)""",
        (run_type, scope, target_count, _now_str()),
    )
    return result["lastrowid"]



def _record_item_result(run_id: int, target: dict, sync_type: str, status: str, error_message: str = "", source: str = "futu") -> None:
    started_at = _now_str()
    execute(
        """INSERT INTO futu_sync_run_items
           (run_id, stock_code, sync_type, status, error_message, source, started_at, finished_at, duration_ms, from_watchlist, from_holdings)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (
            run_id,
            target["code"],
            sync_type,
            status,
            error_message,
            source,
            started_at,
            started_at,
            1 if target.get("from_watchlist") else 0,
            1 if target.get("from_holdings") else 0,
        ),
    )



def _finalize_run(run_id: int, success_count: int, failed_count: int, status: str, error_summary: str = "", alert_sent: bool = False) -> None:
    execute(
        """UPDATE futu_sync_runs
           SET success_count = ?, failed_count = ?, status = ?, error_summary = ?, alert_sent = ?, finished_at = ?, duration_ms = 0
           WHERE id = ?""",
        (success_count, failed_count, status, error_summary, 1 if alert_sent else 0, _now_str(), run_id),
    )



def _build_alert_message(run_id: int, status: str, target_count: int, failed_count: int) -> tuple[str, str]:
    title = f"Futu 同步告警 — {status}"
    markdown = (
        f"# Futu Sync Alert\n\n"
        f"- run_id: {run_id}\n"
        f"- status: {status}\n"
        f"- target_count: {target_count}\n"
        f"- failed_count: {failed_count}\n"
    )
    return title, markdown



def _maybe_alert(run_id: int, status: str, target_count: int, failed_count: int) -> bool:
    should_alert = False
    if status == "failed":
        should_alert = True
    elif status == "partial_success" and target_count > 0 and failed_count / target_count >= 0.5:
        should_alert = True

    if not should_alert:
        return False

    title, markdown = _build_alert_message(run_id, status, target_count, failed_count)
    result = send_notification(markdown, title=title)
    return bool(result.get("ok")) if isinstance(result, dict) else bool(result)



def run_intraday_sync(scope: str = "watchlist+holdings") -> dict:
    targets = _load_sync_targets(scope)
    run_id = _record_run("intraday", scope, len(targets))
    success_count = 0
    failed_count = 0
    errors = []

    client = FutuClient()
    for target in targets:
        for sync_type, fn in (("quote", sync_quote), ("minute", sync_minute_kline)):
            result = fn(target["code"], client=client)
            if "error" in result:
                failed_count += 1
                errors.append(f"{target['code']}:{sync_type}:{result['error']}")
                _record_item_result(run_id, target, sync_type, "failed", result["error"])
            else:
                success_count += 1
                _record_item_result(run_id, target, sync_type, "success")

    status = _summarize_run(len(targets) * 2, success_count, failed_count)
    alert_sent = _maybe_alert(run_id, status, len(targets) * 2, failed_count)
    _finalize_run(run_id, success_count, failed_count, status, "; ".join(errors[:5]), alert_sent=alert_sent)
    return {
        "run_id": run_id,
        "status": status,
        "target_count": len(targets),
        "success_count": success_count,
        "failed_count": failed_count,
    }



def run_nightly_sync(scope: str = "watchlist+holdings", count: int = 200) -> dict:
    targets = _load_sync_targets(scope)
    run_id = _record_run("nightly", scope, len(targets))
    success_count = 0
    failed_count = 0
    errors = []

    client = FutuClient()
    for target in targets:
        result = sync_daily_kline(target["code"], count=count, client=client)
        if "error" in result:
            failed_count += 1
            errors.append(f"{target['code']}:daily:{result['error']}")
            _record_item_result(run_id, target, "daily", "failed", result["error"])
        else:
            success_count += 1
            _record_item_result(run_id, target, "daily", "success")

    status = _summarize_run(len(targets), success_count, failed_count)
    alert_sent = _maybe_alert(run_id, status, len(targets), failed_count)
    _finalize_run(run_id, success_count, failed_count, status, "; ".join(errors[:5]), alert_sent=alert_sent)
    return {
        "run_id": run_id,
        "status": status,
        "target_count": len(targets),
        "success_count": success_count,
        "failed_count": failed_count,
    }


# ═══════════════════════════════════════════════════════════════
#  基本面 + 板块同步
# ═══════════════════════════════════════════════════════════════

def run_nightly_fundamentals() -> dict:
    """盘后同步基本面到本地缓存表 local_fundamentals"""
    from datetime import date
    today = date.today().isoformat()

    targets = _load_sync_targets("watchlist+holdings")
    codes = [t["code"] for t in targets]
    if not codes:
        return {"status": "skipped", "message": "无同步目标"}

    futu = FutuClient()
    if not futu.healthcheck()["ok"]:
        return {"status": "skipped", "message": "Futu OpenD 不可用"}

    saved = 0
    errors = []
    batch_size = 300

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        try:
            snapshots = futu.get_snapshot(batch)
            for s in snapshots:
                if "error" in s:
                    continue
                execute(
                    """INSERT OR REPLACE INTO local_fundamentals
                       (stock_code, trade_date, pe_ttm, pb, market_cap, turnover_rate, eps, roe, dividend_yield, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'futu')""",
                    (s["code"], today,
                     s.get("pe_ttm"), s.get("pb"), s.get("market_cap"),
                     s.get("turnover_rate"), s.get("eps"), s.get("roe"),
                     s.get("dividend_yield")),
                )
                saved += 1
        except Exception as e:
            errors.append(str(e))

    # 从本地K线计算板块涨跌
    try:
        _calc_plate_daily(today)
    except Exception as e:
        errors.append(str(e))

    # 1. 用 Tushare MCP 更新全市场日线（1次调用全A股，零K线配额）
    daily_bar_added = 0
    try:
        from services.tushare_adapter import sync_daily_kline as tushare_daily
        result = tushare_daily(today.replace("-", ""))
        daily_bar_added = result.get("stocks", 0)
    except Exception as e:
        # Tushare 不可用时回退到 Futu snapshot
        try:
            daily_bar_added = _update_daily_bars(futu, today)
        except Exception as e2:
            errors.append(f"日线更新: {e}, fallback: {e2}")

    # 2. 用 Tushare 更新全市场基本面（1次调用，无需K线配额）
    try:
        from services.tushare_adapter import sync_daily_basic as tushare_basic
        tushare_basic(today.replace("-", ""))
    except Exception:
        pass  # daily_basic 有频率限制，静默跳过

    return {
        "status": "ok" if not errors else "partial",
        "target_count": len(codes),
        "saved": saved,
        "daily_bar_added": daily_bar_added,
        "errors": errors[:5],
    }


def _incremental_kline_sync(futu: FutuClient, max_per_day: int = 100) -> int:
    """每天为缺失日线的股票下载历史K线（受Futu配额限制）"""
    import time
    missing = query_all(
        """SELECT DISTINCT w.stock_code FROM watchlist w
           WHERE w.user_id = 1 AND w.asset_type = 'stock'
           AND w.stock_code NOT IN (SELECT DISTINCT stock_code FROM historical_kline)
           LIMIT ?""",
        (max_per_day,),
    )
    if not missing:
        return 0

    added = 0
    for r in missing:
        try:
            result = sync_daily_kline(r["stock_code"], count=500, client=futu)
            if "error" not in result:
                added += 1
        except Exception:
            pass
        time.sleep(0.5)  # 避免频率限制

    return added


def _update_daily_bars(futu: FutuClient, trade_date: str) -> int:
    """用 get_market_snapshot 更新已有股票的当日日线 bar（不消耗K线配额）

    get_market_snapshot 一次可拉 300 只，644 只 = 3 次调用。
    仅在盘后（15:30+）调用时数据才是收盘价。
    """
    targets = _load_sync_targets("watchlist+holdings")
    all_codes = [t["code"] for t in targets if t["code"]]
    if not all_codes:
        return 0

    batch_size = 300
    added = 0

    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i + batch_size]
        try:
            snapshots = futu.get_snapshot(batch)
            for s in snapshots:
                if "error" in s:
                    continue
                price = s.get("price")
                if price is None or price <= 0:
                    continue
                execute(
                    """INSERT OR REPLACE INTO historical_kline
                       (stock_code, trade_date, open, high, low, close, volume)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        s["code"], trade_date,
                        s.get("open_price"), s.get("high_price"),
                        s.get("low_price"), price,
                        int(s.get("volume") or 0),
                    ),
                )
                added += 1
        except Exception:
            pass

    return added


def _calc_plate_daily(trade_date: str):
    """从 historical_kline + 行业分类计算板块日均涨跌，写入 local_plate_daily"""
    try:
        from services.baostock_adapter import _get_industry_map
        ind_map = _get_industry_map()
    except Exception:
        return

    if not ind_map:
        return

    # 获取当日和前一日数据
    today_rows = query_all(
        """SELECT stock_code, close FROM historical_kline WHERE trade_date = ?""",
        (trade_date,),
    )
    prev_rows = query_all(
        """SELECT stock_code, close FROM historical_kline
           WHERE trade_date = (SELECT MAX(trade_date) FROM historical_kline WHERE trade_date < ?)""",
        (trade_date,),
    )
    prev_map = {r["stock_code"]: r["close"] for r in prev_rows}

    ind_changes: dict[str, list[float]] = {}
    for r in today_rows:
        code = r["stock_code"]
        close = r["close"]
        prev = prev_map.get(code)
        if close and prev and prev > 0:
            change = (float(close) - float(prev)) / float(prev) * 100
            industry = ind_map.get(code, {}).get("industry", "其他")
            ind_changes.setdefault(industry, []).append(change)

    for ind, changes in ind_changes.items():
        if changes:
            execute(
                """INSERT OR REPLACE INTO local_plate_daily
                   (plate_code, trade_date, avg_change, up_count, down_count, total)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ind, trade_date, round(sum(changes) / len(changes), 2),
                 sum(1 for c in changes if c > 0), sum(1 for c in changes if c < 0), len(changes)),
            )
