"""数据供应商路由器 — 配置驱动的多源 fallback

用法:
  from services.vendor_router import route

  kline = route("get_daily_kline", code="600519", days=120)
  quote = route("get_realtime_quote", code="600519")
  quotes = route("get_batch_quotes", codes=["000001", "600519"])
  fundamentals = route("get_fundamentals", code="600519")
  minute = route("get_minute_kline", code="600519", count=240)

设计原则:
  - 所有方法签名统一为 **kwargs，由具体 vendor 实现解析
  - 每个 vendor 函数返回 {..., "source": "vendor_name"} 或 {"error": "..."}
  - route() 按配置链依次尝试，第一个成功的返回
  - 所有 vendor 都失败时返回 {"error": "all vendors failed", ...}
  - Futu OpenD 不可用时自动跳过（避免 4 分钟超时等待）
"""

import logging
import socket
from typing import Any

from services.vendor_config import get_vendors

logger = logging.getLogger(__name__)

# Futu 快速连通性检查缓存（避免每次请求都检测）
_futu_available = None
_futu_check_ts = 0.0


def _is_futu_reachable() -> bool:
    """快速检查 Futu OpenD 是否在运行（带 60s 缓存）"""
    global _futu_available, _futu_check_ts
    import time
    now = time.time()
    if _futu_available is not None and (now - _futu_check_ts) < 60:
        return _futu_available
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)  # 1 秒超时，不阻塞
        s.connect(("127.0.0.1", 11111))
        s.close()
        _futu_available = True
    except Exception:
        _futu_available = False
    _futu_check_ts = now
    return _futu_available


def _skip_futu_vendor(vendor: str) -> bool:
    """如果 vendor 是 futu 但 OpenD 不可达，跳过"""
    if vendor != "futu":
        return False
    return not _is_futu_reachable()


# ═══════════════════════════════════════════════════════════════
#  供应商实现注册表
# ═══════════════════════════════════════════════════════════════

def _futu_daily_kline(code: str, days: int = 120, **kwargs) -> dict:
    try:
        from services.futu_ingest_service import sync_daily_kline
        result = sync_daily_kline(code, count=days)
        result["source"] = "futu"
        return result
    except Exception as e:
        return {"error": str(e), "source": "futu", "code": code}


def _sina_daily_kline(code: str, days: int = 120, **kwargs) -> dict:
    try:
        from services.sina_adapter import get_kline as sina_kline
        result = sina_kline(code, days)
        if "error" not in result:
            result["source"] = "sina"
        return result
    except Exception as e:
        return {"error": str(e), "source": "sina", "code": code}


def _akshare_daily_kline(code: str, days: int = 120, **kwargs) -> dict:
    try:
        from services.akshare_adapter import get_kline as ak_kline
        result = ak_kline(code, days)
        if "error" not in result:
            result["source"] = "akshare"
        return result
    except Exception as e:
        return {"error": str(e), "source": "akshare", "code": code}


def _baostock_daily_kline(code: str, days: int = 120, **kwargs) -> dict:
    try:
        from services.baostock_adapter import get_kline as bs_kline
        result = bs_kline(code, days=days)
        if "error" not in result:
            result["source"] = "baostock"
        return result
    except Exception as e:
        return {"error": str(e), "source": "baostock", "code": code}


def _futu_realtime_quote(code: str, **kwargs) -> dict:
    try:
        from services.futu_ingest_service import sync_quote
        result = sync_quote(code)
        if "error" not in result:
            result["source"] = "futu"
        return result
    except Exception as e:
        return {"error": str(e), "source": "futu", "code": code}


def _akshare_realtime_quote(code: str, **kwargs) -> dict:
    try:
        from services.akshare_adapter import get_quote
        result = get_quote(code)
        if result is None:
            return {"error": "no data", "source": "akshare", "code": code}
        result["source"] = "akshare"
        return result
    except Exception as e:
        return {"error": str(e), "source": "akshare", "code": code}


def _akshare_batch_quotes(codes: list[str], **kwargs) -> dict[str, dict]:
    try:
        from services.akshare_adapter import get_batch_quotes
        return get_batch_quotes(codes)
    except Exception as e:
        return {"error": str(e), "source": "akshare"}


