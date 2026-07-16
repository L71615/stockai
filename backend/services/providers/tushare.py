"""Tushare MCP Provider — 通过 tushare_adapter._call_mcp 调 MCP 协议

本机网络封锁风险: Tushare MCP 在某些机器上不可达，所以它只是 Chain 的"主"层，
按顺序回退。
"""
import logging
from .base import StockInfo, KLine

logger = logging.getLogger(__name__)


class TushareStockInfoProvider:
    """全市场代码+名+行业一次性拉取 (走 stock_basic MCP 接口)"""
    name = "tushare"

    def fetch_all(self) -> list[StockInfo]:
        from services.tushare_adapter import _call_mcp
        items = _call_mcp("stock_basic", {
            "exchange": "", "list_status": "L",
            "fields": "ts_code,name,industry,list_date",
        }, timeout=30)
        out = []
        for it in items or []:
            ts_code = it.get("ts_code", "")
            if "." not in ts_code:
                continue
            code = ts_code.split(".")[0]
            name = (it.get("name") or "").strip()
            industry = (it.get("industry") or "").strip()
            if not name:
                continue
            out.append(StockInfo(
                code=code, name=name, industry=industry,
                list_date=it.get("list_date") or "",
            ))
        return out

    def fetch_one(self, code: str) -> StockInfo | None:
        items = self.fetch_all()
        for it in items:
            if it.code == code:
                return it
        return None
