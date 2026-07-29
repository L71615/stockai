"""StockAI — 后台定时任务（DCA 邮件提醒 / 止损检查 / Futu 同步 / T+1 watcher）"""

import logging
import threading
import time
from datetime import datetime, timedelta

from database import query_all, execute, query_one
from services.futu_sync_service import run_intraday_sync, run_nightly_sync
from services.trading_calendar import trading_days_lag_str, is_trading_day

logger = logging.getLogger("stockai")


def _check_and_remind():
    """检查所有活跃 DCA 计划，对即将到期的发送提醒（多用户遍历）"""
    from services.email_service import get_smtp_settings, send_dca_reminder

    smtp = get_smtp_settings()
    if not smtp:
        return

    users = query_all("SELECT id, email FROM users WHERE email IS NOT NULL AND email != ''")
    now = datetime.now()
    cutoff = (now + timedelta(hours=24)).strftime("%Y-%m-%d")

    for user in users:
        plans = query_all(
            """SELECT * FROM dca_plans
               WHERE user_id = ? AND active = 1
                 AND next_deduction IS NOT NULL
                 AND next_deduction <= ?
                 AND (last_reminded IS NULL OR last_reminded = '' OR last_reminded != next_deduction)""",
            (user["id"], cutoff),
        )

        for plan in plans:
            ok = send_dca_reminder(user["email"], plan)
            if ok:
                execute(
                    "UPDATE dca_plans SET last_reminded = ? WHERE id = ?",
                    (plan["next_deduction"], plan["id"]),
                )


def start_dca_reminder_thread(interval_seconds: int = 3600):
    """启动后台 daemon 线程，定期检查 DCA 提醒"""
    def _loop():
        while True:
            try:
                _check_and_remind()
            except Exception:
                logger.warning("scheduler: DCA提醒线程异常", exc_info=True)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="dca-reminder")
    t.start()
    return t


def _check_stop_losses():
    """检查所有用户持仓止损触发，推送通知"""
    from services.notify_service import send_notification
    from services.akshare_adapter import get_batch_quotes

    holdings = query_all(
        "SELECT * FROM holdings WHERE quantity > 0 AND stop_loss_price IS NOT NULL",
    )
    if not holdings:
        return

    codes = [h["stock_code"] for h in holdings]
    try:
        quotes = get_batch_quotes(codes)
    except Exception:
        return

    triggered = []
    for h in holdings:
        q = quotes.get(h["stock_code"])
        if not q or not q.get("price"):
            continue
        price = q["price"]
        sl = h["stop_loss_price"]
        tp = h.get("take_profit_price")
        if sl and price <= sl:
            triggered.append(f"🔴 {h['stock_code']} {h.get('stock_name','')} 触发止损! 当前{price} ≤ 止损{sl}")
        elif tp and price >= tp:
            triggered.append(f"🟢 {h['stock_code']} {h.get('stock_name','')} 触发止盈! 当前{price} ≥ 止盈{tp}")

    if triggered:
        send_notification("\n".join(triggered), title="⚠️ 止损/止盈预警")


def start_stop_loss_thread(interval_seconds: int = 300):
    """每5分钟检查止损（仅交易时段）"""
    def _loop():
        while True:
            try:
                now = datetime.now()
                if now.weekday() < 5 and 9 <= now.hour <= 15:
                    _check_stop_losses()
            except Exception:
                logger.warning("scheduler: 止损检查线程异常", exc_info=True)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="stop-loss-checker")
    t.start()
    return t


def start_futu_intraday_sync_thread(interval_seconds: int = 300, scope: str = "watchlist+holdings"):
    """白天增量同步线程：交易时段定期跑 quote + minute。"""
    def _loop():
        while True:
            try:
                now = datetime.now()
                if now.weekday() < 5 and 9 <= now.hour <= 15:
                    run_intraday_sync(scope=scope)
            except Exception:
                logger.warning("scheduler: Futu intraday 同步线程异常", exc_info=True)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="futu-intraday-sync")
    t.start()
    return t


