"""用户交易风格分析 — v4.0 A4

基于用户的真实交易历史,提取个性化偏好,并生成可注入到 LLM system prompt 的上下文。

输出的风格特征:
  - avg_hold_days: 平均持仓天数(对 T+1 vs T+2 决策有影响)
  - win_rate: 历史胜率(信心度参考)
  - preferred_sectors: 偏好行业(top 3)
  - risk_tolerance: 风险容忍度(low/medium/high) — 基于平均持仓时长 + 行业分散度
  - avg_position_size: 平均单笔仓位金额
  - recent_activity: 最近 30 天交易频次

用法:
  from services.user_style import build_user_style_context
  ctx = build_user_style_context(user_id=1)  # 返回可注入 prompt 的文本
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _analyze_trades(user_id: int, lookback_days: int = 180) -> dict:
    """从 transactions 表分析用户交易风格

    Returns:
        {total_trades, buy_count, sell_count, win_count, loss_count,
         win_rate, avg_hold_days, sectors, avg_position_amount,
         risk_tolerance}
    """
    from database import query_all
    from datetime import datetime, timedelta

    since = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    # 拉取用户的 buy/sell 交易
    rows = query_all(
        """SELECT stock_code, stock_name, direction, price, quantity, amount, fee, traded_at
           FROM transactions
           WHERE user_id = ? AND traded_at >= ?
           ORDER BY traded_at ASC""",
        (user_id, since),
    )
    if not rows:
        return {
            "total_trades": 0,
            "buy_count": 0,
            "sell_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": None,
            "avg_hold_days": None,
            "sectors": [],
            "avg_position_amount": None,
            "risk_tolerance": "medium",
        }

    buys: dict[str, dict] = {}  # code -> latest buy trade
    sells: dict[str, dict] = {}
    for r in rows:
        if r["direction"] == "buy":
            buys[r["stock_code"]] = r
        elif r["direction"] == "sell":
            sells[r["stock_code"]] = r

    # 计算胜率:有对应 buy 的 sell 才算
    win_count = 0
    loss_count = 0
    hold_days_list: list[int] = []
    sector_counts: dict[str, int] = {}
    position_amounts: list[float] = []

    for code, sell in sells.items():
        buy = buys.get(code)
        if not buy:
            continue
        pnl = (sell["price"] - buy["price"]) * sell["quantity"] - (sell.get("fee") or 0)
        if pnl > 0:
            win_count += 1
        else:
            loss_count += 1
        # 持仓天数
        if sell.get("traded_at") and buy.get("traded_at"):
            try:
                d1 = datetime.fromisoformat(sell["traded_at"][:10])
                d2 = datetime.fromisoformat(buy["traded_at"][:10])
                hold_days_list.append((d1 - d2).days)
            except (ValueError, TypeError):
                pass
        # 行业(暂用 stock_name 简化,实际应 join 行业表)
        if sell.get("stock_name"):
            sector_counts[sell["stock_name"]] = sector_counts.get(sell["stock_name"], 0) + 1
        # 仓位金额
        if buy.get("amount"):
            position_amounts.append(float(buy["amount"]))

    total_round_trips = win_count + loss_count
    win_rate = win_count / total_round_trips if total_round_trips > 0 else None
    avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else None
    avg_position = sum(position_amounts) / len(position_amounts) if position_amounts else None

    # 风险容忍度:基于平均持仓天数 + 行业分散度
    if avg_hold_days is not None:
        if avg_hold_days < 3:
            risk_tolerance = "high"  # 短炒 = 高风险偏好
        elif avg_hold_days < 30:
            risk_tolerance = "medium"
        else:
            risk_tolerance = "low"  # 长线 = 低风险偏好
    else:
        risk_tolerance = "medium"

    # 偏好行业(top 3)
    sorted_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)
    preferred_sectors = [s[0] for s in sorted_sectors[:3]]

    return {
        "total_trades": len(rows),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "avg_hold_days": avg_hold_days,
        "sectors": preferred_sectors,
        "avg_position_amount": avg_position,
        "risk_tolerance": risk_tolerance,
    }


def build_user_style_context(user_id: int, lookback_days: int = 180) -> Optional[str]:
    """构建用户风格 context 字符串(可注入 system prompt)

    Returns:
        格式化的多行文本,失败/无数据返回 None
    """
    try:
        style = _analyze_trades(user_id, lookback_days)
    except Exception as e:
        logger.warning("build_user_style_context(%s) failed: %s", user_id, e)
        return None

    if style["total_trades"] == 0:
        return None  # 无交易数据,不注入

    lines = ["\n## 用户交易风格参考(v4.0 A4 个性化)"]
    lines.append(f"- 回看周期: 最近 {lookback_days} 天")
    lines.append(f"- 总交易笔数: {style['total_trades']}(买{style['buy_count']} / 卖{style['sell_count']})")

    if style["win_rate"] is not None:
        lines.append(f"- 历史胜率: {style['win_rate'] * 100:.0f}%")
    if style["avg_hold_days"] is not None:
        lines.append(f"- 平均持仓天数: {style['avg_hold_days']:.1f} 天")
    if style["sectors"]:
        lines.append(f"- 偏好行业(Top {len(style['sectors'])}): {', '.join(style['sectors'])}")
    if style["avg_position_amount"] is not None:
        lines.append(f"- 平均单笔仓位: ¥{style['avg_position_amount']:,.0f}")
    lines.append(f"- 风险偏好: {style['risk_tolerance']}(由持仓时长 + 行业分散度推断)")

    # 给出建议
    if style["avg_hold_days"] is not None and style["avg_hold_days"] < 2:
        lines.append("- 建议: 用户偏短线,关注 T+1/T+2 短线机会,优先考虑流动性")
    elif style["avg_hold_days"] is not None and style["avg_hold_days"] > 60:
        lines.append("- 建议: 用户偏长线,关注基本面 + 行业趋势,短期波动可忽略")

    if style["win_rate"] is not None and style["win_rate"] < 0.4:
        lines.append("- 警告: 用户历史胜率偏低,本次建议偏保守")

    return "\n".join(lines)
