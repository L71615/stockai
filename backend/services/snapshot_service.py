"""实验快照服务 (v3.11+) — point-in-time 输入冻结 + 独立 OOS replay

按 plan-ceo-review 2026-07-24 §Phase 1.2 / D14 设计:
  - 任何验证/回测前先 freeze_snapshot()
  - replay 只能读 experiment_snapshots, 不能直接读实时 historical_kline
  - 同 snapshot 二次 replay 必须产生相同 hash (hash equality)
  - as_of_date 之后的 row 永远不进 snapshot (leakage prevention)

snapshot_json 必含字段 (推荐):
  - stock_pool: [code, ...]            当时使用的股票池
  - stock_pool_source: str             池子来源 ("csi800" / "manual" / ...)
  - as_of_date: "YYYY-MM-DD"           数据截止日 (与表字段冗余, 便于校验)
  - factor_values: {code: value}       当时每个股票的因子值
  - kline_window: {start, end, count}  K 线覆盖
  - config: {policy_version, cost_bps, rebalance, ...}  验证配置
  - validation_window: {start, end}    验证时段
  - oos_window: {start, end}           OOS 时段

公开 API:
  - freeze_snapshot(experiment_id, snapshot_dict, policy_hash, ...) -> version
  - get_snapshot(experiment_id, version=latest) -> dict (含 snapshot_json 解码)
  - list_snapshots(experiment_id) -> list
  - compute_input_hash(snapshot_dict) -> sha256 hex  (规范化 JSON)
  - replay_from_snapshot(snapshot, replay_func, *args) -> replay_func 返回值
  - assert_no_future_data(snapshot, rows_with_date, ...) -> None (未来行抛错)

异常:
  - SnapshotNotFoundError
  - SnapshotLeakageError (检测到 as_of_date 之后的行)
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from database import execute, query_all, query_one

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  异常
# ════════════════════════════════════════════════════════════

class SnapshotError(Exception):
    http_status = 400


class SnapshotNotFoundError(SnapshotError):
    http_status = 404


class SnapshotLeakageError(SnapshotError):
    """snapshot 里混入了 as_of_date 之后的数据, 视为泄漏"""
    http_status = 422


class SnapshotDuplicateError(SnapshotError):
    """UNIQUE(experiment_id, version) 冲突"""
    http_status = 409


# ════════════════════════════════════════════════════════════
#  hash + 时间工具
# ════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def compute_input_hash(snapshot: dict) -> str:
    """规范化 JSON 后算 sha256. 同 dict 永远同 hash (dict key 排序保证稳定)."""
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ════════════════════════════════════════════════════════════
#  freeze / get / list
# ════════════════════════════════════════════════════════════

def freeze_snapshot(
    *,
    experiment_id: str,
    snapshot: dict,
    policy_hash: str = "",
    note: str = "",
    version: Optional[int] = None,
) -> int:
    """冻结一个 point-in-time 输入快照.

    Args:
        experiment_id: 关联实验
        snapshot: 完整 dict, 会被规范化 JSON
        policy_hash: 验证策略 hash (从 validation_policy.POLICY_HASH 传入)
        note: 说明文字
        version: 不传则自动 = (该 experiment 的 max(version) + 1)

    Returns:
        新 version 号

    Raises:
        SnapshotLeakageError: snapshot 里 as_of_date 字段缺失或不一致
        SnapshotDuplicateError: UNIQUE 冲突 (同一 experiment_id + version 已存在)
    """
    as_of = snapshot.get("as_of_date")
    if not as_of:
        raise SnapshotLeakageError("snapshot 必须包含 as_of_date (YYYY-MM-DD)")
    if "validation_window" in snapshot:
        vw = snapshot["validation_window"]
        if isinstance(vw, dict) and vw.get("end") and vw["end"] > as_of:
            raise SnapshotLeakageError(
                f"validation_window.end ({vw['end']}) 不能晚于 as_of_date ({as_of})"
            )
        if "oos_window" in snapshot:
            ow = snapshot["oos_window"]
            if isinstance(ow, dict) and ow.get("end") and ow["end"] > as_of:
                raise SnapshotLeakageError(
                    f"oos_window.end ({ow['end']}) 不能晚于 as_of_date ({as_of})"
                )

    input_hash = compute_input_hash(snapshot)
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)

    if version is None:
        row = query_one(
            "SELECT COALESCE(MAX(version), 0) AS mx FROM experiment_snapshots WHERE experiment_id = ?",
            (experiment_id,),
        )
        version = int(row["mx"]) + 1 if row else 1

    try:
        cur = execute(
            "INSERT INTO experiment_snapshots "
            "(experiment_id, version, policy_hash, input_version_hash, "
            " as_of_date, snapshot_json, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (experiment_id, version, policy_hash, input_hash,
             as_of, snapshot_json, note, _now()),
        )
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg or "experiment_snapshots.experiment_id" in msg:
            raise SnapshotDuplicateError(
                f"snapshot already exists: experiment_id={experiment_id}, version={version}"
            ) from e
        raise
    return version


def get_snapshot(
    experiment_id: str,
    *,
    version: Optional[int] = None,
) -> dict:
    """取一个 snapshot. version=None 取最新版本."""
    if version is None:
        row = query_one(
            "SELECT * FROM experiment_snapshots WHERE experiment_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (experiment_id,),
        )
    else:
        row = query_one(
            "SELECT * FROM experiment_snapshots WHERE experiment_id = ? AND version = ?",
            (experiment_id, version),
        )
    if not row:
        raise SnapshotNotFoundError(
            f"snapshot not found: experiment_id={experiment_id}, version={version}"
        )
    row["snapshot"] = json.loads(row["snapshot_json"])
    return row


def list_snapshots(experiment_id: str) -> list[dict]:
    """列一个实验的所有 snapshot (按 version 降序)."""
    return query_all(
        "SELECT * FROM experiment_snapshots WHERE experiment_id = ? "
        "ORDER BY version DESC",
        (experiment_id,),
    )


# ════════════════════════════════════════════════════════════
#  replay + leakage 检测
# ════════════════════════════════════════════════════════════

def replay_from_snapshot(
    snapshot_row: dict,
    replay_func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """从 snapshot 跑 replay 函数.

    Args:
        snapshot_row: get_snapshot() 返回的行 (含 'snapshot' 解码后的 dict)
        replay_func: 接收 (snapshot_dict, *args, **kwargs) 的 callable
        *args/**kwargs: 传给 replay_func 的额外参数

    Returns:
        replay_func 的返回值
    """
    snap = snapshot_row["snapshot"]
    return replay_func(snap, *args, **kwargs)


def assert_no_future_data(
    snapshot: dict,
    rows: list[dict],
    date_field: str = "trade_date",
) -> None:
    """断言 rows 里所有行的日期 ≤ snapshot.as_of_date.

    Raises:
        SnapshotLeakageError: 任一行日期 > as_of_date
    """
    as_of = snapshot.get("as_of_date")
    if not as_of:
        raise SnapshotLeakageError("snapshot 缺 as_of_date")
    leaks = []
    for r in rows:
        d = r.get(date_field)
        if not d:
            continue
        # 字符串比较, 假设 ISO YYYY-MM-DD 格式
        if d > as_of:
            leaks.append((d, as_of))
    if leaks:
        sample = leaks[:5]
        raise SnapshotLeakageError(
            f"检测到 {len(leaks)} 行未来数据泄漏 (sample={sample}); "
            f"as_of_date={as_of}"
        )


def snapshot_diff(a: dict, b: dict) -> dict:
    """返回两个 snapshot 的差异, 用于审计/调试. 不抛错."""
    a.pop("created_at", None)
    b.pop("created_at", None)
    return {
        "same_input_hash": a.get("input_version_hash") == b.get("input_version_hash"),
        "a_version": a.get("version"),
        "b_version": b.get("version"),
        "a_as_of": a.get("as_of_date"),
        "b_as_of": b.get("as_of_date"),
    }