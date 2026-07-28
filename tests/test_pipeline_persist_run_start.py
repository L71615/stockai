"""回归测试: 修复 daily pipeline 静默 NOT NULL 失败导致永远 status=running 的 bug

v4.0 后 v3.11 write-through 引入 experiment_runs, 但 daily pipeline 没绑实验
传 experiment_id=None, 而 schema 是 NOT NULL FK — 每次 POST /run 触发后
_persist_run_start() 第一秒就 IntegrityError, 但 run_pipeline 没标 STATUS=failed,
导致 /status 永远显示 running/current_step=0, 用户以为 hang。

修复:
1. _ensure_pipeline_daily_experiment() 幂等创建 __pipeline_daily__ 占位行
2. _persist_run_start() 在 experiment_id=None 时自动用它
3. run_pipeline() 顶层异常兜底: STATUS.finish('failed', ...) 让用户能看见
"""

import pytest


class TestEnsurePipelineDailyExperiment:
    def test_creates_synthetic_experiment_row(self, db):
        """首次调用应在 experiments 表创建 __pipeline_daily__ 行"""
        from services.quant_pipeline import _ensure_pipeline_daily_experiment, _PIPELINE_DAILY_EXPERIMENT_ID

        eid = _ensure_pipeline_daily_experiment()
        assert eid == "__pipeline_daily__"

        # 验证 DB 里确实有这行
        from database import query_one
        row = query_one("SELECT experiment_id, expr_text, lifecycle_status FROM experiments WHERE experiment_id = ?", (eid,))
        assert row is not None
        assert row["expr_text"] == "__pipeline_daily__"
        assert row["lifecycle_status"] == "champion"

    def test_is_idempotent(self, db):
        """重复调用不应报错也不应创建重复行"""
        from services.quant_pipeline import _ensure_pipeline_daily_experiment
        from database import query_one

        eid1 = _ensure_pipeline_daily_experiment()
        eid2 = _ensure_pipeline_daily_experiment()
        assert eid1 == eid2 == "__pipeline_daily__"

        rows = query_one("SELECT COUNT(*) AS cnt FROM experiments WHERE experiment_id = ?", (eid1,))
        assert rows["cnt"] == 1


class TestPersistRunStart:
    def test_none_experiment_id_uses_synthetic(self, db):
        """experiment_id=None 应自动用 __pipeline_daily__, 不抛 NOT NULL 约束"""
        from services.quant_pipeline import _persist_run_start

        # 不应抛 IntegrityError
        run_id = _persist_run_start(
            scope="pipeline_daily",
            experiment_id=None,
            run_label="qp-test-pipeline_daily",
        )
        assert isinstance(run_id, int) and run_id > 0

        # 验证 row 落库
        from database import query_one
        row = query_one("SELECT experiment_id, scope FROM experiment_runs WHERE run_id = ?", (run_id,))
        assert row is not None
        assert row["experiment_id"] == "__pipeline_daily__"
        assert row["scope"] == "pipeline_daily"

    def test_explicit_experiment_id_still_works(self, db):
        """experiment_id 显式传值时不应受影响"""
        from services.quant_pipeline import _persist_run_start

        # 先创建一个真实 experiment (满足 FK)
        from database import execute
        execute(
            "INSERT INTO experiments (experiment_id, owner_user_id, expr_text, "
            "policy_version, snapshot_hash, lifecycle_status, portfolio_role, "
            "proposal_status, version, snapshot_json, note, created_at, updated_at) "
            "VALUES (?, 1, 'ret_5d', 'v1.0.0', '', 'candidate', 'none', 'pending', "
            "1, '{}', 'test', '2026-07-28 00:00:00', '2026-07-28 00:00:00')",
            ("exp_real_test",),
        )

        run_id = _persist_run_start(
            scope="experiment",
            experiment_id="exp_real_test",
            run_label="qp-test-explicit",
        )
        assert isinstance(run_id, int)


class TestRunPipelineVisibility:
    def test_status_marked_failed_on_persist_error(self, db, monkeypatch):
        """如果 _persist_run_start 抛错, STATUS 应被标为 failed 而不是永远 running"""
        from services.quant_pipeline import STATUS, run_pipeline

        # 让 _persist_run_start 模拟失败 (例如 schema 漂移 / DB 写失败)
        import services.quant_pipeline as qp

        def boom(*args, **kwargs):
            raise RuntimeError("simulated DB error")

        monkeypatch.setattr(qp, "_persist_run_start", boom)

        result = run_pipeline()

        # 必须不是 running 状态 — 用户该看到失败
        assert result.get("status") == "failed", f"expected failed, got {result.get('status')}"
        assert "simulated DB error" in str(result.get("summary", {}).get("error", ""))
        assert STATUS.get().get("status") == "failed"

    def test_status_finish_called_on_unexpected_error(self, db, monkeypatch):
        """step 1 抛错时 STATUS 也要标记 (不再静默 leaving running)"""
        from services.quant_pipeline import STATUS, run_pipeline

        import services.quant_pipeline as qp

        # 让 step_1 立即失败
        def fail_step1():
            STATUS.step("1_gp_mining", "running")
            return {"error": "fake step1 error"}

        monkeypatch.setattr(qp, "step_1_gp_mining", fail_step1)

        # 跑 (会很快失败)
        result = run_pipeline()

        # final_status 应该是 'partial' (因为 brief_result error 由后续步骤决定; 这里 step1 error → 整个 done=false)
        assert result.get("status") in ("partial", "done", "failed")
        # STATUS 应该被标 finish (不是永远 running)
        final = STATUS.get()
        assert final.get("status") != "running"