def start_futu_nightly_sync_thread(run_hour: int = 20, run_minute: int = 5, scope: str = "watchlist+holdings"):
    """夜间补齐线程：每天固定时间跑 nightly。"""
    def _loop():
        last_run = None
        while True:
            try:
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                if now.weekday() < 5 and now.hour == run_hour and now.minute >= run_minute and last_run != today_key:
                    run_nightly_sync(scope=scope)
                    last_run = today_key
            except Exception:
                logger.warning("scheduler: Futu nightly 同步线程异常", exc_info=True)
            time.sleep(60)

    t = threading.Thread(target=_loop, daemon=True, name="futu-nightly-sync")
    t.start()
    return t


def start_memory_resolution_thread(run_hour: int = 15, run_minute: int = 30):
    """每天收盘后（15:00）检查 pending 交易记忆，生成 AI 反思"""
    def _loop():
        last_run = None
        while True:
            try:
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                if now.weekday() < 5 and now.hour == run_hour and now.minute >= run_minute and last_run != today_key:
                    from services.trading_memory import TradingMemoryLog
                    mem = TradingMemoryLog()
                    resolved = mem.resolve_pending()
                    if resolved:
                        logger.info("scheduler: 已解析 %d 条交易记忆", len(resolved))
                    last_run = today_key
            except Exception:
                logger.warning("scheduler: 记忆解析线程异常", exc_info=True)
            time.sleep(120)  # 每2分钟检查一次

    t = threading.Thread(target=_loop, daemon=True, name="memory-resolution")
    t.start()
    return t


def start_futu_nightly_fundamentals_thread(run_hour: int = 15, run_minute: int = 35):
    """每天收盘后（15:35）同步基本面+板块数据到本地表"""
    def _loop():
        last_run = None
        while True:
            try:
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                if now.weekday() < 5 and now.hour == run_hour and now.minute >= run_minute and last_run != today_key:
                    from services.futu_sync_service import run_nightly_fundamentals
                    result = run_nightly_fundamentals()
                    logger.info("scheduler: 基本面同步完成 — %s 条, 状态=%s",
                                result.get("saved", 0), result.get("status", "?"))
                    last_run = today_key
            except Exception:
                logger.warning("scheduler: 基本面同步异常", exc_info=True)
            time.sleep(300)  # 每5分钟检查一次

    t = threading.Thread(target=_loop, daemon=True, name="futu-fundamentals")
    t.start()
    return t


# ═══════════════════════════════════════════════════════════════
#  v4.1 1A.1 — T+1 watcher 守护线程
# ═══════════════════════════════════════════════════════════════

def _is_a_share_trading_day(d: datetime | None = None) -> bool:
    """v4.1 1A.1: 判断是否 A 股交易日 (用 trading_calendar.is_trading_day)

    akshare 拉不到交易日历时回退到 weekday<5 (已由 trading_calendar 处理).
    """
    d = d or datetime.now()
    try:
        return is_trading_day(d.strftime("%Y-%m-%d"))
    except Exception:
        # 终极 fallback
        return d.weekday() < 5


def _last_pipeline_status() -> str | None:
    """v4.1 1A.1: 查 experiment_runs 最新一条的 status

    返回 'done' / 'partial' / 'failed' / 'running' / None (无记录)
    """
    row = query_one(
        "SELECT status FROM experiment_runs WHERE scope = 'pipeline' "
        "ORDER BY started_at DESC LIMIT 1"
    )
    return row["status"] if row else None


