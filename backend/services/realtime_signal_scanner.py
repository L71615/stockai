"""盘中信号扫描守护线程 — v5.0-alpha M3

- 启动后: 每 5s 扫一次(盘中)
- 触发后: 写 realtime_signal_log(M4 阶段推送给前端)
- 盘后: 不扫描
- 异常: 单轮异常不影响下一轮

v5.0-beta M9 升级:
  - 触发后调 notify_service.send_signal 推送到 wechat/tg/email
  - 5min dedup(同 code+strategy 不重复推)
  - NOTIFY_ENABLED=false 时跳过(复用 notify_service 配置)

通过 main.startup() 中的 start_realtime_signal_scanner_thread() 启动
"""
from __future__ import annotations

import logging
import threading
import time

from database import query_all
from services.realtime_quote import is_trading_hours
from services.realtime_signal import scan_signals
from services.realtime_signal_log import log_signal

logger = logging.getLogger(__name__)

# ── 通知去重(v5.0-beta M9 新增) ──
DEDUP_TTL_SECONDS = 300  # 5min
_dedup_lock = threading.Lock()
_dedup_state: dict[tuple[str, str], float] = {}


def _should_push(stock_code: str, strategy_id: str) -> bool:
    """5min dedup: 同一 (stock_code, strategy_id) 5min 内不重推"""
    key = (stock_code, strategy_id)
    now = time.time()
    with _dedup_lock:
        last_ts = _dedup_state.get(key, 0)
        if now - last_ts < DEDUP_TTL_SECONDS:
            return False
        _dedup_state[key] = now
    return True


def _reset_dedup() -> None:
    """清空 dedup 缓存(测试用)"""
    with _dedup_lock:
        _dedup_state.clear()


# ── 主类 ──


class RealtimeSignalScanner:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._running = False
                    cls._instance._thread = None
        return cls._instance

    def start(
        self,
        enabled_strategies: list[str] | None = None,
        interval_seconds: int = 5,
    ):
        """启动守护线程(单例, 重复调用 no-op)"""
        if self._thread and self._thread.is_alive():
            logger.debug("realtime_signal_scanner: 已在运行, 跳过启动")
            return
        self._running = True
        # 默认策略列表 — 覆盖不同市场状态:
        #  - turtle_s1 / breakout_pullback: 突破类(强势股)
        #  - boll_mean: 回归类(震荡市)
        #  - momentum_leader: 动量类(趋势确认)
        #  - trend_continuation: 趋势中途介入(半山腰)
        #  - gap_reversal: 反转类(超跌反弹)
        #  - rsi_oversold: 弱反转
        strategies = enabled_strategies or [
            "turtle_s1", "breakout_pullback",
            "boll_mean", "momentum_leader",
            "trend_continuation",
            "gap_reversal", "rsi_oversold",
        ]
        self._thread = threading.Thread(
            target=self._loop,
            args=(strategies, interval_seconds),
            daemon=True,
            name="realtime-signal-scanner",
        )
        self._thread.start()
        logger.info(
            "realtime_signal_scanner: 启动 (strategies=%s, interval=%ds)",
            strategies, interval_seconds,
        )

    def stop(self):
        self._running = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── 主循环 ──

    def _loop(self, enabled_strategies: list[str], interval: int):
        while self._running:
            try:
                self._tick(enabled_strategies)
            except Exception as e:
                logger.exception("realtime_signal_scanner 主循环异常: %s", e)
            time.sleep(interval)

    def _tick(self, enabled_strategies: list[str]):
        """单轮扫描 — 非交易时段直接返回"""
        if not is_trading_hours():
            return

        codes = self._candidate_codes()
        if not codes:
            return

        signals = scan_signals(
            enabled_strategies=enabled_strategies,
            candidate_codes=codes,
        )
        for sig in signals:
            # 1) 写 log_signal — 始终执行
            try:
                log_signal(sig)
            except Exception as e:
                logger.warning("realtime_signal_scanner: log_signal 失败: %s", e)

            # 2) 推送给 wechat/tg/email — v5.0-beta M9
            # dedup: 5min 内同 code+strategy 不重推
            if not _should_push(sig.stock_code, sig.strategy_id):
                logger.debug(
                    "realtime_signal_scanner: 5min 内已推过, 跳过 %s %s",
                    sig.stock_code, sig.strategy_id,
                )
                continue

            try:
                from services.notify_service import send_signal
                result = send_signal(sig)
                if not result.get("sent"):
                    logger.debug(
                        "realtime_signal_scanner: 通知未发送 (NOTIFY_ENABLED=false 或无渠道): %s",
                        result,
                    )
            except Exception as e:
                # 推送失败不阻塞 scanner
                logger.warning("realtime_signal_scanner: send_signal 失败: %s", e)

    def _candidate_codes(self) -> list[str]:
        """候选代码 = 持仓(quantity>0) ∪ watchlist"""
        holdings = query_all(
            "SELECT DISTINCT stock_code FROM holdings WHERE quantity > 0"
        )
        watchlist = query_all("SELECT stock_code FROM watchlist")
        return sorted({
            *(h["stock_code"] for h in holdings),
            *(w["stock_code"] for w in watchlist),
        })


# ── 顶层启动函数(给 main.startup 调用) ──


_scanner_started = False
_scanner_lock = threading.Lock()


def start_realtime_signal_scanner_thread():
    """在 FastAPI startup 时调用 — 幂等"""
    global _scanner_started
    with _scanner_lock:
        if _scanner_started:
            return
        _scanner_started = True
    RealtimeSignalScanner().start()