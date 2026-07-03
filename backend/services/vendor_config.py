"""数据供应商配置 — 环境变量可控的 vendor 优先级链

用法:
  from services.vendor_config import get_config

  cfg = get_config()
  vendors = cfg["data_vendors"]["daily_kline"]  # → ["futu", "sina", "akshare", "baostock"]

环境变量覆盖:
  VENDOR_DAILY_KLINE=futu,baostock     → 只用 Futu + Baostock，跳过新浪和腾讯
  VENDOR_REALTIME_QUOTE=akshare        → 报价只用 AKShare
  VENDOR_FUNDAMENTALS=akshare,baostock → 基本面按此顺序尝试
"""

import os

# ── 环境变量 → 配置键映射 ──
_ENV_OVERRIDES = {
    "VENDOR_DAILY_KLINE":      "daily_kline",
    "VENDOR_REALTIME_QUOTE":   "realtime_quote",
    "VENDOR_BATCH_QUOTES":     "batch_quotes",
    "VENDOR_FUNDAMENTALS":     "fundamentals",
    "VENDOR_MINUTE_KLINE":     "minute_kline",
}

# ── 默认供应商链（按优先级排列）──
_DEFAULT_CONFIG = {
    "daily_kline":    ["futu", "sina", "akshare", "baostock"],
    "realtime_quote": ["futu", "akshare"],
    "batch_quotes":   ["akshare"],
    "fundamentals":   ["akshare", "baostock"],
    "minute_kline":   ["futu"],
}

_config_cache: dict | None = None


def get_config() -> dict:
    """获取供应商配置（带缓存，首次调用时应用环境变量覆盖）"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    cfg = dict(_DEFAULT_CONFIG)

    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw:
            vendors = [v.strip() for v in raw.split(",") if v.strip()]
            if vendors:
                cfg[key] = vendors

    _config_cache = cfg
    return cfg


def get_vendors(category: str) -> list[str]:
    """获取指定类别的供应商优先级列表"""
    return get_config()[category]
