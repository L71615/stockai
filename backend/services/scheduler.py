"""StockAI — 后台定时任务（DCA 邮件提醒 / 止损检查 / Futu 同步）"""

import logging
import threading
import time
from datetime import datetime, timedelta

from database import query_all, execute
from services.futu_sync_service import run_intraday_sync, run_nightly_sync

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
