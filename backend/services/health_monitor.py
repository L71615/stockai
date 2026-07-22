"""
Data Source Health Monitor - akshare 限频 / Futu 断连检测 (v3.10+)

按 plan-ceo-review 2026-07-22:
  解决"我以为数据新,实际是 5 天前"的盲区

检测项:
  1. akshare 限频 (HTTP 429 / Too Many Requests)
  2. Futu OpenD 断连
  3. 数据库最新日期滞后
  4. 数据源健康度总体评级
"""
import logging
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# 阈值
STALE_DAYS_WARN = 3     # 数据滞后 >3 天警告
STALE_DAYS_CRITICAL = 7  # 数据滞后 >7 天严重
AKSHARE_TEST_URL = "https://web.ifzq.gtimg.cn/q=sh600519"
AKSHARE_TIMEOUT = 5  # 探测超时秒


def _check_akshare_health() -> dict:
    """探测 akshare (腾讯 API) 是否可用

    Returns:
        {status, latency_ms, error}
    """
    t0 = time.time()
    try:
        r = requests.get(AKSHARE_TEST_URL, timeout=AKSHARE_TIMEOUT)
        latency_ms = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            return {"status": "ok", "latency_ms": latency_ms, "error": None}
        elif r.status_code == 429:
            return {"status": "rate_limited", "latency_ms": latency_ms, "error": "429 Too Many Requests"}
        else:
            return {"status": "degraded", "latency_ms": latency_ms, "error": f"HTTP {r.status_code}"}
    except requests.exceptions.Timeout:
        return {"status": "timeout", "latency_ms": AKSHARE_TIMEOUT * 1000, "error": "Request timeout"}
    except Exception as e:
        return {"status": "down", "latency_ms": None, "error": str(e)[:200]}


def _check_futu_health() -> dict:
    """探测 Futu OpenD 是否可用 (本地 127.0.0.1:11111)

    Returns:
        {status, connected, error}
    """
    try:
        from services.futu_client import FutuClient
        # 探测: 尝试创建一个客户端 (不实际连)
        # Futu SDK 在创建 client 时不连, 只在 subscribe 时连
        # 我们直接尝试 ping 端口
        sock = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("127.0.0.1", 11111))
        sock.close()
        if result == 0:
            return {"status": "ok", "connected": True, "error": None}
        return {"status": "down", "connected": False, "error": f"Futu port 11111 not reachable (err={result})"}
    except Exception as e:
        return {"status": "unknown", "connected": False, "error": str(e)[:200]}


def _check_db_freshness() -> dict:
    """查数据库最新 K 线日期 (查 historical_kline 表)

    Returns:
        {latest_date, days_ago, status}
    """
    from database import query_one
    try:
        row = query_one("SELECT MAX(trade_date) AS latest FROM historical_kline")
        if not row or not row.get("latest"):
            return {"latest_date": None, "days_ago": None, "status": "no_data"}
        latest = row["latest"][:10]  # 'YYYY-MM-DD'
        latest_d = datetime.strptime(latest, "%Y-%m-%d").date()
        days_ago = (datetime.now().date() - latest_d).days
        if days_ago <= STALE_DAYS_WARN:
            status = "fresh"
        elif days_ago <= STALE_DAYS_CRITICAL:
            status = "stale"
        else:
            status = "critical"
        return {"latest_date": latest, "days_ago": days_ago, "status": status}
    except Exception as e:
        return {"latest_date": None, "days_ago": None, "status": "unknown", "error": str(e)[:200]}


def check_all() -> dict:
    """检查所有数据源健康度 (主入口)

    Returns:
        {
            "overall_status": "ok" | "stale" | "rate_limited" | "down",
            "checks": {akshare, futu, db_freshness},
            "issues": [str, ...],
        }
    """
    checks = {
        "akshare": _check_akshare_health(),
        "futu": _check_futu_health(),
        "db_freshness": _check_db_freshness(),
    }
    issues = []

    # 评估 akshare
    if checks["akshare"]["status"] == "rate_limited":
        issues.append("akshare 限频中 (429) - 数据同步可能失败")
    elif checks["akshare"]["status"] in ("timeout", "down"):
        issues.append(f"akshare 不可用 ({checks['akshare'].get('error', '?')})")

    # 评估 Futu
    if checks["futu"]["status"] == "down":
        issues.append("Futu OpenD 未运行 (本地 11111 端口) - 不影响本地 akshare 流程")

    # 评估 DB 新鲜度
    db_status = checks["db_freshness"]["status"]
    db_latest = checks["db_freshness"].get("latest_date")
    db_days = checks["db_freshness"].get("days_ago")
    if db_status == "critical":
        issues.append(f"K 线数据严重滞后 ({db_latest}, {db_days} 天前)")
    elif db_status == "stale":
        issues.append(f"K 线数据滞后 ({db_latest}, {db_days} 天前)")
    elif db_status == "no_data":
        issues.append("数据库没有任何 K 线数据")

    # 总体评级
    if any("严重" in i or "限频" in i or "不可用" in i for i in issues):
        overall = "down"
    elif issues:
        overall = "stale"
    else:
        overall = "ok"

    return {
        "overall_status": overall,
        "checks": checks,
        "issues": issues,
        "checked_at": datetime.now().isoformat(),
    }
