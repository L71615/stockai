"""v4.1 Phase 2A: ETF K 线同步

固定 ETF universe (宽基 + 行业 + 跨境 + 商品), 让 holdings 里 ETF 标的
能查到真实日 K (不再走 stock_zh_index_daily 错误路径).

数据源: akshare.fund_etf_hist_em (后复权 hfq)
Universe: 11 只默认 ETF

调度:
  - run_full_seed(days_back=1250)     # 一次性 5 年 seed
  - run_nightly_etf_sync()            # 每日 17:10 nightly (30 天增量)
"""
from __future__ import annotations

import logging

from services.akshare_adapter import get_etf_kline
from services.base_vendor_sync import BaseVendorSyncService
from database import execute

logger = logging.getLogger(__name__)


# 11 只默认 ETF — 6 宽基 + 5 行业/跨境/商品
DEFAULT_ETFS: list[dict] = [
    {"code": "510300", "name": "沪深300ETF"},
    {"code": "510500", "name": "中证500ETF"},
    {"code": "159915", "name": "创业板ETF"},
    {"code": "510050", "name": "上证50ETF"},
    {"code": "588000", "name": "科创50ETF"},
    {"code": "510880", "name": "红利ETF"},
    {"code": "512880", "name": "证券ETF"},
    {"code": "512760", "name": "半导体ETF"},
    {"code": "512690", "name": "酒ETF"},
    {"code": "518880", "name": "黄金ETF"},
    {"code": "513050", "name": "中概互联ETF"},
]


UPSERT_SQL = """
INSERT INTO etf_kline
  (code, name, trade_date, open, high, low, close, volume)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(code, trade_date) DO UPDATE SET
  open=excluded.open,
  high=excluded.high,
  low=excluded.low,
  close=excluded.close,
  volume=excluded.volume,
  updated_at=CURRENT_TIMESTAMP
"""


class ETFSyncService(BaseVendorSyncService):
    """固定 ETF universe 同步服务."""

    _RUN_TABLE = "etf_sync_runs"
    _ITEM_TABLE = "etf_sync_run_items"
    _TARGET_CODE_COL = "code"
    _ALERT_FOOTER = "ETF"

    def __init__(self, etfs: list[dict] | None = None) -> None:
        self.etfs = DEFAULT_ETFS if etfs is None else etfs

    def load_targets(self) -> list[dict]:
        return list(self.etfs)

    def _fetch_one(self, code: str, days: int) -> int:
        """拉取 + upsert, 返回写入行数."""
        data = get_etf_kline(code, days=days)
        if "error" in data:
            raise RuntimeError(data["error"])
        name = next(
            (x["name"] for x in self.etfs if x["code"] == code),
            code,
        )
        rows = 0
        for d, o, h, low, c, v in zip(
            data["dates"], data["opens"], data["highs"],
            data["lows"], data["closes"], data["volumes"],
        ):
            execute(UPSERT_SQL, (code, name, d, o, h, low, c, v))
            rows += 1
        return rows


_service = ETFSyncService()


def run_etf_sync(
    *,
    run_type: str = "nightly",
    days_back: int = 1250,
    sleep_seconds: float | None = None,
) -> dict:
    """通用入口."""
    kwargs: dict = {"run_type": run_type, "days_back": days_back}
    if sleep_seconds is not None:
        kwargs["sleep_seconds"] = sleep_seconds
    return _service.run_sync(**kwargs)


def run_full_seed(days_back: int = 1250) -> dict:
    """5 年一次性 seed — 调用方: 部署后 / 新建 dev DB 后."""
    return _service.run_sync(
        run_type="full_seed",
        days_back=days_back,
        sleep_seconds=0.3,
    )


def run_nightly_etf_sync() -> dict:
    """每日晚间增量 — scheduler 17:10 触发."""
    return _service.run_sync(
        run_type="nightly",
        days_back=30,
        sleep_seconds=0.1,
    )
