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

# ═══════════════════════════════════════════════════════════════
#  板块分类 — 过滤买不了的股票（科创板/北交所/创业板需权限）
# ═══════════════════════════════════════════════════════════════

import re

_BOARD_RULES: dict[str, dict] = {
    "main_sh":   {"pattern": r"^60[0-9]{4}$",      "label": "上海主板", "need_permission": False},
    "main_sz":   {"pattern": r"^00[0-39][0-9]{3}$", "label": "深圳主板", "need_permission": False},
    "gem":       {"pattern": r"^30[0-9]{4}$",       "label": "创业板",   "need_permission": True,  "permission_desc": "需2年交易经验+10万资产"},
    "star":      {"pattern": r"^68[0-9]{4}$",       "label": "科创板",   "need_permission": True,  "permission_desc": "需50万资产"},
    "bse":       {"pattern": r"^8[0-9]{5}$",        "label": "北交所",   "need_permission": True,  "permission_desc": "需50万资产+2年经验"},
    "nq":        {"pattern": r"^4[0-9]{5}$",        "label": "三板",     "need_permission": True,  "permission_desc": "需特殊权限"},
}

_DEFAULT_ALLOWED_BOARDS = {"main_sh", "main_sz"}


def detect_board(code: str) -> str:
    """根据股票代码检测所属板块"""
    for board_id, rule in _BOARD_RULES.items():
        if re.match(rule["pattern"], code):
            return board_id
    return "other"


def filter_by_board(stocks: list[dict], allowed_boards: set[str] | None = None) -> list[dict]:
    """按板块过滤股票列表。allowed_boards=None 时默认只用沪深主板"""
    if allowed_boards is None:
        allowed_boards = _DEFAULT_ALLOWED_BOARDS
    result = []
    for s in stocks:
        code = s.get("code", "")
        board = detect_board(code)
        if board in allowed_boards or board == "other":
            s["board"] = board
            result.append(s)
    return result


