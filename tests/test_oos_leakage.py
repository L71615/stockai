"""T2 point-in-time OOS + 快照 replay 测试

覆盖:
  - freeze_snapshot 必填字段缺失抛错 (SnapshotLeakageError)
  - validation_window.end > as_of_date 抛错
  - UNIQUE(experiment_id, version) 冲突抛 SnapshotDuplicateError
  - 同 dict freeze 两次 version 自增, 输入 hash 相同
  - get_snapshot 取最新/指定 version
  - compute_input_hash 稳定 (同 dict 永远同 hash, key 顺序无关)
  - assert_no_future_data 检测未来行
  - replay_from_snapshot 调用 callback 并把 snapshot 传过去
  - _evaluate_overfit_from_snapshot: 同 snapshot 跑两次结果 snapshot_meta.input_version_hash 相同
  - _evaluate_overfit_from_snapshot: curve/trades 含未来日期抛 SnapshotLeakageError
  - fixture 文件存在并能 freeze + replay 走通
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Module-level DB init (与 test_experiment_service.py 一致)
import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_oos.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

_TEST_DB_PATH = Path("/tmp/stockai_test_oos.db")
if _TEST_DB_PATH.exists():
    try:
        _TEST_DB_PATH.unlink()
    except PermissionError:
        import time
        time.sleep(0.3)
        _TEST_DB_PATH.unlink(missing_ok=True)

from database import init_db, ensure_admin_user as _eua
init_db()
_eua()

import pytest

from services.experiment_service import create_experiment
from services.snapshot_service import (
    freeze_snapshot, get_snapshot, list_snapshots,
    compute_input_hash, replay_from_snapshot, assert_no_future_data,
    snapshot_diff,
    SnapshotNotFoundError, SnapshotLeakageError, SnapshotDuplicateError,
)
from services.strategy_backtest_service import _evaluate_overfit_from_snapshot


# ════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════

def _make_snapshot(as_of: str = "2026-07-24") -> dict:
    return {
        "as_of_date": as_of,
        "stock_pool": ["600519", "000858"],
        "stock_pool_source": "csi800",
        "factor_values": {"600519": 0.04, "000858": -0.02},
        "kline_window": {"start": "2025-04-01", "end": as_of, "count": 250},
        "config": {"policy_version": "v1.0.0", "cost_bps": 30},
        "validation_window": {"start": "2025-04-01", "end": as_of},
        "oos_window": {"start": "2026-01-01", "end": as_of},
    }


def _make_curve(start: str, end: str, n: int = 30) -> list[dict]:
    """构造 n 天单调上升的净值曲线, 不含未来行"""
    from datetime import datetime, timedelta
    s = datetime.strptime(start, "%Y-%m-%d")
    curve = []
    val = 100000.0
    for i in range(n):
        d = (s + timedelta(days=i)).strftime("%Y-%m-%d")
        if d > end:
            break
        val *= 1.005
        curve.append({"date": d, "value": round(val, 2)})
    return curve


# ════════════════════════════════════════════════════════════
#  freeze 基本
# ════════════════════════════════════════════════════════════

def test_freeze_missing_as_of_date():
    exp_id = create_experiment(owner_user_id=1, expr_text="snap_x")
    with pytest.raises(SnapshotLeakageError, match="as_of_date"):
        freeze_snapshot(experiment_id=exp_id, snapshot={"stock_pool": ["600519"]})


def test_freeze_validation_window_end_after_as_of():
    exp_id = create_experiment(owner_user_id=1, expr_text="snap_y")
    bad = _make_snapshot()
    bad["validation_window"]["end"] = "2099-01-01"  # 未来
    with pytest.raises(SnapshotLeakageError, match="validation_window.end"):
        freeze_snapshot(experiment_id=exp_id, snapshot=bad)


def test_freeze_oos_window_end_after_as_of():
    exp_id = create_experiment(owner_user_id=1, expr_text="snap_z")
    bad = _make_snapshot()
    bad["oos_window"]["end"] = "2099-12-31"
    with pytest.raises(SnapshotLeakageError, match="oos_window.end"):
        freeze_snapshot(experiment_id=exp_id, snapshot=bad)


def test_freeze_returns_increasing_version():
    exp_id = create_experiment(owner_user_id=1, expr_text="snap_v")
    v1 = freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot())
    v2 = freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot())
    v3 = freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot())
    assert v1 == 1
    assert v2 == 2
    assert v3 == 3


def test_freeze_duplicate_version_raises():
    exp_id = create_experiment(owner_user_id=1, expr_text="snap_dup")
    freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot(), version=5)
    with pytest.raises(SnapshotDuplicateError):
        freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot(), version=5)


def test_freeze_input_hash_stable():
    """同 dict 不同调用, hash 必须一致"""
    snap = _make_snapshot()
    h1 = compute_input_hash(snap)
    h2 = compute_input_hash(snap)
    assert h1 == h2
    assert len(h1) == 64  # sha256


def test_freeze_input_hash_key_order_invariant():
    """dict key 顺序不影响 hash (规范化 JSON)"""
    a = {"a": 1, "b": 2, "c": 3}
    b = {"c": 3, "b": 2, "a": 1}
    assert compute_input_hash(a) == compute_input_hash(b)


def test_get_snapshot_latest_and_specific():
    exp_id = create_experiment(owner_user_id=1, expr_text="snap_get")
    freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot())
    freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot(as_of="2026-07-25"))

    latest = get_snapshot(exp_id)
    assert latest["version"] == 2
    assert latest["as_of_date"] == "2026-07-25"
    assert "stock_pool" in latest["snapshot"]

    specific = get_snapshot(exp_id, version=1)
    assert specific["as_of_date"] == "2026-07-24"


def test_get_snapshot_not_found():
    with pytest.raises(SnapshotNotFoundError):
        get_snapshot("exp-doesnt-exist-xxx")


def test_list_snapshots_ordering():
    exp_id = create_experiment(owner_user_id=1, expr_text="snap_list")
    freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot(as_of="2026-07-22"))
    freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot(as_of="2026-07-23"))
    freeze_snapshot(experiment_id=exp_id, snapshot=_make_snapshot(as_of="2026-07-24"))

    rows = list_snapshots(exp_id)
    versions = [r["version"] for r in rows]
    assert versions == [3, 2, 1]  # DESC


# ════════════════════════════════════════════════════════════
#  assert_no_future_data
# ════════════════════════════════════════════════════════════

def test_assert_no_future_data_clean():
    snap = _make_snapshot(as_of="2026-07-24")
    rows = [{"trade_date": "2026-07-22"}, {"trade_date": "2026-07-23"}]
    assert_no_future_data(snap, rows)  # 不抛


def test_assert_no_future_data_detects_one():
    snap = _make_snapshot(as_of="2026-07-24")
    rows = [{"trade_date": "2026-07-22"}, {"trade_date": "2026-07-25"}]
    with pytest.raises(SnapshotLeakageError, match="泄漏"):
        assert_no_future_data(snap, rows)


def test_assert_no_future_data_missing_date_field():
    snap = _make_snapshot(as_of="2026-07-24")
    rows = [{"foo": "bar"}]  # 没 trade_date 字段
    assert_no_future_data(snap, rows)  # 不抛 (跳过)


# ════════════════════════════════════════════════════════════
#  replay_from_snapshot
# ════════════════════════════════════════════════════════════

def test_replay_passes_snapshot_to_callback():
    snap = _make_snapshot()
    captured = {}
    def cb(s, *args, **kwargs):
        captured["snapshot"] = s
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    row = {
        "snapshot": snap,
        "experiment_id": "exp-test",
        "version": 1,
    }
    result = replay_from_snapshot(row, cb, "x", y=1)
    assert result == "ok"
    assert captured["snapshot"] == snap
    assert captured["args"] == ("x",)
    assert captured["kwargs"] == {"y": 1}


def test_snapshot_diff_compares():
    a = {"version": 1, "as_of_date": "2026-07-24", "input_version_hash": "abc"}
    b = {"version": 2, "as_of_date": "2026-07-25", "input_version_hash": "abc"}
    diff = snapshot_diff(a, b)
    assert diff["same_input_hash"] is True
    assert diff["a_version"] == 1
    assert diff["b_version"] == 2


# ════════════════════════════════════════════════════════════
#  _evaluate_overfit_from_snapshot
# ════════════════════════════════════════════════════════════

def test_overfit_from_snapshot_happy_path():
    snap = _make_snapshot(as_of="2026-07-24")
    curve = _make_curve("2026-04-01", "2026-07-24", n=80)
    trades = [{"date": "2026-04-05", "code": "600519", "direction": "buy"}]

    result = _evaluate_overfit_from_snapshot(
        snapshot=snap, equity_curve=curve, trades=trades, initial_cash=100000.0,
    )
    assert "snapshot_meta" in result
    meta = result["snapshot_meta"]
    assert meta["as_of_date"] == "2026-07-24"
    assert meta["policy_version"] == "v1.0.0"
    assert "600519" in meta["stock_pool"]


def test_overfit_from_snapshot_leakage_curve():
    snap = _make_snapshot(as_of="2026-07-24")
    curve = _make_curve("2026-04-01", "2026-07-30", n=120)  # 含未来行
    with pytest.raises(SnapshotLeakageError, match="curve"):
        _evaluate_overfit_from_snapshot(
            snapshot=snap, equity_curve=curve, trades=[], initial_cash=100000.0,
        )


def test_overfit_from_snapshot_leakage_trade():
    snap = _make_snapshot(as_of="2026-07-24")
    curve = _make_curve("2026-04-01", "2026-07-24", n=80)
    future_trade = [{"date": "2026-08-01", "code": "600519"}]
    with pytest.raises(SnapshotLeakageError, match="trade"):
        _evaluate_overfit_from_snapshot(
            snapshot=snap, equity_curve=curve, trades=future_trade, initial_cash=100000.0,
        )


def test_overfit_from_snapshot_hash_equality():
    """同 snapshot 跑两次, snapshot_meta.input_version_hash 必须相同."""
    snap = _make_snapshot(as_of="2026-07-24")
    snap["__input_hash"] = compute_input_hash(snap)  # 模拟 freeze 写入
    curve = _make_curve("2026-04-01", "2026-07-24", n=80)
    trades = [{"date": "2026-04-05", "code": "600519", "direction": "buy"}]

    r1 = _evaluate_overfit_from_snapshot(
        snapshot=snap, equity_curve=curve, trades=trades, initial_cash=100000.0,
    )
    r2 = _evaluate_overfit_from_snapshot(
        snapshot=snap, equity_curve=curve, trades=trades, initial_cash=100000.0,
    )
    assert r1["snapshot_meta"]["input_version_hash"] == r2["snapshot_meta"]["input_version_hash"]
    # 主判定字段也应相同 (verdict / sharpe_decay_pct)
    assert r1["verdict"] == r2["verdict"]
    assert r1["sharpe_decay_pct"] == r2["sharpe_decay_pct"]


def test_overfit_from_snapshot_missing_as_of():
    with pytest.raises(SnapshotLeakageError, match="缺 as_of_date"):
        _evaluate_overfit_from_snapshot(
            snapshot={"stock_pool": ["600519"]},
            equity_curve=[{"date": "2026-07-24", "value": 100000}],
            trades=[],
            initial_cash=100000.0,
        )


# ════════════════════════════════════════════════════════════
#  Fixture 集成
# ════════════════════════════════════════════════════════════

def test_fixture_freeze_replay_roundtrip():
    """用 build_freeze_fixture 生成的 fixture, 走完整 freeze → replay"""
    fixture_path = Path(__file__).parent / "fixtures" / "freeze_demo.json"
    if not fixture_path.exists():
        pytest.skip(f"fixture not found: {fixture_path} (跑 build_freeze_fixture.py 生成)")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    exp_id = create_experiment(owner_user_id=1, expr_text="fixture_demo")
    snap = {k: v for k, v in fixture.items() if k != "experiment_id"}

    version = freeze_snapshot(experiment_id=exp_id, snapshot=snap, policy_hash="v1.0.0")
    assert version == 1

    row = get_snapshot(exp_id)
    assert row["as_of_date"] == fixture["as_of_date"]
    assert len(row["snapshot"]["equity_curve"]) == len(fixture["equity_curve"])

    # 走一遍 replay
    result = _evaluate_overfit_from_snapshot(
        snapshot=row["snapshot"],
        equity_curve=row["snapshot"]["equity_curve"],
        trades=row["snapshot"]["trades"],
        initial_cash=fixture["config"]["initial_cash"],
    )
    assert "verdict" in result
    assert result["snapshot_meta"]["as_of_date"] == fixture["as_of_date"]


def test_fixture_tamper_rejected():
    """场景: 攻击者 freeze 时通过, replay 时塞入未来 trade — replay 必须拦截.

    实际上 freeze_snapshot 自己已经拦截 validation/oos window 越界,
    这里模拟的是另一种攻击: freeze 通过 (window 收缩到合法), 但 replay
    时塞入 trade date > as_of_date 的伪造 trade.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "freeze_demo.json"
    if not fixture_path.exists():
        pytest.skip(f"fixture not found: {fixture_path}")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    # 合法 snapshot: window 都收敛到 as_of_date 之前
    snap = {k: v for k, v in fixture.items() if k != "experiment_id"}
    snap["as_of_date"] = "2026-07-24"
    snap["validation_window"] = {"start": "2026-04-01", "end": "2026-07-20"}
    snap["oos_window"] = {"start": "2026-05-01", "end": "2026-07-20"}

    exp_id = create_experiment(owner_user_id=1, expr_text="tamper_test")
    freeze_snapshot(experiment_id=exp_id, snapshot=snap)
    row = get_snapshot(exp_id)

    # 攻击: replay 时塞入未来 trade
    forged_trades = [{"date": "2026-08-15", "code": "999999", "direction": "buy"}]
    with pytest.raises(SnapshotLeakageError, match="trade"):
        _evaluate_overfit_from_snapshot(
            snapshot=row["snapshot"],
            equity_curve=row["snapshot"]["equity_curve"],
            trades=forged_trades,
            initial_cash=fixture["config"]["initial_cash"],
        )


def test_fixture_freeze_window_overflow_rejected():
    """freeze 时 window.end > as_of_date 必须直接拒绝 (前置防护)."""
    fixture_path = Path(__file__).parent / "fixtures" / "freeze_demo.json"
    if not fixture_path.exists():
        pytest.skip(f"fixture not found: {fixture_path}")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    snap = {k: v for k, v in fixture.items() if k != "experiment_id"}
    snap["as_of_date"] = "2026-07-01"  # 提前
    # 但 validation_window.end 仍是 2026-07-24 > as_of_date
    snap["validation_window"]["end"] = "2026-07-24"

    exp_id = create_experiment(owner_user_id=1, expr_text="overflow_test")
    with pytest.raises(SnapshotLeakageError, match="validation_window.end"):
        freeze_snapshot(experiment_id=exp_id, snapshot=snap)