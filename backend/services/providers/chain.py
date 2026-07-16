"""Chain — 把多个 Provider 串成 fallback 链"""
import logging
from typing import TypeVar

from .base import StockInfo, KLine, StockInfoProvider, KLineProvider

logger = logging.getLogger(__name__)

P = TypeVar("P")


class StockInfoChain:
    """按声明顺序尝试各 Provider；第一个返回非空的胜出，后续跳过。

    适用: 上层想"只要有个数据源能拿到就行"。
    注意: StockInfo 有 name/industry 字段，可能有 name 来自 provider A、
          industry 来自 provider B。可自定义 `combine()` 逻辑。
    """
    def __init__(self, providers: list[StockInfoProvider]):
        self.providers = providers

    def fetch_all(self) -> tuple[list[StockInfo], dict]:
        """尝试每个 provider.fetch_all()，第一个非空胜出。

        Returns:
            (items, stats)  stats={"source": <provider name>, "count": int}
        """
        for p in self.providers:
            try:
                items = p.fetch_all()
                if items:
                    logger.info(
                        "StockInfoChain: %s.fetch_all() succeeded with %d items",
                        p.name, len(items),
                    )
                    return items, {"source": p.name, "count": len(items)}
            except Exception as e:
                logger.warning(
                    "StockInfoChain: %s.fetch_all() failed: %s",
                    p.name, str(e)[:120],
                )
                continue
        logger.warning("StockInfoChain: all providers empty/failed")
        return [], {"source": "none", "count": 0}

    def fetch_one(self, code: str) -> StockInfo | None:
        for p in self.providers:
            try:
                r = p.fetch_one(code)
                if r:
                    return r
            except Exception as e:
                logger.warning(
                    "StockInfoChain: %s.fetch_one(%s) failed: %s",
                    p.name, code, str(e)[:120],
                )
                continue
        return None


class KLineChain:
    """K 线拉取的 fallback 链"""
    def __init__(self, providers: list[KLineProvider]):
        self.providers = providers

    def fetch(self, code: str, days: int = 252) -> tuple[list[KLine] | None, str]:
        """返回 (records, source_name)。失败时 records=None。"""
        for p in self.providers:
            try:
                r = p.fetch(code, days)
                if r:
                    return (r, p.name)
            except Exception as e:
                logger.warning(
                    "KLineChain: %s.fetch(%s, %d) failed: %s",
                    p.name, code, days, str(e)[:120],
                )
                continue
        return (None, "none")
