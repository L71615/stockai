"""v4.1 Phase 2A: 指数 K 线同步

替换 strategy_backtest_service._get_benchmark_curve 的 ETF 代理,提供真实 CSI300 等指数基准.

数据源: akshare.stock_zh_index_daily (零配额, 腾讯 fallback)
Universe: 6 只默认指数 (沪深300 / 中证500 / 创业板 / 上证50 / 中证1000 / 科创50)

调度:
  - run_full_seed(days_back=1250)     # 一次性 5 年 seed
  - run_nightly_index_sync()          # 每日 17:00 nightly (30 天增量)
"""
from __future__ import annotations

import logging

from services.akshare_adapter import get_index_kline
from services.base_vendor_sync import BaseVendorSyncService
from database import execute

logger = logging.getLogger(__name__)


# 6 只默认指数 — ak-share 格式 symbol
DEFAULT_INDICES: list[dict] = [
    {"code": "sh000300", "name": "沪深300"},
    {"code": "sh000905", "name": "中证500"},
    {"code": "sz399006", "name": "创业板指"},
    {"code": "sh000016", "name": "上证50"},
    {"code": "sh000852", "name": "中证1000"},
    {"code": "sh000688", "name": "科创50"},
]


# ON CONFLICT 幂等 upsert — ON CONFLICT 是 SQLite 3.24+ 语法
UPSERT_SQL = """
INSERT INTO index_kline
  (symbol, name, trade_date, open, high, low, close, volume)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(symbol, trade_date) DO UPDATE SET
  open=excluded.open,
  high=excluded.high,
  low=excluded.low,
  close=excluded.close,
  volume=excluded.volume,
  updated_at=CURRENT_TIMESTAMP
"""


class IndexSyncService(BaseVendorSyncService):
    """CSI300 等指数同步服务."""

    _RUN_TABLE = "index_sync_runs"
    _ITEM_TABLE = "index_sync_run_items"
    _TARGET_CODE_COL = "symbol"
    _ALERT_FOOTER = "指数"

    def __init__(self, indices: list[dict] | None = None) -> None:
        self.indices = DEFAULT_INDICES if indices is None else indices

    def load_targets(self) -> list[dict]:
        return list(self.indices)

    def _fetch_one(self, code: str, days: int) -> int:
        """拉取 + upsert, 返回写入行数."""
        data = get_index_kline(code, days=days)
        if "error" in data:
            raise RuntimeError(data["error"])
        name = next(
            (x["name"] for x in self.indices if x["code"] == code),
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


_service = IndexSyncService()


def run_index_sync(
    *,
    run_type: str = "nightly",
    days_back: int = 1250,
    sleep_seconds: float | None = None,
) -> dict:
    """通用入口 — 任何 run_type 都能调."""
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


def run_nightly_index_sync() -> dict:
    """每日晚间增量 — scheduler 17:00 触发, 只拉最近 30 天."""
    return _service.run_sync(
        run_type="nightly",
        days_back=30,
        sleep_seconds=0.1,
    )
