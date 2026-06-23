"""AI 盯盘服务：监控候选股票的价格异动、新闻舆情、技术面变化

功能:
  1. 每日自动检测盯盘列表中的股票
  2. 价格异动检测（涨跌幅阈值、成交量异常）
  3. 技术面变化追踪（金叉/死叉/突破）
  4. AI 生成每日简报
  5. 严重异动邮件提醒

集成:
  - services.stocks: 实时行情
  - services.technical: 技术指标
  - services.ai_service: AI 生成简报
  - services.email_service: 邮件提醒
  - services.scheduler: 定时任务
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from database import query_all, query_one, execute, execute_many

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 盯盘检查
# ═══════════════════════════════════════════════════════════

def check_single_stock(code: str, name: str = "", user_id: int = 1) -> dict:
    """检查单只股票的今日状态

    Returns:
        {
            code, name, price, change_pct,
            alerts: [{type, severity, message}],
            technical_signals: [str],
            volume_anomaly: bool,
        }
    """
    from services.technical import fetch_kline, get_indicators as calc_indicators
    from services.utils import get_market, detect_asset_type

    mkt = get_market(code)
    result = {
        "code": code,
        "name": name,
        "price": None,
        "change_pct": None,
        "alerts": [],
        "technical_signals": [],
        "volume_anomaly": False,
    }

    # 1. 实时行情
    try:
        from routers.stocks import _cached_quote
        quote = _cached_quote(code, mkt)
        if "error" not in quote:
            result["price"] = quote.get("price")
            result["name"] = result["name"] or quote.get("name", "")
            result["change_pct"] = quote.get("change_pct")
            result["volume"] = quote.get("volume")
    except Exception as e:
        logger.warning(f"获取 {code} 行情失败: {e}")
        return result

    price = result["price"]
    change_pct = result.get("change_pct")

    # 2. 价格异动检测
    if change_pct is not None:
        if change_pct >= 5:
            result["alerts"].append({
                "type": "price_surge",
                "severity": "high",
                "message": f"大涨 {change_pct:+.2f}%，注意追高风险",
            })
        elif change_pct >= 3:
            result["alerts"].append({
                "type": "price_up",
                "severity": "medium",
                "message": f"上涨 {change_pct:+.2f}%",
            })
        elif change_pct <= -5:
            result["alerts"].append({
                "type": "price_drop",
                "severity": "high",
                "message": f"大跌 {change_pct:+.2f}%，关注是否出现买点",
            })
        elif change_pct <= -3:
            result["alerts"].append({
                "type": "price_down",
                "severity": "medium",
                "message": f"下跌 {change_pct:+.2f}%",
            })

    # 3. 技术面信号
    try:
        indicators = calc_indicators(code, mkt, days=120)
        sig = indicators.get("signal", "")
        if sig:
            result["technical_signals"].append(sig)

        # MACD 金叉/死叉
        macd = indicators.get("MACD", {})
        dif = macd.get("DIF", [])
        dea = macd.get("DEA", [])
        if dif and dea and len(dif) >= 2 and len(dea) >= 2:
            if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
                result["technical_signals"].append("MACD 金叉 ↑")
                result["alerts"].append({
                    "type": "macd_golden_cross",
                    "severity": "medium",
                    "message": "MACD 金叉形成，短期看涨信号",
                })
            elif dif[-2] >= dea[-2] and dif[-1] < dea[-1]:
                result["technical_signals"].append("MACD 死叉 ↓")

        # RSI
        rsi = indicators.get("RSI")
        if rsi is not None:
            if rsi < 20:
                result["technical_signals"].append(f"RSI 极度超卖 ({rsi})")
                result["alerts"].append({
                    "type": "rsi_oversold",
                    "severity": "medium",
                    "message": f"RSI={rsi} 极度超卖，反弹概率较高",
                })
            elif rsi > 80:
                result["technical_signals"].append(f"RSI 极度超买 ({rsi})")
                result["alerts"].append({
                    "type": "rsi_overbought",
                    "severity": "medium",
                    "message": f"RSI={rsi} 极度超买，回调风险增加",
                })
    except Exception as e:
        logger.warning(f"技术指标计算失败 {code}: {e}")

    # 4. 成交量异动
    try:
        kline = fetch_kline(code, mkt, days=30)
        vols = kline.get("volumes", [])
        if vols and len(vols) >= 10:
            recent_vol = sum(vols[-5:]) / 5
            hist_vol = sum(vols[:-5]) / max(len(vols) - 5, 1)
            if hist_vol > 0 and recent_vol > hist_vol * 2:
                result["volume_anomaly"] = True
                result["alerts"].append({
                    "type": "volume_spike",
                    "severity": "medium",
                    "message": f"成交量异常放大（{recent_vol / hist_vol:.1f}x 均量）",
                })
    except Exception:
        logger.warning("watchdog: 成交量异动检测失败 (%s)", code, exc_info=True)

    return result


def check_watchlist(user_id: int = 1) -> dict:
    """检查盯盘列表中所有股票的状态

    Returns:
        {
            checked_at: str,
            stocks: [{code, name, price, change_pct, alerts, technical_signals}],
            summary: {total, alert_count, high_severity_count},
        }
    """
    items = query_all(
        "SELECT * FROM screener_watchlist WHERE user_id = ? AND status = 'watching' ORDER BY added_at DESC",
        (user_id,),
    )

    if not items:
        return {"checked_at": datetime.now().isoformat(), "stocks": [], "summary": {"total": 0, "alert_count": 0, "high_severity_count": 0}}

    stocks = []
    alert_count = 0
    high_count = 0

    for item in items:
        result = check_single_stock(item["stock_code"], item.get("stock_name", ""), user_id)
        stocks.append(result)
        alert_count += len(result["alerts"])
        high_count += sum(1 for a in result["alerts"] if a["severity"] == "high")

        # 保存检查记录
        if result["alerts"]:
            from database import execute
            execute(
                """INSERT INTO screener_alerts (user_id, stock_code, stock_name, alert_type, severity, message, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
                (user_id, item["stock_code"], result["name"],
                 result["alerts"][0]["type"] if result["alerts"] else "",
                 result["alerts"][0]["severity"] if result["alerts"] else "low",
                 json_dumps_zh(result["alerts"])),
            )

    # 通知推送：high 级别异动自动发送
    if high_count > 0:
        try:
            from services.notify_service import send_notification
            high_alerts = []
            for s in stocks:
                for a in s.get("alerts", []):
                    if a.get("severity") == "high":
                        high_alerts.append(
                            f"- **{s['name']}** ({s['code']}) @ ¥{s.get('price', 0):.2f}: {a.get('message', '')}"
                        )
            if high_alerts:
                send_notification(
                    "\n".join(high_alerts),
                    title=f"盯盘异动 — {high_count} 条高级预警",
                )
        except Exception:
            logger.warning("watchdog: 高级预警通知推送失败", exc_info=True)

    return {
        "checked_at": datetime.now().isoformat(),
        "stocks": stocks,
        "summary": {
            "total": len(stocks),
            "alert_count": alert_count,
            "high_severity_count": high_count,
        },
    }


