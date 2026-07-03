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
