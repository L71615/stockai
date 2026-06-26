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


def _fill_empty_names(stocks: list[dict]) -> None:
    """补全股票列表中缺失的名称"""
    need_name = [s for s in stocks if not s.get("name")]
    if not need_name:
        return
    # 1. 尝试从 Baostock 静态列表查找
    try:
        from services.baostock_adapter import _ensure_login, _bs_lock
        with _bs_lock:
            if _ensure_login():
                rs = bs.query_stock_basic()
                if rs.error_code == "0":
                    name_map: dict[str, str] = {}
                    while rs.next():
                        row = rs.get_row_data()
                        code = row[0].replace("sh.", "").replace("sz.", "")
                        name_map[code] = row[1]
                    for s in need_name:
                        if s["code"] in name_map:
                            s["name"] = name_map[s["code"]]
    except Exception:
        logger.warning("screener_service: _fill_empty_names Baostock lookup failed", exc_info=True)
    # 2. 剩余尝试从 akshare 获取
    still_need = [s for s in need_name if not s.get("name")]
    if still_need:
        try:
            from services.akshare_adapter import get_stock_name
            for s in still_need:
                n = get_stock_name(s["code"])
                if n:
                    s["name"] = n
        except Exception:
            logger.warning("screener_service: _fill_empty_names akshare lookup failed", exc_info=True)


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
                    name = str(row.get("成分券名称", "") or "")
                    stocks.append({"code": code, "name": name})
            except Exception:
                logger.warning(f"{idx_name} 成分股获取失败")
    except Exception as e:
        logger.warning(f"Akshare 不可用: {e}")

    # 2. Baostock 全A股补充（去重，不含已纳入的指数成分股）
    # 用线程超时包装，避免 Baostock 挂起阻塞整个扫描
    try:
        from services.baostock_adapter import _ensure_login, _bs_lock
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

        def _fetch_baostock():
            """Baostock 全 A 股 + 行业分类（在线程中执行，可被超时中断）"""
            new_stocks = []
            ind_map: dict[str, dict] = {}
            with _bs_lock:
                if not _ensure_login():
                    return new_stocks, ind_map
                rs = bs.query_stock_basic()
                if rs.error_code == "0":
                    while rs.next():
                        row = rs.get_row_data()
                        code = row[0].replace("sh.", "").replace("sz.", "")
                        if row[3] == "1" and row[4] == "1":
                            if code not in index_codes:
                                new_stocks.append({
                                    "code": code,
                                    "name": row[1],
                                    "ipo_date": row[2],
                                })
                # 行业分类
                rs_ind = bs.query_stock_industry()
                if rs_ind.error_code == "0":
                    while rs_ind.next():
                        row = rs_ind.get_row_data()
                        c = row[1].replace("sh.", "").replace("sz.", "")
                        ind_map[c] = {"industry": row[2] if len(row) > 2 else "",
                                      "industry_type": row[3] if len(row) > 3 else ""}
            return new_stocks, ind_map

        with ThreadPoolExecutor(max_workers=1) as _executor:
            _future = _executor.submit(_fetch_baostock)
            try:
                _baostock_stocks, _ind_map = _future.result(timeout=8)
                stocks.extend(_baostock_stocks)
                for s in stocks:
                    if s["code"] in _ind_map and "industry" not in s:
                        s.update(_ind_map[s["code"]])
            except FutureTimeoutError:
                logger.warning("Baostock 股票列表获取超时(8s)，跳过，仅用指数成分股")
    except Exception as e:
        logger.warning(f"Baostock 股票列表获取失败: {e}")

    # 1.5 补全空名称：对没有名字的股票，从 Baostock 或行情缓存中查找
    _fill_empty_names(stocks)

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
    # 情绪类（总权重 10%）
    "strength_20d": 0.06, "momentum_composite": 0.04,
    # 资金类（总权重 9%，北向/机构）
    "north_flow": 0.05, "inst_change": 0.04,
}


