"""Tushare MCP Provider — 通过 tushare_adapter._call_mcp 调 MCP 协议

本机网络封锁风险: Tushare MCP 在某些机器上不可达，所以它只是 Chain 的"主"层，
按顺序回退。
"""
import logging
from datetime import datetime, timedelta
from .base import StockInfo, KLine

logger = logging.getLogger(__name__)


def _ts_code_suffix(code: str) -> str | None:
    """根据股票代码推断 ts_code 后缀 (SH/SZ/BJ)"""
    if not code or len(code) != 6:
        return None
    # 6 开头 (主板/科创板) → SH
    # 0/3 开头 → SZ
    # 4/8 开头 → BJ
    if code.startswith(("60", "68", "90")):
        return "SH"
    if code.startswith(("00", "30", "20")):
        return "SZ"
    if code.startswith(("43", "83", "87", "88")):
        return "BJ"
    return None


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


class TushareKLineProvider:
    """单只股票历史 K 线 (走 daily MCP 接口, 按 ts_code + 时间范围一次拉完)

    优势: 1 次 MCP 调用拉 1 只股票 ~250 个交易日 (~0.4s/只, 走代理后实测)
    劣势: 需要 Tushare MCP 可达 (本机需配代理 127.0.0.1:7897)
    """
    name = "tushare_kline"

    def fetch(self, code: str, days: int = 252) -> list[KLine] | None:
        suffix = _ts_code_suffix(code)
        if not suffix:
            logger.debug("TushareKLine: %s 无法识别市场后缀", code)
            return None

        # 按 days × 1.5 估算日历天数 (考虑周末节假日)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(days * 1.6))
        ts_code = f"{code}.{suffix}"

        try:
            from services.tushare_adapter import _call_mcp
            items = _call_mcp("daily", {
                "ts_code": ts_code,
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d"),
            }, timeout=30)
        except Exception as e:
            logger.warning("TushareKLine: %s MCP 调用失败: %s", code, str(e)[:120])
            return None

        if not items:
            return None

        out = []
        for it in items:
            try:
                td = it.get("trade_date", "")
                # YYYYMMDD → YYYY-MM-DD
                trade_date = f"{td[:4]}-{td[4:6]}-{td[6:8]}" if len(td) == 8 else td
                out.append(KLine(
                    trade_date=trade_date,
                    open=float(it.get("open") or 0),
                    high=float(it.get("high") or 0),
                    low=float(it.get("low") or 0),
                    close=float(it.get("close") or 0),
                    volume=float(it.get("vol") or 0),
                ))
            except (ValueError, TypeError):
                continue
        return out if out else None
