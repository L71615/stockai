"""历史因子面板 — 为每只股票在每个历史日期计算因子向量 + 未来收益标签"""

import json, math, time, logging
from database import query_all, query_one, execute
from services.factor_service import compute_all_factors, normalize_factors

logger = logging.getLogger(__name__)

# 用于预测的技术类因子（不用基本面和资金，短期预测价值低）
PREDICTION_FACTORS = [
    # 价格 (6)
    "ret_5d", "ret_20d", "ma_disposition", "price_position",
    "close_open_ratio", "high_low_ratio",
    # 成交量 (4)
    "vol_ratio", "vol_std", "price_volume_corr",
    "turnover_rate",
    # 技术指标 (3)
    "rsi_14", "macd_signal", "boll_position",
    # 动量 (4)
    "strength_20d", "momentum_composite", "acceleration",
    "hist_vol_5d",
    # 波动率 (4)
    "hist_vol_20d", "atr_14", "amplitude_20d", "bb_width",
    # 21 个因子
]


def get_kline_slice(code: str, before_date: str, days: int = 120) -> dict | None:
    """获取某只股票在某日期前的 K 线切片"""
    rows = query_all(
        """SELECT trade_date, open, high, low, close, volume
           FROM historical_kline
           WHERE stock_code = ? AND trade_date <= ?
           ORDER BY trade_date ASC""",
        (code, before_date),
    )
    if len(rows) < 60:
        return None
    # 取最后 days 条
    rows = rows[-days:]
    return {
        "dates": [r["trade_date"] for r in rows],
        "opens": [r["open"] for r in rows],
        "highs": [r["high"] for r in rows],
        "lows": [r["low"] for r in rows],
        "closes": [r["close"] for r in rows],
        "volumes": [r["volume"] for r in rows],
    }


def get_forward_return(code: str, from_date: str, n_days: int) -> float | None:
    """计算某只股票在 from_date 后 n 天的未来收益率"""
    rows = query_all(
        """SELECT close FROM historical_kline
           WHERE stock_code = ? AND trade_date > ?
           ORDER BY trade_date ASC LIMIT ?""",
        (code, from_date, n_days + 1),
    )
    if len(rows) < n_days:
        return None
    start = query_one(
        "SELECT close FROM historical_kline WHERE stock_code = ? AND trade_date = ?",
        (code, from_date),
    )
    if not start or start["close"] <= 0:
        return None
    end = rows[n_days - 1]
    return round((end["close"] - start["close"]) / start["close"], 6)


def build_panel_for_date(target_date: str, stock_codes: list[str]) -> dict:
    """为某个历史日期构建完整的因子面板

    返回: {
        date: str,
        stocks: {code: {factors: {...}, fwd_ret_1d, fwd_ret_3d, fwd_ret_5d}}
    }
    """
    t0 = time.time()
    raw_factors = []

    for code in stock_codes:
        kline = get_kline_slice(code, target_date, days=120)
        if not kline:
            continue
        f = compute_all_factors(
            code,
            closes=kline["closes"],
            highs=kline["highs"],
            lows=kline["lows"],
            volumes=kline["volumes"],
            fundamentals={},
        )
        raw_factors.append({
            "code": code,
            "factors": f["factors"],
            "hit_count": f["hit_count"],
        })

    # 截面 Z-Score 标准化
    normalized = normalize_factors(raw_factors)

    # 附加未来收益率标签
    result = {}
    for nf in normalized:
        code = nf["code"]
        result[code] = {
            "factors": {k: v for k, v in nf["factors"].items()
                       if v is not None and k in PREDICTION_FACTORS},
            "fwd_ret_1d": get_forward_return(code, target_date, 1),
            "fwd_ret_3d": get_forward_return(code, target_date, 3),
            "fwd_ret_5d": get_forward_return(code, target_date, 5),
        }

    elapsed = time.time() - t0
    logger.info(f"Panel built for {target_date}: {len(result)} stocks in {elapsed:.1f}s")
    return {"date": target_date, "stocks": result, "count": len(result)}


def get_latest_panel(stock_codes: list[str], kline_days: int = 120) -> dict:
    """获取最新日期的因子面板（用于盘前查询）

    不需要 historical_kline 有未来数据，只算因子不做标签。
    """
    from services.technical import fetch_kline

    t0 = time.time()
    raw_factors = []

    for code in stock_codes:
        try:
            kline = fetch_kline(code, days=kline_days)
            if "error" in kline or not kline.get("closes"):
                continue
            f = compute_all_factors(
                code,
                closes=kline["closes"],
                highs=kline.get("highs", []),
                lows=kline.get("lows", []),
                volumes=kline.get("volumes", []),
                fundamentals={},
            )
            raw_factors.append({
                "code": code,
                "factors": f["factors"],
                "hit_count": f["hit_count"],
            })
        except Exception:
            pass

    normalized = normalize_factors(raw_factors)
    result = {}
    for nf in normalized:
        result[nf["code"]] = {
            "factors": {k: v for k, v in nf["factors"].items()
                       if v is not None and k in PREDICTION_FACTORS},
        }

    elapsed = time.time() - t0
    logger.info(f"Latest panel: {len(result)} stocks in {elapsed:.1f}s")
    return result


def load_historical_panels(dates: list[str], stock_pool: list[str]) -> list[dict]:
    """批量构建多个历史日期的因子面板，返回列表"""
    panels = []
    for i, d in enumerate(sorted(dates)):
        panel = build_panel_for_date(d, stock_pool)
        panels.append(panel)
        if (i + 1) % 10 == 0:
            logger.info(f"Panel progress: {i+1}/{len(dates)} dates")
    return panels
