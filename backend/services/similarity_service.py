"""因子相似度引擎 — 余弦相似度 + 历史胜率聚合"""

import math, logging
from services.historical_panel import PREDICTION_FACTORS, get_latest_panel

logger = logging.getLogger(__name__)


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """计算两个因子向量的余弦相似度"""
    keys = [k for k in PREDICTION_FACTORS if k in a and k in b]
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(a[k] ** 2 for k in keys))
    nb = math.sqrt(sum(b[k] ** 2 for k in keys))
    if na == 0 or nb == 0:
        return 0.0
    return round(dot / (na * nb), 6)


def find_similar_periods(
    target_factors: dict[str, float],
    historical_panels: list[dict],
    top_k: int = 20,
) -> list[dict]:
    """在历史因子面板中找与当前因子最相似的 K 个时刻

    Args:
        target_factors: 当前股票的因子向量 {factor_name: z_score}
        historical_panels: load_historical_panels() 的输出
        top_k: 返回最相似的 K 个

    Returns:
        [{date, stock_code, fwd_ret_1d, fwd_ret_3d, fwd_ret_5d, similarity}]
    """
    matches = []

    for panel in historical_panels:
        date = panel["date"]
        for code, data in panel.get("stocks", {}).items():
            hist_factors = data.get("factors", {})
            if not hist_factors:
                continue
            sim = cosine_similarity(target_factors, hist_factors)
            if sim > 0.5:  # 只保留相似度 > 0.5 的
                matches.append({
                    "date": date,
                    "stock_code": code,
                    "fwd_ret_1d": data.get("fwd_ret_1d"),
                    "fwd_ret_3d": data.get("fwd_ret_3d"),
                    "fwd_ret_5d": data.get("fwd_ret_5d"),
                    "similarity": sim,
                })

    # 按相似度降序
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches[:top_k]


def aggregate_prediction(matches: list[dict]) -> dict:
    """从相似历史时刻聚合预测概率

    Returns:
        {
            probability_1d: 上涨概率 0-1,
            probability_3d: 上涨概率 0-1,
            probability_5d: 上涨概率 0-1,
            similar_count: 找到多少个相似时刻,
            win_count_1d: 1天后涨了几次,
            win_count_3d: 3天后涨了几次,
            win_count_5d: 5天后涨了几次,
            avg_similarity: 平均相似度,
            top_matches: 最相似的5个详情
        }
    """
    if not matches:
        return {
            "probability_1d": None, "probability_3d": None, "probability_5d": None,
            "similar_count": 0, "win_count_1d": 0, "win_count_3d": 0, "win_count_5d": 0,
            "avg_similarity": 0, "top_matches": [],
        }

    total = len(matches)

    def win_rate(n_days: int) -> dict:
        key = f"fwd_ret_{n_days}d"
        valid = [m for m in matches if m.get(key) is not None]
        wins = sum(1 for m in valid if m[key] > 0)
        prob = round(wins / len(valid), 4) if valid else None
        return {"wins": wins, "total": len(valid), "probability": prob}

    wr1 = win_rate(1)
    wr3 = win_rate(3)
    wr5 = win_rate(5)

    avg_sim = round(sum(m["similarity"] for m in matches) / total, 4)

    top5 = sorted(matches, key=lambda x: x["similarity"], reverse=True)[:5]
    top_matches = [{
        "date": m["date"],
        "stock_code": m["stock_code"],
        "fwd_ret_1d": m.get("fwd_ret_1d"),
        "fwd_ret_3d": m.get("fwd_ret_3d"),
        "similarity": m["similarity"],
    } for m in top5]

    return {
        "probability_1d": wr1["probability"],
        "probability_3d": wr3["probability"],
        "probability_5d": wr5["probability"],
        "similar_count": total,
        "win_count_1d": wr1["wins"],
        "win_count_3d": wr3["wins"],
        "win_count_5d": wr5["wins"],
        "avg_similarity": avg_sim,
        "top_matches": top_matches,
    }