def _spearman_ic(x_vals: list, y_vals: list) -> float | None:
    """计算 Spearman 秩相关系数（Information Coefficient）

    对 x_vals 和 y_vals 分别求秩，计算秩的 Pearson 相关系数。
    None 值会被跳过。需要至少 30 对有效数据点。
    """
    import math as _math

    pairs = [(a, b) for a, b in zip(x_vals, y_vals) if a is not None and b is not None]
    if len(pairs) < 30:
        return None

    n = len(pairs)
    # 排序求秩
    x_sorted = sorted(range(n), key=lambda i: pairs[i][0])
    y_sorted = sorted(range(n), key=lambda i: pairs[i][1])
    x_rank = [0] * n
    y_rank = [0] * n
    for rank, idx in enumerate(x_sorted, 1):
        x_rank[idx] = rank
    for rank, idx in enumerate(y_sorted, 1):
        y_rank[idx] = rank

    mean_x = sum(x_rank) / n
    mean_y = sum(y_rank) / n
    cov = sum((x_rank[i] - mean_x) * (y_rank[i] - mean_y) for i in range(n))
    std_x = _math.sqrt(sum((r - mean_x) ** 2 for r in x_rank))
    std_y = _math.sqrt(sum((r - mean_y) ** 2 for r in y_rank))

    if std_x == 0 or std_y == 0:
        return None
    return cov / (std_x * std_y)


def compute_ic_weights(
    normalized_factors: list[dict] | None = None,
    benchmark_returns: list[float] | None = None,
) -> dict[str, float]:
    """基于截面秩 IC 的因子权重

    核心逻辑：
    1. 对每个因子，计算其 Z-score 与股票 ret_20d 的 Spearman 秩相关（IC）
    2. |IC| 越大 → 该因子预测力越强 → 权重越高
    3. 60% IC + 40% 默认权重融合，保证稳定性
    4. 保留默认权重的符号（负号 = 因子值越低越好）

    当扫描样本不足或 IC 计算失败时，回退到 DEFAULT_FACTOR_WEIGHTS
    + 市场状态微调（牛市偏动量、熊市偏质量、震荡偏量价）。

    Returns:
        {factor_name: weight}  绝对值之和 = 1.0
    """
    # ── 默认权重 ──
    weights = dict(DEFAULT_FACTOR_WEIGHTS)

    # ── 尝试计算真实截面 IC ──
    ic_weights: dict[str, float] = {}
    if normalized_factors and len(normalized_factors) >= 30:
        # 提取每个因子的截面值 + 目标收益（ret_20d）
        factor_names = list(DEFAULT_FACTOR_WEIGHTS.keys())
        target_returns: list[float | None] = []
        factor_panels: dict[str, list[float | None]] = {fn: [] for fn in factor_names}

        for nf in normalized_factors:
            fv = nf["factors"]
            target_returns.append(fv.get("ret_20d"))
            for fn in factor_names:
                factor_panels[fn].append(fv.get(fn))

        # 逐因子算 Spearman IC
        for fn in factor_names:
            ic = _spearman_ic(factor_panels[fn], target_returns)
            if ic is not None:
                ic_weights[fn] = abs(ic)  # |IC| 越大越重要

        if ic_weights:
            # 60% IC + 40% 默认融合
            for fn in weights:
                ic_w = ic_weights.get(fn, 0.0)
                default_w = abs(weights[fn])
                blended = ic_w * 0.6 + default_w * 0.4
                # 保留原符号（负数表示因子值越低越好）
                weights[fn] = blended if weights[fn] >= 0 else -blended

    # ── 市场状态微调（与 IC 权重叠加） ──
    if benchmark_returns and len(benchmark_returns) >= 20:
        ret_20 = sum(benchmark_returns[-20:])
        ret_60 = sum(benchmark_returns[-60:]) if len(benchmark_returns) >= 60 else ret_20

        # 牛市：动量因子更有效
        if ret_20 > 0.02 or ret_60 > 0.05:
            weights["ret_20d"] = abs(weights["ret_20d"]) + 0.03
            weights["ret_60d"] = abs(weights["ret_60d"]) + 0.03
            weights["strength_20d"] = abs(weights["strength_20d"]) + 0.02
        # 熊市：质量/低波因子更有效
        if ret_20 < -0.02 or ret_60 < -0.05:
            weights["roe"] = abs(weights["roe"]) + 0.04
            weights["pe_inverse"] = abs(weights["pe_inverse"]) + 0.02
            weights["downside_vol"] = -(abs(weights["downside_vol"]) + 0.03)
        # 震荡市：量价因子更有效
        if abs(ret_20) < 0.01 and abs(ret_60) < 0.03:
            weights["vol_ratio"] = abs(weights["vol_ratio"]) + 0.02
            weights["obv_divergence"] = abs(weights["obv_divergence"]) + 0.02

    return _normalize_weights(weights)


