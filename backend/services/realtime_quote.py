"""实时行情源 — v5.0-alpha M1

数据源:
  - 盘中 9:30-15:00 + 午休 11:30-13:00: 腾讯免费 API (https://qt.gtimg.cn)
  - 盘后 / 隔夜 / 周末: 同 API 返回收盘价 (天然 15 分钟延迟等价)

设计:
  - 单例 RealtimeQuoteService — 全进程一份 quote 缓存
  - subscribe() — 实时推送 callback(用于前端 WebSocket)
  - get_snapshot() — 一次性取快照(用于 REST API)
  - start() — 后台线程,5s 拉一次
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ── 公共类型 ──────────────────────────────────────────


@dataclass
class Quote:
    """实时行情 — 腾讯 API 标准化后的字段"""

    code: str
    name: str
    price: float | None = None
    yesterday_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    amount: float | None = None
    change: float | None = None
    change_pct: float | None = None
    timestamp: float = field(default_factory=time.time)
    source: str = "tencent"

    def to_dict(self) -> dict:
        return asdict(self)


# ── 交易时段判断 ──────────────────────────────────────


def is_trading_hours(ts: datetime | None = None) -> bool:
    """A 股交易时段判断 — 工作日 9:30-11:30 + 13:00-15:00

    注: 周末全天 False, 法定节假日由 trading_calendar.is_trading_day() 进一步校验
    (本函数只判断时段, 不判断日期)
    """
    ts = ts or datetime.now()
    if ts.weekday() >= 5:  # 周六周日
        return False
    t = ts.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))


def is_trading_day(ts: datetime | None = None) -> bool:
    """A 股交易日 — 工作日 + 排除法定节假日

    v5.0-alpha 简化: 只判断工作日。节假日校验依赖 trading_calendar(留 beta)。
    """
    ts = ts or datetime.now()
    return ts.weekday() < 5


# ── 主服务类 ──────────────────────────────────────────


class RealtimeQuoteService:
    """单例实时行情服务

    用法:
        service = get_quote_service()
        # REST API:
        quotes = service.get_snapshot(['000725', '600519'])
        # WebSocket subscribe:
        service.subscribe(['000725'], callback_fn)
        # 后台启动:
        service.start()
    """

    _instance: Optional["RealtimeQuoteService"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._quotes: dict[str, Quote] = {}
                    cls._instance._subscribers: list[Callable[[Quote], None]] = []
                    cls._instance._running = False
                    cls._instance._thread: threading.Thread | None = None
                    cls._instance._loop_thread: threading.Thread | None = None
        return cls._instance

    def subscribe(self, callback: Callable[[Quote], None]) -> None:
        """注册 quote 推送 callback — 新 quote 到来时触发"""
        with self._lock:
            self._subscribers.append(callback)

    def get_snapshot(self, codes: list[str]) -> list[Quote]:
        """取当前缓存的所有 quote(空 codes 返回空列表)"""
        if not codes:
            return []
        with self._lock:
            return [self._quotes[c] for c in codes if c in self._quotes]

    def get_all_codes(self) -> list[str]:
        """所有缓存的 codes — 给 WebSocket /api/realtime/watchlist 用"""
        with self._lock:
            return list(self._quotes.keys())

    async def _poll_once(self, codes: list[str]) -> list[Quote]:
        """单次拉取 codes 的 quote — 用 akshare_adapter.get_batch_quotes"""
        from services.akshare_adapter import get_batch_quotes

        if not codes:
            return []

        try:
            # 静默调用 — 失败时 logger 已记录,不抛
            raw = get_batch_quotes(codes)
        except Exception as e:
            logger.warning("realtime_quote: 拉取失败: %s", e)
            return []

        out: list[Quote] = []
        for code, data in raw.items():
            q = Quote(
                code=code,
                name=data.get("name", code),
                price=data.get("price"),
                yesterday_close=data.get("yesterday_close"),
                open=data.get("open"),
                high=data.get("high"),
                low=data.get("low"),
                volume=data.get("volume"),
                amount=data.get("amount"),
                change=data.get("change"),
                change_pct=data.get("change_pct"),
                timestamp=time.time(),
                source=data.get("source", "tencent"),
            )
            out.append(q)
        return out

    def _update_quotes(self, new_quotes: list[Quote]) -> None:
        """更新缓存 + 推送 subscribers — 加锁"""
        with self._lock:
            for q in new_quotes:
                self._quotes[q.code] = q
            subs = list(self._subscribers)

        # 推送在锁外做,避免 callback 阻塞其他订阅者
        for cb in subs:
            for q in new_quotes:
                try:
                    cb(q)
                except Exception as e:
                    logger.exception("realtime_quote subscriber failed: %s", e)

    async def _loop(self) -> None:
        """主循环 — 每 5s 拉一次所有 codes 的 quote

        拉取范围: 所有 holdings + watchlist 的代码 + cache 中已有的代码
        """
        from database import query_all

        while self._running:
            try:
                # 拉取范围: 持仓 + 自选股
                codes: set[str] = set()
                try:
                    holdings = query_all(
                        "SELECT DISTINCT stock_code FROM holdings WHERE quantity > 0"
                    )
                    codes.update(h["stock_code"] for h in holdings)
                except Exception:
                    pass
                try:
                    watchlist = query_all(
                        "SELECT stock_code FROM watchlist WHERE active = 1"
                    )
                    codes.update(w["stock_code"] for w in watchlist)
                except Exception:
                    pass
                # 加上 cache 里已有的(避免丢掉长期缓存的 code)
                codes.update(self.get_all_codes())

                if codes:
                    quotes = await self._poll_once(list(codes))
                    if quotes:
                        self._update_quotes(quotes)
            except Exception as e:
                logger.exception("realtime_quote loop error: %s", e)

            await asyncio.sleep(5)

    def start(self) -> None:
        """启动后台 polling 循环(幂等 — 重复调用无副作用)"""
        if self._running:
            return
        self._running = True

        def _runner():
            try:
                asyncio.run(self._loop())
            except Exception as e:
                logger.exception("realtime_quote runner crashed: %s", e)
                self._running = False

        self._loop_thread = threading.Thread(target=_runner, daemon=True, name="realtime-quote")
        self._loop_thread.start()
        logger.info("realtime_quote: 启动 (5s 间隔, 盘中用腾讯 API, 盘后返回收盘价)")

    def stop(self) -> None:
        """停止 — 测试 / shutdown 用"""
        self._running = False


# ── 全局入口 ──────────────────────────────────────────


def get_quote_service() -> RealtimeQuoteService:
    """获取单例"""
    return RealtimeQuoteService()