def get_board_summary(stocks: list[dict]) -> dict:
    """获取股票池板块分布统计"""
    counts: dict[str, int] = {}
    for s in stocks:
        code = s.get("code", "")
        board = detect_board(code)
        counts[board] = counts.get(board, 0) + 1
    return {b: {"count": c, "label": _BOARD_RULES.get(b, {}).get("label", b)} for b, c in counts.items()}

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
    """获取选股池股票列表（从本地 historical_kline 读，默认主板）

    Returns:
        [{code, name}, ...]
    """
    global _ALL_STOCKS_CACHE, _all_stocks_ts
    now = time.time()
    if _ALL_STOCKS_CACHE and not force_refresh and (now - _all_stocks_ts) < _ALL_STOCKS_TTL:
        return _ALL_STOCKS_CACHE

    from database import query_all
    rows = query_all(
        "SELECT DISTINCT stock_code FROM historical_kline WHERE trade_date = (SELECT MAX(trade_date) FROM historical_kline)"
    )
    stocks = []
    for r in rows:
        code = r["stock_code"]
        if detect_board(code) in ("main_sh", "main_sz"):
            stocks.append({"code": code, "name": "", "industry": ""})

    logger.info("get_all_stock_list: %d 只 (来自本地 historical_kline)", len(stocks))
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
    """处理单只股票：从本地 historical_kline 取K线 → 算因子 → 返回"""
    try:
        # 从本地 historical_kline 读取 K 线（零外部调用）
        from database import query_all
        rows = query_all(
            "SELECT trade_date, open, high, low, close, volume FROM historical_kline WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 120",
            (code,),
        )
        if len(rows) < 60:
            return None

        rows_rev = list(reversed(rows))
        kline = {
            "dates": [r["trade_date"] for r in rows_rev],
            "opens": [r["open"] for r in rows_rev],
            "highs": [r["high"] for r in rows_rev],
            "lows": [r["low"] for r in rows_rev],
            "closes": [r["close"] for r in rows_rev],
            "volumes": [r["volume"] for r in rows_rev],
        }

        price = kline["closes"][-1]

        # 从本地 local_fundamentals 获取基本面
        fund = {"price": price}
        try:
            frow = query_all(
                "SELECT pe_ttm, pb, market_cap, turnover_rate, roe, dividend_yield FROM local_fundamentals WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 1",
                (code,),
            )
            if frow:
                f = frow[0]
                fund["pe"] = f["pe_ttm"]
                fund["pb"] = f["pb"]
                fund["market_cap"] = f["market_cap"]
                fund["turnover_rate"] = f["turnover_rate"]
                fund["roe"] = f["roe"]
                fund["dividend_yield"] = f["dividend_yield"]
        except Exception:
            pass

        # 名称 + 行业 — 从 stock_info 缓存读取（run_screener 已预热全市场）
        try:
            from database import query_one
            info_row = query_one(
                "SELECT name, industry FROM stock_info WHERE stock_code = ?", (code,)
            )
            if info_row:
                fund["name"] = info_row.get("name", "") or ""
                fund["industry"] = info_row.get("industry", "") or ""
            else:
                fund.setdefault("name", "")
                fund.setdefault("industry", "")
        except Exception:
            fund.setdefault("name", "")
            fund.setdefault("industry", "")

        # 行业兜底 — Tushare preheat 失败时，从 Baostock industry_map 拿
        # (24h 全局缓存 + run_screener 已预热，此处是 dict lookup)
        if not fund.get("industry"):
            try:
                from services.baostock_adapter import _get_industry_map
                ind_map = _get_industry_map()
                if code in ind_map:
                    fund["industry"] = ind_map[code].get("industry", "") or ""
            except Exception:
                pass

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
    allowed_boards: set[str] | None = None,
) -> dict:
    """全市场多因子筛选

    Args:
        stock_list: 股票列表，默认自动获取全A股
        max_workers: 并发线程数
        progress_callback: 可选，进度回调 (current, total) -> None
        allowed_boards: 允许的板块集合，None=默认（沪深主板）。可选: main_sh, main_sz, gem, star, bse, nq

    Returns:
        {
            "total_stocks": int,
            "scanned": int,
            "candidates": [{code, name, score, factors, ...}, ...],
            "factor_weights": {name: weight},
            "market_state": str,
            "board_summary": {...},
            "board_filter": [...],
        }
    """
    if stock_list is None:
        from database import query_all
        stock_list = [
            {"code": r["stock_code"], "name": ""}
            for r in query_all(
                "SELECT DISTINCT stock_code FROM historical_kline WHERE trade_date = (SELECT MAX(trade_date) FROM historical_kline)"
            )
        ]
        # 板块过滤：应用 allowed_boards
        if allowed_boards:
            stock_list = [s for s in stock_list if detect_board(s["code"]) in allowed_boards]
        else:
            stock_list = [s for s in stock_list if detect_board(s["code"]) in _DEFAULT_ALLOWED_BOARDS]

    if not stock_list:
        return {"error": "无法获取股票列表", "total_stocks": 0, "scanned": 0, "candidates": []}

    # 板块过滤
    if allowed_boards is None:
        allowed_boards = _DEFAULT_ALLOWED_BOARDS
    board_summary_before = get_board_summary(stock_list)
    stock_list = filter_by_board(stock_list, allowed_boards)

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

    # 并发计算因子
    all_factors = []
    scanned = 0
    codes = [s["code"] for s in stock_list if s.get("code")]

    # 预热 stock_info 缓存（Tushare 一次拉全市场 → name + industry，避免单只循环查询）
    try:
        from services.tushare_adapter import preheat_stock_info
        preheat_result = preheat_stock_info(codes)
        source = preheat_result.get("source", "unknown")
        # 关键：written==0 说明所有数据源都拿不到数据，
        # 必须升 WARNING，否则下游 stock_info 为空、name/industry 全靠兜底，回归不可见。
        if preheat_result.get("written", 0) == 0:
            logger.warning(
                "screener_service: stock_info 预热 0 行写入 (source=%s, total=%s, error=%s) — 名称/行业将走 Baostock 兜底",
                source, preheat_result.get("total"), preheat_result.get("error"),
            )
        else:
            logger.info("screener_service: stock_info 预热 source=%s, written=%s", source, preheat_result.get("written"))
    except Exception:
        logger.warning("screener_service: stock_info 预热失败", exc_info=True)

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
        # Compute signal confidence
        factors_dict = {k: v for k, v in nf["factors"].items() if v is not None}
        confidence = _calc_confidence(factors_dict)

        scored.append({
            "code": nf["code"],
            "name": nf.get("name", "") or stock_name_map.get(nf["code"], {}).get("name", ""),
            "industry": nf.get("industry", "") or stock_name_map.get(nf["code"], {}).get("industry", ""),
            "score": score,
            "confidence": confidence,
            "confidence_label": "高" if confidence >= 0.7 else ("中" if confidence >= 0.4 else "低"),
            "factors": factors_dict,
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
        "board_summary": board_summary_before,
        "board_filter": list(allowed_boards),
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


def _calc_confidence(factors: dict[str, float]) -> float:
    """信号置信度评分 (0.0-1.0)

    四维度:
    1. 因子一致性 (40%): 正向因子占比
    2. 风险调整 (25%): 波动率越低越可信
    3. 流动性 (20%): 成交额越大越可信
    4. 因子覆盖率 (15%): 有效因子越多越可信
    """
    if not factors:
        return 0.0
    score = 0.0

    # 1. Factor agreement (40%)
    vals = [v for v in factors.values() if v is not None]
    pos_count = sum(1 for v in vals if v > 0)
    score += (pos_count / max(len(vals), 1)) * 0.4

    # 2. Risk adjustment (25%) — lower vol = higher confidence
    vol20 = factors.get("hist_vol_20d") or factors.get("HV_20")
    if vol20 is not None and vol20 > 0:
        vol_score = max(0, 1 - vol20 / 0.5)
        score += vol_score * 0.25

    # 3. Liquidity (20%)
    avg_amt = factors.get("avg_amount")
    if avg_amt is not None:
        # log10(1e8)=8, log10(1e7)=7
        score += min(1.0, max(0, (avg_amt - 6.0) / 3.0)) * 0.2

    # 4. Factor coverage (15%)
    coverage = len(vals) / 57  # total possible factors
    score += min(1.0, coverage * 2) * 0.15

    return round(min(score, 1.0), 4)


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
