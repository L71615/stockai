"""交易纪律服务 — 连亏计数 + 保护模式 + 自动日志"""

import logging
from database import query_all, query_one, execute

logger = logging.getLogger(__name__)

PROTECTION_KEY = "protection_mode"
DEFAULT_PROTECTION = {
    "enabled": True,
    "max_consecutive": 3,
    "locked_until": None,
}


def get_consecutive_losses(user_id: int = 1) -> int:
    """从交易日志倒序数连续亏损次数"""
    rows = query_all(
        """SELECT pnl FROM trade_journal
           WHERE user_id = ? AND pnl IS NOT NULL
           ORDER BY exit_date DESC, id DESC LIMIT 30""",
        (user_id,),
    )
    streak = 0
    for r in rows:
        if r["pnl"] < 0:
            streak += 1
        else:
            break
    return streak


def get_protection_config() -> dict:
    """读取保护模式配置"""
    row = query_one("SELECT value FROM settings WHERE key = ?", (PROTECTION_KEY,))
    if not row:
        return dict(DEFAULT_PROTECTION)
    import json
    try:
        cfg = json.loads(row["value"])
        for k, v in DEFAULT_PROTECTION.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_PROTECTION)


def save_protection_config(cfg: dict):
    """保存保护模式配置"""
    import json
    execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (PROTECTION_KEY, json.dumps(cfg, ensure_ascii=False)),
    )


def check_protection(user_id: int = 1) -> dict:
    """检查保护模式是否激活"""
    cfg = get_protection_config()
    streak = get_consecutive_losses(user_id)
    locked = False
    if cfg["enabled"] and streak >= cfg["max_consecutive"]:
        locked = True
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cfg["locked_until"] = now
        save_protection_config(cfg)
    return {
        "streak": streak,
        "max_consecutive": cfg["max_consecutive"],
        "protection_active": locked,
        "locked_until": cfg.get("locked_until"),
        "enabled": cfg["enabled"],
    }