def _update_watcher_health(*, status: str, proposals_processed: int, error: str = "") -> None:
    """v4.1 1A.1: 写 watcher_health 表

    失败不阻塞主流程 (best-effort).
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        # 用 UPSERT 模式: 有就更新, 无就插入
        existing = query_one("SELECT id FROM watcher_health ORDER BY id DESC LIMIT 1")
        if existing:
            execute(
                "UPDATE watcher_health SET last_run_at = ?, last_status = ?, "
                "last_run_proposals = ?, last_error = ? WHERE id = ?",
                (now, status, proposals_processed, error, existing["id"]),
            )
        else:
            execute(
                "INSERT INTO watcher_health (last_run_at, last_status, last_run_proposals, last_error) "
                "VALUES (?, ?, ?, ?)",
                (now, status, proposals_processed, error),
            )
    except Exception as e:
        logger.warning("watcher_health upsert failed: %s", e)


def _check_watcher_health_3day_alert() -> None:
    """v4.1 1A.1: 连续 3 个交易日 watcher 没跑 → 通知

    用 trading_days_lag_str (不是日历日, 避免周末假报警)
    """
    row = query_one("SELECT last_run_at FROM watcher_health ORDER BY id DESC LIMIT 1")
    if not row or not row.get("last_run_at"):
        return  # 从未跑过 — 不告警 (避免冷启动噪音)
    last_run_date = row["last_run_at"][:10]
    try:
        lag = trading_days_lag_str(last_run_date)
    except Exception:
        return
    if lag is not None and lag >= 3:
        try:
            from services.notify_service import send_notification
            send_notification(
                markdown=(
                    f"⚠️ T+1 watcher 已连续 {lag} 个交易日未运行。\n"
                    f"最后运行: {last_run_date}\n"
                    f"请检查 start.bat / 后端进程是否存活。"
                ),
                title="[watcher 健康告警]",
                run_id="watcher_3day_alert",
            )
        except Exception:
            pass


def _t1_watcher_cycle():
    """v4.1 1A.1: 单次 watcher 循环 — 09:30 触发"""
    from services.t1_watcher import process_pending_buys, process_pending_sells
    from services.retrospective_service import run_retrospective_writer

    today = datetime.now().strftime("%Y-%m-%d")

    # 1. 交易日判断 (非交易日直接跳过, 不写 health)
    if not _is_a_share_trading_day():
        logger.info("scheduler: %s 非 A 股交易日, 跳过 watcher", today)
        return

    # 2. partial pipeline fallback: 检查昨夜 pipeline 状态
    last_pipeline = _last_pipeline_status()
    if last_pipeline and last_pipeline != "done":
        logger.warning(
            "scheduler: 昨夜 pipeline status=%s, watcher 跳过 AI-driven pending_buy (仅允许用户手动单)",
            last_pipeline,
        )
        # 仍然跑 sell (用户手动单不受影响); skip buy 全部
        try:
            sell_results = process_pending_sells(today)
            _update_watcher_health(
                status=f"partial_pipeline={last_pipeline}",
                proposals_processed=len(sell_results),
            )
        except Exception as e:
            logger.warning("scheduler: watcher sell 部分失败: %s", e)
            _update_watcher_health(status="partial_sell_failed", proposals_processed=0, error=str(e))
        return

    # 3. 正常情况: 跑 buy + sell + 反事实 writer
    proposals = 0
    try:
        buy_results = process_pending_buys(today)
        proposals += len(buy_results)
    except Exception as e:
        logger.warning("scheduler: watcher buy 失败: %s", e)
        _update_watcher_health(status="buy_failed", proposals_processed=proposals, error=str(e))
        return

    try:
        sell_results = process_pending_sells(today)
        proposals += len(sell_results)
    except Exception as e:
        logger.warning("scheduler: watcher sell 失败: %s", e)
        _update_watcher_health(status="sell_failed", proposals_processed=proposals, error=str(e))
        return

    # 4. 反事实 writer (异步, 不阻塞主流程)
    try:
        run_retrospective_writer(fwd_days=30)
    except Exception as e:
        logger.warning("scheduler: retrospective_writer 失败: %s", e)

    _update_watcher_health(status="ok", proposals_processed=proposals)
    logger.info("scheduler: watcher 完成 — buy/sell 总 %d 提案", proposals)


def start_t1_watcher_thread():
    """v4.1 1A.1: 启动 T+1 watcher 守护线程

    - 09:30 触发 (A股开盘后, 数据稳定)
    - 仅交易日 (用 trading_days_lag_str 判断)
    - partial pipeline fallback (experiment_runs.status != 'done' 时跳过 buy)
    - 写 watcher_health 表, 3 交易日未跑触发 notify
    - 反事实 writer 自动跟跑
    """
    # 启动时立即跑一次健康检查 (3 天未跑告警)
    _check_watcher_health_3day_alert()

    def _loop():
        last_run = None
        while True:
            try:
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                # 09:30-09:35 之间触发一次 / 每天一次
                if (now.hour == 9 and 30 <= now.minute < 35 and last_run != today_key):
                    _t1_watcher_cycle()
                    last_run = today_key
            except Exception:
                logger.warning("scheduler: t1_watcher 线程异常", exc_info=True)
            time.sleep(60)  # 每分钟检查一次

    t = threading.Thread(target=_loop, daemon=True, name="t1-watcher")
    t.start()
    return t
