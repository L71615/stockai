"""趋势预测 API — 基于历史因子相似度的上涨概率"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import query_all, query_one
from services.historical_panel import (
    get_latest_panel, build_panel_for_date, PREDICTION_FACTORS,
)
from services.similarity_service import find_similar_periods, aggregate_prediction, cosine_similarity
from services.screener_service import get_all_stock_list

router = APIRouter(prefix="/api/prediction", tags=["prediction"])

# 内存缓存：预建的历史因子面板
_panel_cache: list[dict] | None = None


class PredictRequest(BaseModel):
    stock_code: str
    factor_keys: list[str] | None = None


@router.get("/status")
def prediction_status():
    """预测引擎状态"""
    stocks = query_one("SELECT COUNT(DISTINCT stock_code) AS n FROM historical_kline")
    dates = query_one("SELECT MIN(trade_date) AS min_d, MAX(trade_date) AS max_d FROM historical_kline")
    panel_count = len(_panel_cache) if _panel_cache else 0
    return {
        "kline_stocks": stocks["n"] if stocks else 0,
        "date_range": f"{dates['min_d']} ~ {dates['max_d']}" if dates else "无数据",
        "panel_dates_cached": panel_count,
        "ready": panel_count > 0,
    }


@router.post("/predict")
def predict_stock(body: PredictRequest):
    """预测单只股票的上涨概率

    需要先运行 build_history.py 和 build_panel 脚本。
    如果因子面板未加载，返回错误提示。
    """
    if not _panel_cache:
        # 尝试快速构建：用最近 30 个交易日的面板
        return {
            "probability_1d": None,
            "probability_3d": None,
            "probability_5d": None,
            "error": "因子面板未加载。请先运行: python scripts/build_panel.py",
            "status": "not_ready",
        }

    # 获取当前因子
    pool = get_all_stock_list()
    codes = [s["code"] for s in pool[:300]]  # 最多 300 只以保持性能
    if body.stock_code not in codes:
        codes.insert(0, body.stock_code)

    latest = get_latest_panel(codes)
    target = latest.get(body.stock_code)
    if not target:
        raise HTTPException(404, f"无法计算 {body.stock_code} 的因子")

    # 在历史面板中找相似时刻
    matches = find_similar_periods(target["factors"], _panel_cache, top_k=30)
    result = aggregate_prediction(matches)
    result["stock_code"] = body.stock_code
    result["factor_keys_used"] = PREDICTION_FACTORS
    result["status"] = "ready"

    return result


@router.post("/batch-predict")
def batch_predict(codes: list[str]):
    """批量预测多只股票"""
    if not _panel_cache:
        return {"error": "因子面板未加载", "results": []}

    limit = min(len(codes), 50) if codes else 0
    pool = get_all_stock_list()
    all_codes = [s["code"] for s in pool[:300]]
    for c in codes[:limit]:
        if c not in all_codes:
            all_codes.append(c)

    latest = get_latest_panel(all_codes)
    results = []

    for code in codes[:limit]:
        target = latest.get(code)
        if not target:
            continue
        matches = find_similar_periods(target["factors"], _panel_cache, top_k=20)
        pred = aggregate_prediction(matches)
        pred["stock_code"] = code
        results.append(pred)

    results.sort(key=lambda x: x.get("probability_3d") or 0, reverse=True)
    return {"results": results}


@router.post("/build-panel")
def trigger_build_panel(dates: list[str] | None = None):
    """手动触发因子面板构建（管理员用）

    不带 dates 参数时，自动从 historical_kline 中取最近 30 个交易日。
    """
    global _panel_cache

    if not dates:
        rows = query_all(
            "SELECT DISTINCT trade_date FROM historical_kline ORDER BY trade_date DESC LIMIT 30"
        )
        dates = [r["trade_date"] for r in rows]
        dates.reverse()  # 升序

    if not dates:
        raise HTTPException(400, "没有可用的历史K线数据，请先运行 build_history.py")

    pool = get_all_stock_list()
    codes = [s["code"] for s in pool]

    from services.historical_panel import load_historical_panels
    _panel_cache = load_historical_panels(dates, codes)

    return {"ok": True, "dates_processed": len(dates), "panels_cached": len(_panel_cache)}


@router.get("/panel-info")
def panel_info():
    """因子面板缓存信息"""
    if not _panel_cache:
        return {"cached": False, "message": "请先调用 POST /api/prediction/build-panel 构建面板"}
    return {
        "cached": True,
        "dates": [p["date"] for p in _panel_cache],
        "total_dates": len(_panel_cache),
        "avg_stocks_per_date": sum(p["count"] for p in _panel_cache) // max(len(_panel_cache), 1),
    }
