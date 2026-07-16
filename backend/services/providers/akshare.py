"""Akshare Provider

提供:
    - AkshareStockInfoProvider: 全市场代码+名字 (ak.stock_info_a_code_name, ~14s)
    - AkshareKLineProvider:      单只历史 K 线 (ak.stock_zh_a_hist, ~0.4s/只)
"""
import logging
from .base import StockInfo, KLine

logger = logging.getLogger(__name__)


class AkshareStockInfoProvider:
    name = "akshare"

    def fetch_all(self) -> list[StockInfo]:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        out = []
        for _, row in df[["code", "name"]].iterrows():
            code = str(row["code"]).strip()
            name = str(row["name"] or "").strip()
            if not code or not name:
                continue
            market = "SH" if code.startswith("6") else "SZ"
            out.append(StockInfo(
                code=code, name=name, industry="",
                list_date="",
            ))
        return out

    def fetch_one(self, code: str) -> StockInfo | None:
        # 复用 fetch_all — 全市场拉到再过滤简单可靠，避免单只调用接口变化
        items = self.fetch_all()
        for it in items:
            if it.code == code:
                return it
        return None


class AkshareKLineProvider:
    name = "akshare_kline"

    def fetch(self, code: str, days: int = 252) -> list[KLine] | None:
        try:
            import akshare as ak
        except ImportError:
            return None
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily", adjust="qfq",
                start_date="20240701", end_date="20260713",
            )
        except Exception as e:
            logger.warning("AkshareKLineProvider.fetch(%s) failed: %s", code, str(e)[:120])
            return None
        out = []
        for _, r in df.iterrows():
            d_str = str(r.get("日期", ""))[:10]
            if not d_str or d_str == "NaT":
                continue
            try:
                out.append(KLine(
                    trade_date=d_str,
                    open=float(r.get("开盘", 0) or 0),
                    high=float(r.get("最高", 0) or 0),
                    low=float(r.get("最低", 0) or 0),
                    close=float(r.get("收盘", 0) or 0),
                    volume=float(r.get("成交量", 0) or 0),
                ))
            except (ValueError, TypeError):
                continue
        return out if out else None
