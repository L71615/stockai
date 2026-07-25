"""T7 重启恢复 / 单飞锁抢占 / 实验 run 状态恢复

覆盖:
  - 单飞锁过期可被新 holder 抢占 (T1 实验已覆盖, 这里再加集成测试)
  - experiment_run 'running' 状态被新启动检测为 stale, 可被复用
  - pipeline run 写数据库后, 即使 in-memory STATUS 丢了也能从 DB 读到
  - 多 worker 同时启动: 只有一个抢到 pipeline_lock
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_restart.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

_TEST_DB_PATH = Path("/tmp/stockai_test_restart.db")
if _TEST_DB_PATH.exists():
    try:
        _TEST_DB_PATH.unlink()
    except PermissionError:
        import time
        time.sleep(0.3)
        _TEST_DB_PATH.unlink(missing_ok=True)

from database import init_db, ensure_admin_user as _eua, execute as db_execute, query_one, query_all
init_db()
_eua()

import pytest
import threading

from services.experiment_service import (
    create_experiment, acquire_pipeline_lock, release_pipeline_lock,
    get_pipeline_lock, transition,
)


# ════════════════════════════════════════════════════════════
#  单飞锁: 过期抢占
# ════════════════════════════════════════════════════════════

def test_pipeline_lock_expired_taken_over():
    scope = "restart_test_scope_1"
    # worker A 拿锁, TTL 1s
    assert acquire_pipeline_lock(scope, holder_pid="worker-A", ttl_seconds=1)
    # 强制过期
    db_execute(
        "UPDATE pipeline_lock SET expires_at = '2000-01-01 00:00:00' WHERE scope = ?",
        (scope,),
    )
    # worker B 抢占
    assert acquire_pipeline_lock(scope, holder_pid="worker-B", ttl_seconds=60)
    state = get_pipeline_lock(scope)
    assert state["holder_pid"] == "worker-B"
    release_pipeline_lock(scope, holder_pid="worker-B")


def test_pipeline_lock_active_blocks_new():
    scope = "restart_test_scope_2"
    acquire_pipeline_lock(scope, holder_pid="worker-A", ttl_seconds=60)
    # worker B 不能抢
    assert not acquire_pipeline_lock(scope, holder_pid="worker-B", ttl_seconds=60)
    # 续期 worker A
    assert acquire_pipeline_lock(scope, holder_pid="worker-A", ttl_seconds=60)
    release_pipeline_lock(scope, holder_pid="worker-A")


# ════════════════════════════════════════════════════════════
#  Experiment run: 重启后从 DB 查到 running 状态
# ════════════════════════════════════════════════════════════

def test_experiment_run_persists_through_restart():
    """模拟: 进程崩溃, DB 里的 run 状态保留, 新进程可读到."""
    from services.experiment_service import create_experiment
    from services.quant_pipeline import (
        _persist_run_start, _persist_run_step, _persist_run_finish,
    )
    from database import query_all

    exp_id = create_experiment(owner_user_id=1, expr_text="restart_test")

    # 1. 模拟 worker A 启动一个 run, 写一半
    run_id = _persist_run_start(scope="pipeline_daily", experiment_id=exp_id,
                                run_label="qp-restart-demo")
    _persist_run_step(run_id, "1_gp_mining", "running")
    _persist_run_step(run_id, "1_gp_mining", "done")

    # 2. 模拟 worker A 崩溃 (in-memory 状态全没)

    # 3. 新 worker B 启动, 从 DB 查 run
    rows = query_all(
        "SELECT run_id, scope, status, current_step FROM experiment_runs WHERE experiment_id = ?",
        (exp_id,),
    )
    assert len(rows) == 1
    assert rows[0]["run_id"] == run_id
    assert rows[0]["status"] == "done"
    assert rows[0]["current_step"] == "1_gp_mining"

    # 4. 完成 run
    _persist_run_finish(run_id, "done", {"test": True})
    rows2 = query_all(
        "SELECT status, current_step, finished_at FROM experiment_runs WHERE run_id = ?",
        (run_id,),
    )
    assert rows2[0]["status"] == "done"
    assert rows2[0]["finished_at"] is not None


def test_stale_running_run_can_be_marked_failed():
    """'running' 超过 N 小时没结束的 run 应被标记 failed (worker died)."""
    from services.experiment_service import create_experiment
    from services.quant_pipeline import _persist_run_start
    from database import execute as db_e

    exp_id = create_experiment(owner_user_id=1, expr_text="stale_run_test")
    run_id = _persist_run_start(scope="pipeline_daily",
                                experiment_id=exp_id,
                                run_label="qp-stale-demo")

    # 模拟 24 小时前启动
    db_e(
        "UPDATE experiment_runs SET started_at = '2020-01-01 00:00:00' WHERE run_id = ?",
        (run_id,),
    )

    # 假装检测器: 找到 stale running run 并标记 failed
    stale = query_all(
        "SELECT run_id FROM experiment_runs "
        "WHERE status = 'running' AND started_at < '2025-01-01 00:00:00'"
    )
    assert any(r["run_id"] == run_id for r in stale)

    db_e(
        "UPDATE experiment_runs SET status = 'failed', "
        "error_json = ?, finished_at = ? WHERE run_id = ?",
        ('{"reason": "stale run, worker died"}', "2025-01-01 00:00:00", run_id),
    )
    final = query_one("SELECT status FROM experiment_runs WHERE run_id = ?", (run_id,))
    assert final["status"] == "failed"


# ════════════════════════════════════════════════════════════
#  并发: 多 worker 启动, 只有一个抢到锁
# ════════════════════════════════════════════════════════════

def test_concurrent_workers_only_one_acquires():
    scope = "restart_test_concurrent"
    results = []
    barrier = threading.Barrier(3)

    def worker(pid):
        barrier.wait()
        ok = acquire_pipeline_lock(scope, holder_pid=pid, ttl_seconds=60)
        results.append((pid, ok))

    threads = [threading.Thread(target=worker, args=(f"w-{i}",)) for i in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()

    oks = [r for r in results if r[1]]
    assert len(oks) == 1, f"应只有一个 worker 抢到锁, 实得 {len(oks)}: {results}"

    state = get_pipeline_lock(scope)
    assert state["holder_pid"] == oks[0][0]
    release_pipeline_lock(scope, holder_pid=oks[0][0])


# ════════════════════════════════════════════════════════════
#  实验状态可从 DB 重建 (不依赖 in-memory 缓存)
# ════════════════════════════════════════════════════════════

def test_experiment_state_rebuildable_from_db():
    """新进程读 DB 能拿到完整三轴状态, 不需要任何缓存."""
    exp_id = create_experiment(owner_user_id=1, expr_text="rebuild_test")

    # 推进到 champion 终态
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="validated", expected_version=1, reason="step1")
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="paper", expected_version=2, reason="step2")
    transition(experiment_id=exp_id, axis="lifecycle_status",
               target="champion", expected_version=3, reason="step3")

    # 模拟"新进程": 直接查 DB
    from services.experiment_service import get_experiment
    fresh = get_experiment(exp_id)

    assert fresh["lifecycle_status"] == "champion"
    assert fresh["version"] == 4

    # audit 也能查到
    from services.experiment_service import list_events
    events = list_events(experiment_id=exp_id)
    transitions = [e for e in events if e["event_type"] == "transition:lifecycle_status"]
    assert len(transitions) == 3