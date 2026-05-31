"""量化分析 API 路由：风控指标 / 相关性 / 回测 / 蒙特卡洛"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.quant_service import (
    calc_correlation_matrix,
    backtest_dca,
    compare_strategies,
    monte_carlo_sim,
    get_portfolio_risk,
    get_benchmark_comparison,
)
from fastapi.responses import PlainTextResponse
import csv, io

router = APIRouter(prefix="/api/quant", tags=["Quant"])


# ==================== 请求体 ====================

class BacktestRequest(BaseModel):
    code: str
    amount: float = 1000.0
    freq: str = "monthly"       # "weekly" | "monthly"
    start_date: str = "2025-01-01"
    end_date: str = ""           # 默认今天


class CompareRequest(BaseModel):
    code: str
    amount: float = 1000.0
    start_date: str = "2025-01-01"
    end_date: str = ""


class MonteCarloRequest(BaseModel):
    code: str
    days: int = 252
    sims: int = 1000


# ==================== 端点 ====================

@router.get("/portfolio-risk")
def portfolio_risk():
    """获取整个投资组合的风控指标摘要"""
    result = get_portfolio_risk()
    return result


@router.get("/correlation")
def correlation():
    """获取持仓间价格相关性矩阵"""
    from database import query_all
    from services.technical import fetch_kline
    from services.utils import get_market

    holdings = query_all("SELECT * FROM holdings WHERE user_id = 1 ORDER BY id DESC")
    if not holdings:
        return {"stocks": [], "matrix": [], "error": "无持仓数据"}

    prices_map: dict[str, list[float]] = {}
    for h in holdings:
        code = h["stock_code"]
        kline = fetch_kline(code, get_market(code), days=252)
        if "error" not in kline and kline.get("closes"):
            prices_map[code] = kline["closes"]

    return calc_correlation_matrix(prices_map)


@router.get("/benchmarks")
def benchmarks():
    """获取组合 vs 多个基准指数的对比"""
    return get_benchmark_comparison()


@router.get("/export/{export_type}")
def export_csv(export_type: str):
    """导出量化数据为 CSV

    export_type: "risk" | "correlation" | "backtest"
    其中 backtest 需要 query params: code, amount, freq, start_date, end_date
    """
    if export_type == "risk":
        data = get_portfolio_risk()
        if data.get("error"):
            raise HTTPException(400, data["error"])
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["指标", "值"])
        w.writerow(["持仓数量", data["holdings_count"]])
        w.writerow(["夏普比率", data.get("sharpe", "")])
        w.writerow(["最大回撤", data.get("max_drawdown", "")])
        w.writerow(["年化波动率", data.get("volatility", "")])
        w.writerow(["Beta vs 沪深300", data.get("beta", "")])
        for hr in data.get("holdings_risk", []):
            w.writerow([f"{hr.get('code','')} {hr.get('name','')} Sharpe", hr.get("sharpe", "")])
            w.writerow([f"{hr.get('code','')} {hr.get('name','')} MaxDD", hr.get("max_dd", "")])
            w.writerow([f"{hr.get('code','')} {hr.get('name','')} Vol", hr.get("vol", "")])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=risk-metrics.csv"})

    elif export_type == "correlation":
        data = get_portfolio_risk()
        corr = data.get("correlation", {})
        buf = io.StringIO()
        w = csv.writer(buf)
        stocks = corr.get("stocks", [])
        w.writerow([""] + stocks)
        for i, s in enumerate(stocks):
            row = [s] + corr["matrix"][i] if i < len(corr["matrix"]) else []
            w.writerow(row)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=correlation.csv"})

    else:
        raise HTTPException(400, f"未知导出类型: {export_type}")


@router.post("/backtest")
def backtest(req: BacktestRequest):
    """DCA 定期定额历史回测"""
    result = backtest_dca(req.code, req.amount, req.freq, req.start_date, req.end_date)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/compare")
def compare(req: CompareRequest):
    """对比 4 种策略的历史表现"""
    result = compare_strategies(req.code, req.amount, req.start_date, req.end_date)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/monte-carlo")
def monte_carlo(req: MonteCarloRequest):
    """蒙特卡洛仓位模拟"""
    from services.technical import fetch_kline
    from services.utils import get_market

    kline = fetch_kline(req.code, get_market(req.code), days=252)
    if "error" in kline:
        raise HTTPException(400, f"无法获取 {req.code} 的历史数据")
    if not kline.get("closes"):
        raise HTTPException(400, f"{req.code} 无价格数据")

    result = monte_carlo_sim(kline["closes"], days=req.days, sims=req.sims)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result
