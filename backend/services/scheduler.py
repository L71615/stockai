"""StockAI — 后台定时任务（DCA 邮件提醒）"""

import threading
import time
from datetime import datetime, timedelta

from database import query_all, query_one, execute


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
                pass  # 静默吞掉所有异常，保证线程不挂
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="dca-reminder")
    t.start()
    return t


def _check_and_run_kol_daily():
    """检查是否交易日 16:00-17:00，如果是则执行 KOL 爬取+日报生成"""
    from datetime import datetime

    now = datetime.now()
    # 仅交易日触发（周一到周五）
    if now.weekday() >= 5:
        return
    # 仅 16:00-17:00 触发（收盘后一小时窗口）
    if now.hour != 16:
        return

    try:
        from services.kol_crawler import crawl_all
        from services.kol_service import generate_brief

        # 先爬取
        result = crawl_all(user_id=1)
        if result["total_posts"] > 0:
            # 有新帖子才生成日报
            generate_brief(user_id=1)
    except Exception:
        pass


def start_kol_daily_thread(interval_seconds: int = 1800):
    """启动 KOL 日报后台线程（每 30 分钟检查一次是否到触发时间）"""
    def _loop():
        while True:
            try:
                _check_and_run_kol_daily()
            except Exception:
                pass
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="kol-daily")
    t.start()
    return t
