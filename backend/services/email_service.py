"""StockAI — SMTP 邮件发送与配置管理"""

import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
from database import query_one, execute

CYCLE_LABELS = {"daily": "每日", "weekly": "每周", "biweekly": "双周", "monthly": "每月"}


def _smtp_config() -> dict:
    """获取 SMTP 配置：优先数据库 settings 表，fallback 到环境变量"""
    row = query_one("SELECT value FROM settings WHERE key = 'smtp'")
    if row:
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "host": SMTP_HOST,
        "port": SMTP_PORT,
        "user": SMTP_USER,
        "password": SMTP_PASSWORD,
    }


def get_smtp_settings() -> dict | None:
    """返回当前 SMTP 配置（密码脱敏），未配置返回 None"""
    cfg = _smtp_config()
    if not cfg.get("host") or not cfg.get("user"):
        return None
    return {
        "host": cfg["host"],
        "port": cfg.get("port", 465),
        "user": cfg["user"],
        "password_set": bool(cfg.get("password")),
    }


def save_smtp_settings(host: str, port: int, user: str, password: str) -> None:
    """保存 SMTP 配置到数据库"""
    data = json.dumps({"host": host, "port": port, "user": user, "password": password})
    execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('smtp', ?)", (data,))


def test_smtp_connection(host: str, port: int, user: str, password: str) -> tuple[bool, str]:
    """测试 SMTP 连接，返回 (成功, 错误信息)"""
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        server.login(user, password)
        server.quit()
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "认证失败，请检查邮箱地址和授权码"
    except smtplib.SMTPConnectError:
        return False, "连接失败，请检查服务器地址和端口"
    except Exception as e:
        return False, f"发送失败: {str(e)[:100]}"


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    """发送纯文本邮件，返回 (成功, 错误信息)"""
    cfg = _smtp_config()
    if not cfg.get("host") or not cfg.get("user") or not cfg.get("password"):
        return False, "SMTP 未配置"

    msg = MIMEMultipart()
    msg["From"] = cfg["user"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        port = cfg.get("port", 465)
        if port == 465:
            server = smtplib.SMTP_SSL(cfg["host"], port, timeout=10)
        else:
            server = smtplib.SMTP(cfg["host"], port, timeout=10)
            server.starttls()
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["user"], [to], msg.as_string())
        server.quit()
        return True, ""
    except Exception as e:
        return False, str(e)[:200]


def send_dca_reminder(email: str, plan: dict) -> bool:
    """发送单条 DCA 定投提醒邮件"""
    name = plan.get("stock_name") or plan.get("stock_code", "")
    code = plan.get("stock_code", "")
    amount = plan.get("amount", 0)
    date_str = plan.get("next_deduction", "")
    cycle = plan.get("cycle", "")
    cycle_label = CYCLE_LABELS.get(cycle, cycle)

    subject = f"[StockAI] 定投提醒 - {name}({code})"
    body = (
        f"{name}（{code}）定投扣款日将至：\n"
        f"  扣款日期：{date_str}\n"
        f"  定投金额：¥{amount:,.2f}\n"
        f"  定投周期：{cycle_label}\n"
        f"\n请确保账户资金充足。\n"
        f"\n---\nStockAI 自动提醒"
    )

    ok, err = send_email(email, subject, body)
    return ok
