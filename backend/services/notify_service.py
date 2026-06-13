"""通知推送服务 — 企业微信 / Telegram / 邮件

从 daily_stock_analysis 开源项目提取核心发送逻辑，精简为一文件三渠道。
挂载点: watchdog_service（价格异动）、AI 盯盘简报、选股结果

配置方式: settings 表或环境变量（优先级: settings > env）
"""

import json
import os
import re
import smtplib
import time
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 配置加载
# ═══════════════════════════════════════════════════════════

def _get_config() -> dict:
    """从 settings 表 + 环境变量 加载通知配置"""
    cfg = {
        # 企业微信
        "wechat_webhook_url": os.getenv("WECHAT_WEBHOOK_URL", ""),
        "wechat_msg_type": os.getenv("WECHAT_MSG_TYPE", "markdown"),  # markdown | text
        # Telegram
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        # 邮件
        "email_sender": os.getenv("EMAIL_SENDER", ""),
        "email_password": os.getenv("EMAIL_PASSWORD", ""),
        "email_receiver": os.getenv("EMAIL_RECEIVER", ""),  # 逗号分隔
        # 通用
        "notify_enabled": os.getenv("NOTIFY_ENABLED", "false").lower() == "true",
    }
    # settings 表覆盖（如果存在）
    try:
        from database import query_one
        row = query_one("SELECT value FROM settings WHERE key = 'notify_config'")
        if row and row.get("value"):
            saved = json.loads(row["value"])
            if isinstance(saved, dict):
                cfg.update(saved)
    except Exception:
        pass
    return cfg


# ═══════════════════════════════════════════════════════════
# 企业微信 Webhook
# ═══════════════════════════════════════════════════════════

def _split_long_message(text: str, max_bytes: int = 4000) -> list[str]:
    """将长消息按字节数分割（企业微信限制 4096 字节）"""
    chunks = []
    current = ""
    for line in text.split("\n"):
        trial = current + ("\n" if current else "") + line
        if len(trial.encode("utf-8")) <= max_bytes:
            current = trial
        else:
            if current:
                chunks.append(current)
            current = line if len(line.encode("utf-8")) <= max_bytes else line[:max_bytes // 3]
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


def _send_wechat(markdown: str, cfg: dict) -> bool:
    """发送到企业微信 Webhook"""
    url = cfg.get("wechat_webhook_url", "")
    if not url:
        return False
    msg_type = cfg.get("wechat_msg_type", "markdown")

    chunks = _split_long_message(markdown)
    for i, chunk in enumerate(chunks):
        prefix = f"> 第 {i + 1}/{len(chunks)} 部分\n\n" if len(chunks) > 1 else ""
        if msg_type == "markdown":
            payload = {"msgtype": "markdown", "markdown": {"content": prefix + chunk}}
        else:
            # text 模式：去 markdown 标记
            plain = re.sub(r"[*#>`_~]", "", prefix + chunk)
            payload = {"msgtype": "text", "text": {"content": plain}}

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200 or resp.json().get("errcode", -1) != 0:
                logger.warning(f"企业微信发送失败: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.warning(f"企业微信发送异常: {e}")
            return False
    return True


# ═══════════════════════════════════════════════════════════
# Telegram Bot
# ═══════════════════════════════════════════════════════════

def _convert_md_to_telegram(text: str) -> str:
    """Markdown → Telegram 兼容格式"""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # 去标题
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)               # **bold** → *bold*
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)               # 去代码块
    return text


def _send_telegram(markdown: str, cfg: dict) -> bool:
    """发送到 Telegram Bot"""
    token = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    if not token or not chat_id:
        return False

    tg_md = _convert_md_to_telegram(markdown)
    chunks = _split_long_message(tg_md, 3800)

    for chunk in chunks:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=10,
            )
            if resp.status_code != 200:
                # 回退纯文本
                requests.get(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk},
                    timeout=10,
                )
        except Exception as e:
            logger.warning(f"Telegram 发送异常: {e}")
            return False
    return True


# ═══════════════════════════════════════════════════════════
# 邮件 (SMTP)
# ═══════════════════════════════════════════════════════════

def _get_smtp_config(sender: str) -> tuple[str, int, bool]:
    """根据发件人邮箱自动识别 SMTP 服务器"""
    if "@qq.com" in sender or "@foxmail.com" in sender:
        return ("smtp.qq.com", 587, True)
    if "@163.com" in sender:
        return ("smtp.163.com", 465, True)
    if "@gmail.com" in sender:
        return ("smtp.gmail.com", 587, True)
    if "@outlook.com" in sender or "@hotmail.com" in sender:
        return ("smtp-mail.outlook.com", 587, True)
    return ("smtp.qq.com", 587, True)  # 默认 QQ 邮箱


