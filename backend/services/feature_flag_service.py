"""Feature Flag 服务 (v3.11+, T8) — 灰度发布 / 紧急回滚

按 plan-ceo-review 2026-07-24 §Delivery gates 设计:
  - 新功能先加 flag, 默认 OFF
  - flag ON → 走新代码路径, OFF → 兼容旧行为
  - 回滚只关 flag, 不改代码

公开 API:
  - is_enabled(flag_key, scope='global') -> bool
  - set_flag(flag_key, enabled, updated_by='admin', description='') -> bool
  - list_flags(scope=None) -> list[dict]
  - ensure_flag(flag_key, description, default=False) -> None  (bootstrap)

设计:
  - flag_key 全局唯一 (scope='global') 或 per-user/per-scope
  - 内存缓存 + DB 真值, 5min TTL 自动 reload
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from database import execute, query_all, query_one

logger = logging.getLogger(__name__)


_CACHE: dict[str, bool] = {}
_CACHE_TIME: float = 0.0
_CACHE_TTL_SECONDS = 300  # 5 min


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _refresh_cache_if_stale() -> None:
    global _CACHE, _CACHE_TIME
    now_ts = datetime.now().timestamp()
    if now_ts - _CACHE_TIME < _CACHE_TTL_SECONDS and _CACHE:
        return
    rows = query_all(
        "SELECT flag_key, enabled, scope FROM feature_flags"
    )
    new_cache: dict[str, bool] = {}
    for r in rows:
        key = f"{r['scope']}::{r['flag_key']}"
        new_cache[key] = bool(r["enabled"])
    _CACHE = new_cache
    _CACHE_TIME = now_ts


def _key(flag_key: str, scope: str) -> str:
    return f"{scope}::{flag_key}"


# ════════════════════════════════════════════════════════════
#  公开 API
# ════════════════════════════════════════════════════════════

def is_enabled(flag_key: str, scope: str = "global") -> bool:
    """检查 flag 是否启用. 默认 False (新功能默认 OFF)."""
    _refresh_cache_if_stale()
    return _CACHE.get(_key(flag_key, scope), False)


def set_flag(
    flag_key: str,
    enabled: bool,
    *,
    scope: str = "global",
    updated_by: str = "admin",
    description: str = "",
) -> bool:
    """设置 flag 状态. 返回是否实际改动了."""
    cur = execute(
        "UPDATE feature_flags SET enabled = ?, updated_by = ?, updated_at = ?, "
        "description = CASE WHEN description = '' THEN ? ELSE description END "
        "WHERE flag_key = ? AND scope = ?",
        (1 if enabled else 0, updated_by, _now(), description, flag_key, scope),
    )
    if cur["changes"] == 0:
        # 不存在 → 插入
        execute(
            "INSERT OR IGNORE INTO feature_flags "
            "(flag_key, enabled, scope, description, updated_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (flag_key, 1 if enabled else 0, scope, description, updated_by, _now()),
        )
    # 失效缓存
    global _CACHE_TIME
    _CACHE_TIME = 0
    return True


def ensure_flag(flag_key: str, description: str = "", default: bool = False) -> None:
    """bootstrap 时确保 flag 存在 (不覆盖已有)."""
    row = query_one(
        "SELECT 1 FROM feature_flags WHERE flag_key = ?", (flag_key,)
    )
    if row:
        return
    set_flag(flag_key, default, description=description, updated_by="bootstrap")


def list_flags(scope: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM feature_flags"
    params: list = []
    if scope:
        sql += " WHERE scope = ?"
        params.append(scope)
    sql += " ORDER BY flag_key"
    return query_all(sql, tuple(params))


def reset_cache() -> None:
    """测试 / 紧急用: 立即清缓存."""
    global _CACHE_TIME, _CACHE
    _CACHE_TIME = 0
    _CACHE = {}