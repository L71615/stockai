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


def get_journal(user_id: int = 1, limit: int = 50) -> list[dict]:
    """获取交易日志列表"""
    rows = query_all(
        """SELECT * FROM trade_journal WHERE user_id = ?
           ORDER BY exit_date DESC, id DESC LIMIT ?""",
        (user_id, limit),
    )
    return [dict(r) for r in rows]