def _akshare_fundamentals(code: str, **kwargs) -> dict:
    try:
        from services.akshare_adapter import get_stock_factors_http
        result = get_stock_factors_http(code)
        if result is None:
            return {"error": "no data", "source": "akshare", "code": code}
        if "error" not in result:
            result["source"] = "akshare"
        return result
    except Exception as e:
        return {"error": str(e), "source": "akshare", "code": code}


def _baostock_fundamentals(code: str, **kwargs) -> dict:
    try:
        from services.baostock_adapter import get_stock_factors
        result = get_stock_factors(code)
        if "error" not in result:
            result["source"] = "baostock"
        return result
    except Exception as e:
        return {"error": str(e), "source": "baostock", "code": code}


def _futu_minute_kline(code: str, count: int = 240, **kwargs) -> dict:
    try:
        from services.futu_ingest_service import sync_minute_kline
        result = sync_minute_kline(code, count=count)
        if "error" not in result:
            result["source"] = "futu"
        return result
    except Exception as e:
        return {"error": str(e), "source": "futu", "code": code}


# ═══════════════════════════════════════════════════════════════
#  方法 → 供应商实现 映射表
# ═══════════════════════════════════════════════════════════════

_METHOD_REGISTRY: dict[str, dict[str, Any]] = {
    "get_daily_kline": {
        "category": "daily_kline",
        "futu":     _futu_daily_kline,
        "sina":     _sina_daily_kline,
        "akshare":  _akshare_daily_kline,
        "baostock":  _baostock_daily_kline,
    },
    "get_realtime_quote": {
        "category": "realtime_quote",
        "futu":    _futu_realtime_quote,
        "akshare": _akshare_realtime_quote,
    },
    "get_batch_quotes": {
        "category": "batch_quotes",
        "akshare": _akshare_batch_quotes,
    },
    "get_fundamentals": {
        "category": "fundamentals",
        "akshare":  _akshare_fundamentals,
        "baostock":  _baostock_fundamentals,
    },
    "get_minute_kline": {
        "category": "minute_kline",
        "futu": _futu_minute_kline,
    },
}


def route(method: str, **kwargs) -> Any:
    """按配置的供应商优先级链调用数据方法

    Args:
        method: 方法名 ("get_daily_kline" | "get_realtime_quote" | "get_batch_quotes" | "get_fundamentals" | "get_minute_kline")
        **kwargs: 传递给具体 vendor 实现的参数（如 code, days, count, codes）

    Returns:
        第一个成功 vendor 的返回值（dict），或 {"error": "all vendors failed", "tried": [...]}

    Example:
        kline = route("get_daily_kline", code="600519", days=120)
        # → 按配置链尝试 futu → sina → akshare → baostock
        # → 返回第一个非 error 的结果
    """
    if method not in _METHOD_REGISTRY:
        return {"error": f"Unknown method: {method}", "available": list(_METHOD_REGISTRY.keys())}

    registry = _METHOD_REGISTRY[method]
    category = registry["category"]
    vendor_chain = get_vendors(category)

    errors = []
    for vendor in vendor_chain:
        if vendor not in registry:
            logger.debug("vendor_router: %s not implemented for %s, skipping", vendor, method)
            continue
        if _skip_futu_vendor(vendor):
            logger.info("vendor_router: Futu OpenD not reachable, skipping for %s", method)
            continue

        try:
            result = registry[vendor](**kwargs)
            if "error" not in result:
                return result
            errors.append(f"{vendor}: {result['error']}")
            logger.debug("vendor_router: %s failed for %s: %s", vendor, method, result["error"])
        except Exception as e:
            errors.append(f"{vendor}: {e}")
            logger.warning("vendor_router: %s exception for %s: %s", vendor, method, e)

    code = kwargs.get("code", kwargs.get("codes", "?"))
    logger.error("vendor_router: all vendors failed for %s(%s): %s", method, code, errors)
    return {
        "error": f"All vendors failed for {method}",
        "tried": errors,
        "code": code,
    }