def _normalize_weights(weights: dict) -> dict:
    """权重归一化到绝对值总和为 1.0"""
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
        price = kline["closes"][-1] if kline["closes"] else None

        # 获取基本面：优先 akshare HTTP（无锁，真并发），失败回退 Baostock
        fund = {}
        try:
            from services.akshare_adapter import get_stock_factors_http
            http = get_stock_factors_http(code)
            if http:
                # akshare 成功 — 只用 HTTP 数据，缺失 total_shares/dividend 仅
                # 影响 turnover_rate 和 dividend_yield 两个低权因子，不调 Baostock
                fund = http
                if price and fund.get("bvps") and fund["bvps"] > 0:
                    fund["pb"] = round(price / fund["bvps"], 4)
                if price and fund.get("eps") and fund["eps"] > 0:
                    fund["pe"] = round(price / fund["eps"], 2)
                if price:
                    fund["price"] = price
                # 行业从全局缓存取（已在 baostock 侧缓存，这里直接查）
                try:
                    from services.baostock_adapter import _get_industry_map
                    ind_map = _get_industry_map()
                    if code in ind_map:
                        fund.update(ind_map[code])
                except Exception:
                    logger.warning("screener_service: industry map lookup failed for %s", code, exc_info=True)
            else:
                # akshare 失败 — 完整走 Baostock
                try:
                    from services.baostock_adapter import get_stock_factors as _bs_factors
                    bs = _bs_factors(code)
                    if isinstance(bs, dict) and "error" not in bs:
                        fund = bs
                except Exception:
                    logger.warning("screener_service: Baostock factors fallback failed for %s", code, exc_info=True)
        except Exception:
            logger.warning("screener_service: fundamentals fetch failed for %s", code, exc_info=True)

        # 注入雪球社交数据（已在 run_screener 预热缓存）
        try:
            from services.social_service import get_stock_social_score
            stock_name = fund.get("name", "")
            fund["_social"] = get_stock_social_score(code, stock_name)
        except Exception:
            fund["_social"] = {}

        # 获取北向资金 / 机构持仓数据
        north_flow_data = None
        inst_data = None
        try:
            from services.akshare_adapter import get_north_flow, get_inst_holding
            north_flow_data = get_north_flow(code)
            inst_data = get_inst_holding(code)
        except Exception:
            logger.warning("screener_service: north_flow/inst fetch failed for %s", code, exc_info=True)

        result = compute_all_factors(
            code=code,
            closes=kline["closes"],
            highs=kline.get("highs", []),
            lows=kline.get("lows", []),
            volumes=kline.get("volumes", []),
            fundamentals=fund,
            prev_eps=fund.get("prev_eps"),
            dividend=fund.get("dividend"),
            north_flow_data=north_flow_data,
            inst_data=inst_data,
        )

        # 附上股票名称和行业
        result["name"] = fund.get("name", "")
        result["industry"] = fund.get("industry", "")
        result["price"] = price

        return result
    except Exception:
        logger.warning("screener_service: _process_single_stock failed for %s", code, exc_info=True)
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

    # 获取基准收益（用于市场状态判断和 IC 权重微调）
    try:
        bench_kline = fetch_kline("000300", "1", days=252)
        from services.factor_service import _returns
        bench_returns = _returns(bench_kline["closes"]) if "closes" in bench_kline else []
    except Exception:
        bench_returns = []

    market_state = _market_state_label(bench_returns)

    # 预热全局缓存（避免线程内抢 Baostock 锁）
    try:
        from services.baostock_adapter import _get_industry_map
        _get_industry_map()  # 一次性查询全市场行业分类，后续线程直接读缓存
    except Exception:
        logger.warning("screener_service: industry map preheat failed", exc_info=True)

    # 预热雪球人气榜缓存（一次拉取，线程内直接匹配）
    hot_stocks = []
    try:
        from services.social_service import get_hot_stocks
        hot_stocks = get_hot_stocks(50)
    except Exception:
        logger.warning("screener_service: hot stocks preheat failed", exc_info=True)

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
                logger.warning("screener_service: future.result() failed for %s", futures[future], exc_info=True)
                scanned += 1

    if not all_factors:
        return {"error": "未能计算出任何有效因子", "total_stocks": total, "scanned": scanned, "candidates": []}

    # 截面标准化
    normalized = normalize_factors(all_factors)

    # 基于截面 IC 的因子权重（归一化后计算，用真实数据驱动）
    weights = compute_ic_weights(normalized, bench_returns)

    # 打分排序
    # 名称兜底：提前构建 stock_list 查找表（O(n)），避免循环内重复构建（原 O(n²)）
    stock_name_map = {s["code"]: s for s in stock_list}
    scored = []
    for nf in normalized:
        score = score_stock(nf["factors"], weights)
        scored.append({
            "code": nf["code"],
            "name": nf.get("name", "") or stock_name_map.get(nf["code"], {}).get("name", ""),
            "industry": nf.get("industry", "") or stock_name_map.get(nf["code"], {}).get("industry", ""),
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
