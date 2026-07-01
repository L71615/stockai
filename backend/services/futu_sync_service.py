from database import query_all
from services.utils import detect_asset_type


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
