"""雪球社区热度数据服务

通过 akshare 获取雪球关注数、东方财富人气排名，用于社交情绪因子。

API:
  - stock_hot_tweet_xq:    雪球关注数（全市场 5600+ 只股票）
  - stock_hot_rank_em:     东方财富人气榜（Top 100）
  - stock_hot_follow_xq:   雪球热门关注榜
"""

import time
from typing import Optional

# ── 缓存 ──

_FOLLOW_COUNT_CACHE: dict[str, int] = {}
_FOLLOW_COUNT_TS = 0.0
_FOLLOW_COUNT_TTL = 3600.0  # 1 小时


def _load_follow_counts() -> dict[str, int]:
    """从 akshare 加载全市场雪球关注数（缓存 1 小时）"""
    global _FOLLOW_COUNT_CACHE, _FOLLOW_COUNT_TS
    now = time.time()
    if _FOLLOW_COUNT_CACHE and (now - _FOLLOW_COUNT_TS) < _FOLLOW_COUNT_TTL:
        return _FOLLOW_COUNT_CACHE

    try:
        import akshare as ak
        df = ak.stock_hot_tweet_xq()
        if df is not None and not df.empty:
            new_cache: dict[str, int] = {}
            for _, row in df.iterrows():
                code = str(row.get("股票代码", "")).replace("SH", "").replace("SZ", "")
                follow = int(row.get("关注", 0) or 0)
                if code and len(code) == 6:
                    new_cache[code] = follow
            _FOLLOW_COUNT_CACHE = new_cache
            _FOLLOW_COUNT_TS = now
    except Exception:
        pass
    return _FOLLOW_COUNT_CACHE


def get_stock_social_score(code: str) -> dict:
    """获取单只股票的社交热度评分

    使用雪球关注数（全市场 5600+ 只），计算该股票的社交关注度。

    Returns:
        {
            follow_count: int,           # 雪球关注人数
            follow_rank: int | None,     # 关注数排名（1=最高，None=无数据）
            heat_score: float,           # 热度分（0-100）
        }
    """
    follows = _load_follow_counts()
    count = follows.get(code, 0)

    # 计算排名（关注数降序）
    rank = None
    if count > 0:
        sorted_counts = sorted(set(follows.values()), reverse=True)
        for i, c in enumerate(sorted_counts, 1):
            if c == count:
                rank = i
                break

    # 热度分：log 压缩关注数 → [0, 100]
    import math
    max_follow = max(follows.values()) if follows else 100000
    if count > 0:
        heat_score = round(min(math.log(count + 1) / math.log(max_follow + 1) * 100, 100), 1)
    else:
        heat_score = 0.0

    return {
        "follow_count": count,
        "follow_rank": rank,
        "heat_score": heat_score,
    }


def get_stock_follow_count(code: str) -> int:
    """快速获取单只股票的雪球关注数"""
    return get_stock_social_score(code).get("follow_count", 0)
