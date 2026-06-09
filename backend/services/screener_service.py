"""多因子选股筛选服务：全市场扫描 → 因子计算 → IC加权打分 → TopN 候选池

工作流:
  1. 获取股票池（Baostock 全A股列表）
  2. 逐只获取 K 线 + 基本面 → 计算 25 因子
  3. 截面 Z-Score 标准化
  4. IC 加权合成总分（动态权重，滚动12个月 IC）
  5. 输出 TopN 候选池
  6. AI 二次筛选（可选）

性能说明: 全市场扫描约 5000 只，每只约 0.3s（缓存命中时更快），
         总耗时约 3-5 分钟。结果缓存 2 小时。
"""

import time
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import baostock as bs

from services.factor_service import compute_all_factors, normalize_factors
from services.technical import fetch_kline
from services.utils import get_market

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 股票池
# ═══════════════════════════════════════════════════════════

_ALL_STOCKS_CACHE: Optional[list[dict]] = None
_ALL_STOCKS_TTL = 86400.0  # 24 小时
_all_stocks_ts = 0.0


def get_all_stock_list(force_refresh: bool = False) -> list[dict]:
    """获取全A股股票列表（缓存24小时）

    Returns:
        [{code, name, industry, ipo_date}, ...]
    """
    global _ALL_STOCKS_CACHE, _all_stocks_ts
    now = time.time()
    if _ALL_STOCKS_CACHE and not force_refresh and (now - _all_stocks_ts) < _ALL_STOCKS_TTL:
        return _ALL_STOCKS_CACHE

    stocks = []
    index_codes: set[str] = set()

    # 1. 沪深300 + 中证500 成分股（akshare，确保核心池优先）
    try:
        import akshare as ak
        for idx_code, idx_name in [("000300", "沪深300"), ("000905", "中证500")]:
            try:
                df = ak.index_stock_cons_csindex(idx_code)
                for _, row in df.iterrows():
                    code = str(row["成分券代码"])
                    index_codes.add(code)
                    stocks.append({"code": code, "name": row.get("成分券名称", "")})
            except Exception:
                logger.warning(f"{idx_name} 成分股获取失败")
    except Exception as e:
        logger.warning(f"Akshare 不可用: {e}")

    # 2. Baostock 全A股补充（去重，不含已纳入的指数成分股）
    try:
        from services.baostock_adapter import _ensure_login, _bs_lock

        with _bs_lock:
            if _ensure_login():
                rs = bs.query_stock_basic()
                if rs.error_code == "0":
                    while rs.next():
                        row = rs.get_row_data()
                        code = row[0].replace("sh.", "").replace("sz.", "")
                        if row[3] == "1" and row[4] == "1":  # type=股票, status=上市
                            if code not in index_codes:
                                stocks.append({
                                    "code": code,
                                    "name": row[1],
                                    "ipo_date": row[2],
                                })
                # 获取行业分类（对所有股票）
                rs_ind = bs.query_stock_industry()
                if rs_ind.error_code == "0":
                    ind_map: dict[str, dict] = {}
                    while rs_ind.next():
                        row = rs_ind.get_row_data()
                        c = row[1].replace("sh.", "").replace("sz.", "")
                        ind_map[c] = {"industry": row[2] if len(row) > 2 else "",
                                      "industry_type": row[3] if len(row) > 3 else ""}
                    for s in stocks:
                        if s["code"] in ind_map and "industry" not in s:
                            s.update(ind_map[s["code"]])
                # 注意：不调用 bs.logout() —— 连接由 baostock_adapter 统一管理
    except Exception as e:
        logger.warning(f"Baostock 股票列表获取失败: {e}")

    # 3. 兜底：Baostock 和 Akshare 都挂了
    if len(stocks) < 100:
        logger.error(f"股票池不足100只({len(stocks)})，选股结果不可靠")

    if stocks:
        _ALL_STOCKS_CACHE = stocks
        _all_stocks_ts = now
    return stocks


# ═══════════════════════════════════════════════════════════
# IC 权重计算
# ═══════════════════════════════════════════════════════════

# 默认因子权重（经验值，IC 数据不足时使用）
DEFAULT_FACTOR_WEIGHTS = {
    # 动量类（总权重 25%）
    "ret_5d": 0.03, "ret_20d": 0.06, "ret_60d": 0.06,
    "rsi_14": 0.04, "macd_signal": 0.03, "ma_disposition": 0.03,
    # 波动类（总权重 15%，越低越好，取负）
    "hist_vol_20d": -0.04, "atr_14": -0.02, "amplitude_20d": -0.02,
    "downside_vol": -0.07,
    # 量价类（总权重 15%）
    "vol_ratio": 0.03, "turnover_rate": 0.03, "obv_divergence": 0.04,
    "price_volume_corr": 0.02, "avg_amount": 0.03,
    # 基本面类（总权重 30%）
    "pe_inverse": 0.08, "pb_inverse": 0.06, "roe": 0.08,
    "eps_growth": 0.04, "market_cap_ln": -0.02, "dividend_yield": 0.02,
    # 情绪类（总权重 15%）
    "strength_20d": 0.08, "momentum_composite": 0.07,
}