def _simple_md_to_html(markdown: str) -> str:
    """极简 Markdown → HTML（不依赖 markdown2 库）"""
    html = markdown
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    html = html.replace("\n\n", "</p><p>")
    html = html.replace("\n", "<br>")
    return f'<html><body style="font-family: sans-serif;"><p>{html}</p></body></html>'


def _send_email(markdown: str, cfg: dict) -> bool:
    """发送邮件"""
    sender = cfg.get("email_sender", "")
    password = cfg.get("email_password", "")
    receivers_str = cfg.get("email_receiver", sender)  # 默认发给自己
    if not sender or not password:
        return False

    receivers = [r.strip() for r in receivers_str.split(",") if r.strip()]

    subject = "StockAI 通知"
    # 从 markdown 首行提取标题
    first_line = markdown.strip().split("\n")[0]
    if first_line.startswith("#"):
        subject = first_line.lstrip("# ")

    html_body = _simple_md_to_html(markdown)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg.attach(MIMEText(markdown, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    host, port, use_tls = _get_smtp_config(sender)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receivers, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.warning(f"邮件发送失败: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════

def send_notification(markdown: str, title: str = "") -> dict:
    """向所有已配置的渠道发送通知

    Args:
        markdown: Markdown 格式的消息
        title:   消息标题（邮件主题 / Telegram 首行加粗）

    Returns:
        {wechat: bool, telegram: bool, email: bool}
    """
    cfg = _get_config()
    if not cfg.get("notify_enabled", False):
        return {"sent": False, "reason": "通知功能未启用 (NOTIFY_ENABLED=false)"}

    content = markdown
    if title:
        content = f"**{title}**\n\n{markdown}"

    start = time.time()
    results = {
        "wechat": _send_wechat(content, cfg),
        "telegram": _send_telegram(content, cfg),
        "email": _send_email(content, cfg),
    }
    elapsed = (time.time() - start) * 1000

    success = any(results.values())
    logger.info(f"通知发送完成 ({(elapsed):.0f}ms): {results}")
    return {"sent": success, "channels": results}


def send_alert(stock_code: str, stock_name: str, alert_msg: str,
               price: float = 0, change_pct: float = 0) -> dict:
    """发送价格异动预警（格式化 Markdown）

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        alert_msg: 异动描述
        price: 当前价格
        change_pct: 涨跌幅
    """
    emoji = "🔴" if change_pct < 0 else "🟢"
    direction = "跌" if change_pct < 0 else "涨"

    markdown = (
        f"## {emoji} 异动预警\n\n"
        f"**{stock_code}** {stock_name}\n\n"
        f"- 现价: ¥ {price:.2f}\n"
        f"- 涨跌: {change_pct:+.2f}% {direction}\n"
        f"- 详情: {alert_msg}\n\n"
        f"---\n"
        f"⏰ {time.strftime('%Y-%m-%d %H:%M')} · StockAI"
    )
    return send_notification(markdown, title=f"盯盘预警 — {stock_name}")


def send_briefing(briefing: str) -> dict:
    """发送 AI 盯盘简报"""
    markdown = (
        f"{briefing}\n\n"
        f"---\n"
        f"⏰ {time.strftime('%Y-%m-%d %H:%M')} · StockAI 盯盘"
    )
    return send_notification(markdown, title="AI 盯盘简报")


def send_screener_result(candidates: list[dict], market_state: str = "") -> dict:
    """发送选股结果"""
    lines = [f"## 📊 AI 选股结果 ({market_state})", ""]
    for i, c in enumerate(candidates[:5], 1):
        name = c.get("name", "")
        code = c.get("code", "")
        score = c.get("score", 0)
        lines.append(f"{i}. **{code}** {name} — 得分 {score:+.4f}")
    lines.append("")
    lines.append(f"共 {len(candidates)} 只候选 · StockAI")
    return send_notification("\n".join(lines), title="AI 选股结果")


def is_configured() -> bool:
    """检查是否有渠道已配置"""
    cfg = _get_config()
    return bool(cfg.get("wechat_webhook_url") or
                (cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id")) or
                (cfg.get("email_sender") and cfg.get("email_password")))
