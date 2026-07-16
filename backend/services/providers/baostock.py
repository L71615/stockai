"""Baostock Provider

提供:
    - BaostockIndustryProvider: 全市场 industry_type 映射 (5534 个代码,~13s)
                                  fetch_one 查单只; fetch_all 返回全量 (每条仅含 industry)
    - BaostockKLineProvider:    单只历史 K 线 (1.5s/只)
"""
import logging
from .base import StockInfo, KLine

logger = logging.getLogger(__name__)


class BaostockIndustryProvider:
    """仅提供 industry 字段 (industry_type — 行业代码，"J66货币金融服务" 这种)

    在 Chain 里通常作为 AkshareProvider 之后的兜底，专门补 industry。
    Tushare provider 已经包含 industry，所以这两个不要并列使用。
    """
    name = "baostock_industry"

    def fetch_all(self) -> list[StockInfo]:
        from services.baostock_adapter import _get_industry_map
        bs_map = _get_industry_map()
        out = []
        for code, entry in bs_map.items():
            ind_type = (entry.get("industry_type") or "").strip()
            if not ind_type:
                continue
            out.append(StockInfo(
                code=code, name="", industry=ind_type,
                list_date="",
            ))
        return out

    def fetch_one(self, code: str) -> StockInfo | None:
        from services.baostock_adapter import _get_industry_map
        bs_map = _get_industry_map()
        entry = bs_map.get(code)
        if not entry:
            return None
        ind = (entry.get("industry_type") or "").strip()
        if not ind:
            return None
        return StockInfo(code=code, name="", industry=ind)


class BaostockKLineProvider:
    name = "baostock_kline"

    def fetch(self, code: str, days: int = 252) -> list[KLine] | None:
        from services.baostock_adapter import get_kline
        d = get_kline(code, days=days, freq="d")
        dates   = d.get("dates", []) or []
        opens   = d.get("opens", []) or []
        highs   = d.get("highs", []) or []
        lows    = d.get("lows", []) or []
        closes  = d.get("closes", []) or []
        volumes = d.get("volumes", []) or []
        n = min(len(dates), len(opens), len(highs), len(lows), len(closes), len(volumes))
        if n == 0:
            return None
        out = []
        for i in range(n):
            if dates[i] is None or closes[i] is None:
                continue
            out.append(KLine(
                trade_date=str(dates[i]),
                open=opens[i] or 0.0,
                high=highs[i] or 0.0,
                low=lows[i] or 0.0,
                close=closes[i] or 0.0,
                volume=volumes[i] or 0.0,
            ))
        return out if out else None