def auto_create_journal_entry(user_id: int, stock_code: str, stock_name: str,
                               exit_price: float, quantity: int, pnl: float | None = None):
    """卖出时自动创建交易日志（入场价从买入记录反查）"""
    # 查最近一次买入
    buy = query_one(
        """SELECT price, traded_at FROM transactions
           WHERE user_id = ? AND stock_code = ? AND direction = 'buy'
           ORDER BY traded_at DESC LIMIT 1""",
        (user_id, stock_code),
    )
    entry_price = buy["price"] if buy else None
    entry_date = buy["traded_at"] if buy else None

    pnl_pct = None
    if pnl is not None and entry_price and entry_price > 0:
        cost = entry_price * quantity
        pnl_pct = round(pnl / cost * 100, 2)

    from datetime import date
    execute(
        """INSERT INTO trade_journal
           (user_id, stock_code, stock_name, direction, entry_price, exit_price,
            quantity, pnl, pnl_pct, entry_date, exit_date)
           VALUES (?, ?, ?, 'sell', ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, stock_code, stock_name, entry_price, exit_price,
         quantity, pnl, pnl_pct, entry_date, date.today().isoformat()),
    )

    # 同步写入交易记忆日志（Phase A：pending 状态，后续 AI 反思）
    try:
        from services.trading_memory import TradingMemoryLog
        mem = TradingMemoryLog()
        decision_text = (
            f"买入 {stock_code} {stock_name} 于 {entry_date}，价格 {entry_price}，{quantity}股；"
            f"卖出于 {date.today().isoformat()}，价格 {exit_price}，"
            f"盈亏 {pnl:.2f} 元 ({pnl_pct:.2f}%)" if pnl is not None and pnl_pct is not None
            else f"卖出 {stock_code} {stock_name} 于 {date.today().isoformat()}，价格 {exit_price}"
        )
        mem.store_decision(
            code=stock_code,
            direction="卖出",
            date=date.today().isoformat(),
            decision_text=decision_text,
            entry_price=entry_price or 0,
            quantity=quantity,
        )
    except Exception:
        pass  # 记忆记录失败不影响主流程


def get_journal(user_id: int = 1, limit: int = 50) -> list[dict]:
    """获取交易日志列表"""
    rows = query_all(
        """SELECT * FROM trade_journal WHERE user_id = ?
           ORDER BY exit_date DESC, id DESC LIMIT ?""",
        (user_id, limit),
    )
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════
#  交易规则
# ═══════════════════════════════════════════════════════════

RULES_KEY = "trading_rules"
DEFAULT_RULES = {
    "require_stop_loss": True,           # 买入前必须设止损
    "max_position_pct": 30,              # 单票最大仓位百分比
    "max_total_position_pct": 80,        # 总仓位上限（保留现金）
    "forbid_chasing_limit_up": True,     # 禁止追涨停板
    "max_consecutive_losses": 3,         # 连亏 N 笔自动停手
    "min_hold_days": 1,                  # 最短持仓天数
    "enabled": True,                     # 规则总开关
}


def get_rules() -> dict:
    """获取交易规则配置"""
    row = query_one("SELECT value FROM settings WHERE key = ?", (RULES_KEY,))
    if not row:
        return dict(DEFAULT_RULES)
    import json
    try:
        cfg = json.loads(row["value"])
        for k, v in DEFAULT_RULES.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_RULES)


def save_rules(rules: dict):
    """保存交易规则配置"""
    import json
    execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (RULES_KEY, json.dumps(rules, ensure_ascii=False)),
    )


def validate_buy(code: str, price: float, quantity: int, user_id: int = 1,
                 stop_loss_price: float | None = None) -> dict:
    """买入前校验——检查所有交易规则

    Returns:
        {"ok": True} 或 {"ok": False, "violations": ["违规原因1", ...]}
    """
    rules = get_rules()
    if not rules.get("enabled"):
        return {"ok": True}

    violations = []

    # 1. 检查保护模式
    protection = check_protection(user_id)
    if protection["protection_active"]:
        violations.append(
            f"保护模式已激活: 连亏 {protection['streak']} 笔 "
            f"(上限 {protection['max_consecutive']} 笔)。请等待下次交易周期或手动解除。"
        )

    # 2. 买入前必须设止损
    if rules.get("require_stop_loss"):
        if not stop_loss_price or stop_loss_price <= 0:
            violations.append("必须设置止损价才能买入")

    # 3. 单票仓位检查
    max_pct = rules.get("max_position_pct", 30)
    total_value = _get_total_value(user_id)
    if total_value > 0 and price > 0:
        position_value = price * quantity
        position_pct = position_value / total_value * 100
        if position_pct > max_pct:
            violations.append(
                f"单票仓位 {position_pct:.1f}% 超过上限 {max_pct}%"
            )
        # 总仓位检查
        existing_value = _get_current_positions_value(user_id)
        new_total_pct = (existing_value + position_value) / total_value * 100
        max_total = rules.get("max_total_position_pct", 80)
        if new_total_pct > max_total:
            violations.append(
                f"总仓位将达到 {new_total_pct:.1f}%，超过上限 {max_total}%"
            )

    # 4. 禁止追涨停
    if rules.get("forbid_chasing_limit_up"):
        try:
            from services.vendor_router import route
            quote = route("get_realtime_quote", code=code)
            if "error" not in quote and quote.get("change_pct"):
                change = float(quote["change_pct"])
                if change >= 9.5:
                    violations.append(f"当前涨幅 {change:.1f}%，禁止追涨停买入")
        except Exception:
            pass

    if violations:
        return {"ok": False, "violations": violations}
    return {"ok": True}


def _get_total_value(user_id: int = 1) -> float:
    """获取用户总资产"""
    rows = query_all(
        "SELECT quantity, cost_price FROM holdings WHERE user_id = ? AND quantity > 0",
        (user_id,),
    )
    return sum(r["quantity"] * r["cost_price"] for r in rows) if rows else 0


def _get_current_positions_value(user_id: int = 1) -> float:
    """获取当前持仓总市值"""
    total = 0.0
    rows = query_all(
        "SELECT stock_code, quantity FROM holdings WHERE user_id = ? AND quantity > 0",
        (user_id,),
    )
    for r in rows:
        try:
            from services.vendor_router import route
            quote = route("get_realtime_quote", code=r["stock_code"])
            if "error" not in quote and quote.get("price"):
                total += r["quantity"] * float(quote["price"])
        except Exception:
            pass
    return total
