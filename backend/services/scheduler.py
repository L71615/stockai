"""StockAI — 后台定时任务（DCA 邮件提醒）"""

import logging
import threading
import time
from datetime import datetime, timedelta

from database import query_all, query_one, execute

logger = logging.getLogger("stockai")


def _check_and_remind():
    """检查所有活跃 DCA 计划，对即将到期的发送提醒"""
    from services.email_service import get_smtp_settings, send_dca_reminder

    smtp = get_smtp_settings()
    if not smtp:
        return  # SMTP 未配置，静默跳过

    # 查 user_id=1 的邮箱
    user = query_one("SELECT email FROM users WHERE id = 1")
    if not user or not user.get("email"):
        return

    email = user["email"]
    now = datetime.now()
    cutoff = (now + timedelta(hours=24)).strftime("%Y-%m-%d")

    plans = query_all(
        """SELECT * FROM dca_plans
           WHERE user_id = 1 AND active = 1
             AND next_deduction IS NOT NULL
             AND next_deduction <= ?
             AND (last_reminded IS NULL OR last_reminded = '' OR last_reminded != next_deduction)""",
        (cutoff,),
    )

    for plan in plans:
        ok = send_dca_reminder(email, plan)
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
    """检查持仓止损触发，推送通知"""
    from services.notify_service import send_notification

    uid = 1
    holdings = query_all(
        "SELECT * FROM holdings WHERE user_id = ? AND quantity > 0 AND stop_loss_price IS NOT NULL",
        (uid,),
    )
    if not holdings:
        return

    from services.utils import get_market
    from services.akshare_adapter import get_batch_quotes

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