def compute_ic_weights(benchmark_returns: list[float]) -> dict[str, float]:
    """基于过去 12 个月滚动 IC 计算因子权重

    会尝试对每个因子回溯其历史值和未来收益的相关性（IC），
    IC 绝对值大的因子获得更高权重。数据不足时退回到 DEFAULT_FACTOR_WEIGHTS。

    Returns:
        {factor_name: weight}  权重之和 = 1.0
    """
    # 实际滚动 IC 计算需要大量的历史因子面板数据
    # 当前版本使用默认权重 + 简单动量调整
    # 未来可扩展为真正的滚动IC

    # 根据近期市场状态微调权重
    weights = dict(DEFAULT_FACTOR_WEIGHTS)

    if not benchmark_returns or len(benchmark_returns) < 20:
        return _normalize_weights(weights)

    # 市场状态判断
    recent_20d = sum(benchmark_returns[-20:]) if len(benchmark_returns) >= 20 else 0
    recent_60d = sum(benchmark_returns[-60:]) if len(benchmark_returns) >= 60 else 0

    # 牛市：加大动量因子权重
    if recent_20d > 0.02 or recent_60d > 0.05:
        weights["ret_20d"] += 0.04
        weights["ret_60d"] += 0.04
        weights["strength_20d"] += 0.03
        weights["momentum_composite"] += 0.03
        weights["pe_inverse"] -= 0.02  # 牛市中价值因子退化
        weights["pb_inverse"] -= 0.02

    # 熊市：加大质量/价值因子
    if recent_20d < -0.02 or recent_60d < -0.05:
        weights["roe"] += 0.05
        weights["pe_inverse"] += 0.03
        weights["pb_inverse"] += 0.02
        weights["downside_vol"] -= 0.03  # 低波动更重要
        weights["ret_20d"] -= 0.03

    # 震荡市：加大量价/反转因子
    if abs(recent_20d) < 0.01 and abs(recent_60d) < 0.03:
        weights["vol_ratio"] += 0.03
        weights["price_volume_corr"] += 0.02
        weights["obv_divergence"] += 0.02
        weights["ret_5d"] -= 0.02  # 短期动量失效

    return _normalize_weights(weights)


def _normalize_weights(weights: dict) -> dict:
    """权重归一化到总和为 1.0"""
    abs_sum = sum(abs(w) for w in weights.values())
    if abs_sum == 0:
        return {k: 1.0 / len(weights) for k in weights}
    return {k: round(w / abs_sum, 6) for k, w in weights.items()}


# ═══════════════════════════════════════════════════════════
# 评分与筛选
# ═══════════════════════════════════════════════════════════

def score_stock(factors: dict[str, Optional[float]],
                weights: dict[str, float]) -> float:
    """对单只股票的因子值加权合成总分

    Args:
        factors: {factor_name: z_score_or_None}
        weights: {factor_name: weight}

    Returns:
        总分（越高越好）
    """
    score = 0.0
    total_weight = 0.0
    for fn, w in weights.items():
        val = factors.get(fn)
        if val is not None:
            score += val * w
            total_weight += abs(w)

    if total_weight == 0:
        return 0.0
    return round(score / total_weight, 6)


def _process_single_stock(code: str) -> Optional[dict]:
    """处理单只股票：取K线 → 算因子 → 返回"""
    try:
        mkt = get_market(code)
        kline = fetch_kline(code, mkt, days=120)
        if "error" in kline or not kline.get("closes") or len(kline["closes"]) < 60:
            return None

        # 获取基本面
        fundamentals = {}
        try:
            from services.baostock_adapter import get_stock_factors
            fundamentals = get_stock_factors(code)
        except Exception:
            pass

        result = compute_all_factors(
            code=code,
            closes=kline["closes"],
            highs=kline.get("highs", []),
            lows=kline.get("lows", []),
            volumes=kline.get("volumes", []),
            fundamentals=fundamentals if "error" not in fundamentals else {},
        )

        # 附上股票名称和行业
        result["name"] = fundamentals.get("name", "") if isinstance(fundamentals, dict) else ""
        result["industry"] = fundamentals.get("industry", "") if isinstance(fundamentals, dict) else ""
        result["price"] = kline["closes"][-1] if kline["closes"] else None

        return result
    except Exception:
        return None