def json_dumps_zh(alerts: list[dict]) -> str:
    """alerts 列表转 JSON 字符串"""
    import json
    return json.dumps(alerts, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# AI 盯盘简报
# ═══════════════════════════════════════════════════════════

async def generate_daily_briefing(user_id: int = 1, provider: str = "") -> str:
    """AI 生成当前盯盘股票的每日简报

    Args:
        user_id: 用户ID
        provider: AI供应商

    Returns:
        AI 生成的简报文本（Markdown格式）
    """
    # 先跑一遍检查
    data = check_watchlist(user_id)
    if not data["stocks"]:
        return "📭 盯盘列表为空，请先添加候选股票。"

    # 构建上下文
    stocks_text = ""
    for s in data["stocks"]:
        alerts_text = "; ".join(a["message"] for a in s["alerts"]) if s["alerts"] else "无异常"
        signals_text = ", ".join(s["technical_signals"]) if s["technical_signals"] else "无"
        stocks_text += (
            f"- {s['code']} {s['name']}: 现价 {s['price']}, "
            f"涨跌幅 {s.get('change_pct', 'N/A')}%\n"
            f"  异动: {alerts_text}\n"
            f"  技术信号: {signals_text}\n"
        )

    prompt = f"""你是一位经验丰富的A股分析师。以下是今日盯盘股票的实时状态，请生成一份简短的盯盘简报：

{stocks_text}

要求：
1. 用简洁的中文，适合手机阅读
2. 格式：先总览（1-2句整体判断），再逐只点评（每只1-2句）
3. 对出现"high"级别的异动重点提示
4. 给出可操作的建议（如：继续观察/准备买入/考虑卖出/加观察仓）
5. 不要长篇大论，控制在200字以内
6. 语气专业但不生硬"""

    try:
        from services.ai_service import ai_chat
        briefing = await ai_chat(
            prompt,
            function="watchdog",
            provider=provider,
            system_prompt="你是专业A股分析师。你的回复简洁、专业、可操作。用中文回复。",
        )
        return briefing.strip()
    except Exception as e:
        logger.warning(f"AI 简报生成失败: {e}")
        return f"⚠️ AI 简报生成失败: {e}\n\n原始数据:\n{stocks_text}"


# ═══════════════════════════════════════════════════════════
# 盯盘列表管理
# ═══════════════════════════════════════════════════════════

def add_to_watchlist(code: str, name: str = "", user_id: int = 1,
                     reason: str = "", score: float = None,
                     backtest_strategy: str = "",
                     backtest_sharpe: float = None) -> dict:
    """添加股票到盯盘列表

    Args:
        code: 股票代码
        name: 股票名称
        user_id: 用户ID
        reason: 添加原因（AI推荐理由）
        score: 多因子得分
        backtest_strategy: 回测通过的最佳策略
        backtest_sharpe: 回测夏普比率
    """
    from services.utils import get_market, detect_asset_type

    mkt = get_market(code)
    at = detect_asset_type(code)

    # 检查是否已存在
    existing = query_one(
        "SELECT id FROM screener_watchlist WHERE user_id = ? AND stock_code = ?",
        (user_id, code),
    )
    if existing:
        # 更新
        execute(
            """UPDATE screener_watchlist SET status = 'watching',
               reason = ?, score = ?, backtest_strategy = ?, backtest_sharpe = ?,
               updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (reason, score, backtest_strategy, backtest_sharpe, existing["id"]),
        )
        return {"added": False, "code": code, "message": f"{code} 已在盯盘列表中，已更新"}

    # 新增
    result = execute(
        """INSERT INTO screener_watchlist
           (user_id, stock_code, stock_name, market, asset_type, status,
            reason, score, backtest_strategy, backtest_sharpe)
           VALUES (?, ?, ?, ?, ?, 'watching', ?, ?, ?, ?)""",
        (user_id, code, name, mkt, at, reason, score, backtest_strategy, backtest_sharpe),
    )
    return {"added": True, "code": code, "id": result["lastrowid"], "message": f"{code} {name} 已加入盯盘"}


def remove_from_watchlist(code: str, user_id: int = 1) -> dict:
    """从盯盘列表移除（软删除，标记为 archived）"""
    execute(
        "UPDATE screener_watchlist SET status = 'archived', updated_at = datetime('now','localtime') WHERE user_id = ? AND stock_code = ?",
        (user_id, code),
    )
    return {"removed": True, "code": code}


def get_watchlist(user_id: int = 1) -> list[dict]:
    """获取当前盯盘列表"""
    return query_all(
        "SELECT * FROM screener_watchlist WHERE user_id = ? AND status = 'watching' ORDER BY added_at DESC",
        (user_id,),
    )


def get_watch_history(user_id: int = 1, limit: int = 50) -> list[dict]:
    """获取盯盘历史（含已归档的）"""
    return query_all(
        "SELECT * FROM screener_watchlist WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
        (user_id, limit),
    )


# ═══════════════════════════════════════════════════════════
# 定时任务
# ═══════════════════════════════════════════════════════════

def scheduled_watchdog_check():
    """定时盯盘检查（由 scheduler 调用）"""
    now = datetime.now()
    # 只在交易日 9:00-15:00 检查
    if now.weekday() >= 5:
        logger.info("[Watchdog] 非交易日，跳过盯盘检查")
        return

    if now.hour < 9 or now.hour > 15:
        logger.info(f"[Watchdog] 非交易时间 ({now.strftime('%H:%M')})，跳过盯盘检查")
        return

    logger.info(f"[Watchdog] 开始盯盘检查 {now.strftime('%Y-%m-%d %H:%M')}")
    result = check_watchlist()

    high_alerts = []
    for s in result["stocks"]:
        for a in s["alerts"]:
            if a["severity"] == "high":
                high_alerts.append(f"{s['code']} {s['name']}: {a['message']}")

    if high_alerts:
        try:
            from services.email_service import send_alert_email
            subject = f"⚠️ StockAI 盯盘预警 — {now.strftime('%m-%d %H:%M')}"
            body = "以下股票出现重要异动：\n\n" + "\n".join(high_alerts)
            send_alert_email(subject, body)
        except Exception as e:
            logger.warning(f"盯盘邮件发送失败: {e}")

    logger.info(f"[Watchdog] 盯盘检查完成: {result['summary']}")