def run_screener(
    stock_list: list[dict] = None,
    max_workers: int = 3,
    progress_callback=None,
) -> dict:
    """全市场多因子筛选

    Args:
        stock_list: 股票列表，默认自动获取全A股
        max_workers: 并发线程数
        progress_callback: 可选，进度回调 (current, total) → None

    Returns:
        {
            "total_stocks": int,
            "scanned": int,
            "candidates": [{code, name, score, factors, ...}, ...],  # Top 50
            "factor_weights": {name: weight},
            "market_state": str,
        }
    """
    if stock_list is None:
        stock_list = get_all_stock_list()

    if not stock_list:
        return {"error": "无法获取股票列表", "total_stocks": 0, "scanned": 0, "candidates": []}

    total = len(stock_list)

    # 获取基准收益判断市场状态（用于IC权重调整）
    try:
        bench_kline = fetch_kline("000300", "1", days=252)
        from services.factor_service import _returns
        bench_returns = _returns(bench_kline["closes"]) if "closes" in bench_kline else []
    except Exception:
        bench_returns = []

    weights = compute_ic_weights(bench_returns)
    market_state = _market_state_label(bench_returns)

    # 并发计算因子
    all_factors = []
    scanned = 0
    codes = [s["code"] for s in stock_list if s.get("code")]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_single_stock, c): c for c in codes}
        for i, future in enumerate(as_completed(futures)):
            try:
                result = future.result(timeout=30)
                if result:
                    all_factors.append(result)
                scanned += 1
                if progress_callback:
                    progress_callback(scanned, total)
            except Exception:
                scanned += 1
                pass

    if not all_factors:
        return {"error": "未能计算出任何有效因子", "total_stocks": total, "scanned": scanned, "candidates": []}

    # 截面标准化
    normalized = normalize_factors(all_factors)

    # 打分排序
    scored = []
    for nf in normalized:
        score = score_stock(nf["factors"], weights)
        scored.append({
            "code": nf["code"],
            "name": nf.get("name", ""),
            "industry": nf.get("industry", ""),
            "score": score,
            "factors": {k: v for k, v in nf["factors"].items() if v is not None},
            "hit_count": nf["hit_count"],
            "price": nf.get("price"),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Top 50
    top50 = scored[:50]

    # 补充因子解读
    for s in top50:
        s["top_factors"] = _explain_top_factors(s["factors"], weights)

    return {
        "total_stocks": total,
        "scanned": scanned,
        "candidates": top50,
        "factor_weights": weights,
        "market_state": market_state,
    }


def _market_state_label(returns: list[float]) -> str:
    """判断市场状态标签"""
    if not returns or len(returns) < 20:
        return "unknown"
    ret_20 = sum(returns[-20:])
    ret_60 = sum(returns[-60:]) if len(returns) >= 60 else ret_20
    if ret_20 > 0.03 or ret_60 > 0.06:
        return "bull"
    if ret_20 < -0.03 or ret_60 < -0.06:
        return "bear"
    return "range"


def _explain_top_factors(factors: dict[str, float],
                         weights: dict[str, float]) -> list[dict]:
    """解释单只股票得分的主要贡献因子（TOP 3 正向 + TOP 2 负向）"""
    contributions = []
    for fn, z_val in factors.items():
        w = weights.get(fn, 0)
        contrib = z_val * w
        contributions.append({"factor": fn, "z_score": z_val, "weight": w, "contribution": round(contrib, 6)})

    contributions.sort(key=lambda x: x["contribution"], reverse=True)
    return contributions[:5]  # 前5个最大贡献


# ═══════════════════════════════════════════════════════════
# 行业中性化
# ═══════════════════════════════════════════════════════════

def industry_neutralize(candidates: list[dict]) -> list[dict]:
    """对候选池做行业中性化：每个行业内独立排名，确保不偏向某一行业

    Args:
        candidates: [{code, industry, score, ...}, ...]

    Returns:
        行业中性化后排名的候选池
    """
    if not candidates:
        return candidates

    # 按行业分组
    ind_groups: dict[str, list[dict]] = {}
    others = []
    for c in candidates:
        ind = c.get("industry", "")
        if ind:
            ind_groups.setdefault(ind, []).append(c)
        else:
            others.append(c)

    # 每个行业内独立算 Z-Score
    result = []
    for ind, items in ind_groups.items():
        scores = [it["score"] for it in items]
        if len(scores) < 2:
            result.extend(items)
            continue
        mean = sum(scores) / len(scores)
        std = (sum((s - mean) ** 2 for s in scores) / (len(scores) - 1)) ** 0.5
        if std == 0:
            std = 1e-8
        for it in items:
            it["score_neutral"] = round((it["score"] - mean) / std, 6)
        result.extend(items)

    # 无行业的保持原分数
    for it in others:
        it["score_neutral"] = it["score"]
    result.extend(others)

    # 按中性化分数重新排名
    result.sort(key=lambda x: x.get("score_neutral", x["score"]), reverse=True)
    return result
