"""
Daily Quant Pipeline - 自动量化研究编排 (v3.10+)

按 plan-ceo-review 2026-07-22 设计:
  GP 挖 → ML 训 → 过拟合验证 → 衰减告警 → 简报 → 推送

设计原则:
- 复用现有 service (factor_expr / factor_ml / factor_lifecycle)
- 不重写 GP / ML 逻辑,只编排
- 单只股票失败不影响整体 (try/except + skip)
- 进度可查 (pipeline_status 全局)
- 简报保存到 DB + Markdown 文件

v3.11 (T1): pipeline run 状态写数据库, 不只在内存.
  - PipelineStatus 仍然负责进程内实时 telemetry
  - 业务事实 (run 进度/步骤/错误) 通过 experiment_service 持久化
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from database import execute

logger = logging.getLogger(__name__)

# 简报保存目录
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "quant"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class PipelineStatus:
    """全局 pipeline 状态 (线程安全)"""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict = {}

    def reset(self, run_id: str, total_steps: int):
        with self._lock:
            self._state = {
                "run_id": run_id,
                "status": "running",
                "current_step": 0,
                "total_steps": total_steps,
                "steps": [],
                "started_at": datetime.now().isoformat(),
                "finished_at": None,
                "summary": {},
                "errors": [],
            }

    def step(self, name: str, status: str = "running", **details):
        with self._lock:
            if "steps" not in self._state:
                self._state["steps"] = []
            # 如果 details 里传了 status 字段, 用它覆盖参数 (向后兼容)
            if "status" in details:
                status = details.pop("status")
            # 找已存在的 step, 或新增
            existing = next((s for s in self._state["steps"] if s["name"] == name), None)
            if existing:
                existing.update({**details, "status": status, "updated_at": datetime.now().isoformat()})
            else:
                self._state["steps"].append({
                    "name": name,
                    "status": status,
                    "index": len(self._state["steps"]) + 1,
                    "started_at": datetime.now().isoformat(),
                    **details,
                })
            self._state["current_step"] = len(self._state["steps"])

    def error(self, step_name: str, error_msg: str):
        with self._lock:
            if "errors" not in self._state:
                self._state["errors"] = []
            self._state["errors"].append({
                "step": step_name,
                "error": str(error_msg)[:300],
                "ts": datetime.now().isoformat(),
            })

    def finish(self, status: str, summary: dict):
        with self._lock:
            self._state["status"] = status
            self._state["finished_at"] = datetime.now().isoformat()
            self._state["summary"] = summary

    def get(self) -> dict:
        with self._lock:
            return dict(self._state)  # copy


STATUS = PipelineStatus()

# 当前 pipeline run 的 DB row id (set by run_pipeline 开头)
_CURRENT_RUN_ID: Optional[int] = None


# ════════════════════════════════════════════════════════════
#  v3.11 write-through helpers (DB is source of truth for runs)
# ════════════════════════════════════════════════════════════

def _persist_run_start(scope: str, experiment_id: Optional[str], run_label: str) -> int:
    """开一个 experiment_run 行, 返回 run_id (INT PK).

    experiment_id 可为空 (例如 daily pipeline run 不绑定实验).
    """
    cur = execute(
        "INSERT INTO experiment_runs "
        "(experiment_id, scope, status, current_step, started_at, error_json) "
        "VALUES (?, ?, 'running', ?, ?, '{}')",
        (experiment_id, scope, run_label, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return int(cur["lastrowid"])


def _persist_run_step(run_id: Optional[int], step_name: str, status: str, **details):
    """更新 run 行 + 写审计事件."""
    if not run_id:
        return
    execute(
        "UPDATE experiment_runs SET current_step = ?, status = ? WHERE run_id = ?",
        (step_name, status, run_id),
    )
    # 通过 experiment_service 写 append_event
    try:
        from services.experiment_service import append_event
        run_row = execute("SELECT experiment_id FROM experiment_runs WHERE run_id = ?", (run_id,))
        exp_id = (run_row or {}).get("experiment_id") if isinstance(run_row, dict) else None
        if not exp_id:
            return
        append_event(
            experiment_id=exp_id,
            run_id=run_id,
            actor="pipeline",
            event_type=f"step:{status}",
            reason=step_name,
        )
    except Exception as e:  # audit 失败不能阻塞 run
        logger.warning("append_event failed for run %s step %s: %s", run_id, step_name, str(e)[:200])


def _persist_run_finish(run_id: Optional[int], status: str, summary: dict):
    if not run_id:
        return
    execute(
        "UPDATE experiment_runs SET status = ?, current_step = 'finished', "
        "finished_at = ?, error_json = ? WHERE run_id = ?",
        (
            status,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps({"summary": summary}, ensure_ascii=False),
            run_id,
        ),
    )


def _record_step_result(step_name: str, success: bool, error: Optional[str] = None):
    """每步结尾调一次: 写当前 run 的 step 状态 + 审计."""
    global _CURRENT_RUN_ID
    status = "done" if success else "failed"
    _persist_run_step(_CURRENT_RUN_ID, step_name, status)
    if error:
        _persist_run_step(_CURRENT_RUN_ID, f"{step_name}_error", "failed", error=error[:300])


# ════════════════════════════════════════════════════════════
#  5 步编排 (按 plan)
# ════════════════════════════════════════════════════════════

def step_1_gp_mining() -> dict:
    """Step 1: GP 挖因子 (复用 factor_expr.gp_mine)"""
    from services.factor_expr import gp_mine
    STATUS.step("1_gp_mining", "running")
    try:
        result = gp_mine(
            stock_pool="csi800",
            population=15,
            generations=3,
            top_k=10,
            seed=42,
        )
        STATUS.step("1_gp_mining", status="done",
                    candidates=len(result.get("best", [])),
                    best_factors=result.get("best", []),
                    kept=result.get("stats", {}).get("kept", 0))
        return {"candidates": result.get("best", []), "stats": result.get("stats", {})}
    except Exception as e:
        STATUS.error("1_gp_mining", str(e))
        STATUS.step("1_gp_mining", "failed", error=str(e)[:200])
        return {"candidates": [], "stats": {}, "error": str(e)}


def step_2_ml_training() -> dict:
    """Step 2: GP 因子叠加到 ML (复用 factor_ml.train_ml_with_gp_factors)"""
    from services.factor_ml import train_ml_with_gp_factors
    STATUS.step("2_ml_training", "running")
    try:
        result = train_ml_with_gp_factors(
            stock_pool="csi800",
            n_estimators=40,
            max_depth=4,
        )
        STATUS.step("2_ml_training", "done",
                    base_ir=result.get("comparison", {}).get("ir_base"),
                    enhanced_ir=result.get("comparison", {}).get("ir_enhanced"),
                    lift_pct=result.get("comparison", {}).get("ir_lift_pct"))
        return result
    except Exception as e:
        STATUS.error("2_ml_training", str(e))
        STATUS.step("2_ml_training", "failed", error=str(e)[:200])
        return {"error": str(e)}


def step_3_factor_decay() -> dict:
    """Step 3: 因子衰减告警 (复用 factor_lifecycle.update_all_factors)"""
    from services.factor_lifecycle import update_all_factors
    STATUS.step("3_factor_decay", "running")
    try:
        result = update_all_factors()
        # 提取需要告警的因子 (retired 或 warning)
        warnings = []
        if isinstance(result, dict):
            retired = result.get("retired", [])
            if retired:
                warnings.append({
                    "level": "critical",
                    "type": "retired",
                    "factors": retired[:10],
                    "message": f"{len(retired)} 个因子自动退役",
                })
        STATUS.step("3_factor_decay", status="done",
                    warning_count=len(warnings),
                    warnings=warnings,  # 列表详情 (generate_brief 用)
                    retired_count=len(warnings[0]["factors"]) if warnings else 0)
        return {"warnings": warnings, "result": result}
    except Exception as e:
        STATUS.error("3_factor_decay", str(e))
        STATUS.step("3_factor_decay", status="failed", error=str(e)[:200])
        return {"warnings": [], "error": str(e)}


def step_4_data_health() -> dict:
    """Step 4: 数据源健康度 (新增 health_monitor.check_all)"""
    from services.health_monitor import check_all as check_health
    STATUS.step("4_data_health", "running")
    try:
        result = check_health()
        STATUS.step("4_data_health", status="done",
                    health_status=result.get("overall_status"),
                    issues=len(result.get("issues", [])))
        return result
    except Exception as e:
        STATUS.error("4_data_health", str(e))
        STATUS.step("4_data_health", status="failed", error=str(e)[:200])
        return {"overall_status": "unknown", "issues": [], "error": str(e)}


def step_5_brief_and_notify() -> dict:
    """Step 5: 生成简报 + 推送 (邮件 + Telegram)"""
    from services.quant_brief import generate_brief, save_brief
    from services.notify_service import send_notification
    STATUS.step("5_brief_notify", "running")
    try:
        # 1. 生成简报
        state = STATUS.get()
        steps_data = {s["name"]: s for s in state.get("steps", [])}

        # race condition 修复: generate_brief 看到的状态汇总里 5_brief_notify 应为 done
        if "5_brief_notify" in steps_data:
            steps_data["5_brief_notify"]["status"] = "done"

        brief_md = generate_brief(steps_data=steps_data)
        brief_id = save_brief(brief_md)

        # v3.11 (T8 D7): 通知失败不掩盖研究状态
        # 先记研究结论为 done, 再尝试通知 (通知失败只标 notify_ok=False)
        notify_result = send_notification(
            markdown=(brief_md if isinstance(brief_md, str) else str(brief_md))[:1500] + "\n\n完整简报: /api/pipeline/brief",
            title=f"StockAI 量化日报 {datetime.now().strftime('%Y-%m-%d')}",
            run_id=state.get("run_id", ""),
        )

        STATUS.step("5_brief_notify", "done",
                    brief_id=brief_id,
                    notify_ok=notify_result.get("sent", False),
                    notify_channels=notify_result.get("channels", {}))
        return {"brief_id": brief_id, "notify": notify_result}
    except Exception as e:
        STATUS.error("5_brief_notify", str(e))
        STATUS.step("5_brief_notify", "failed", error=str(e)[:200])
        return {"brief_id": None, "error": str(e)}


# ════════════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════════════

def run_pipeline() -> dict:
    """跑完整 pipeline (5 步)

    v3.11 (T8): 加单飞锁 (pipeline_lock scope='pipeline_daily') + feature flag gate.
    已有的 run 在跑时, 第二次调用立即返回旧 status, 不重复触发.
    """
    from services.feature_flag_service import is_enabled as flag_is_enabled
    from services.experiment_service import (
        acquire_pipeline_lock, release_pipeline_lock,
    )

    # v3.11 (T8): feature flag gate — 全 OFF 走兼容路径 (不写 DB)
    flags = {
        "pipeline_daily": flag_is_enabled("pipeline.shadow.enabled"),
    }

    run_id = f"qp-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    logger.info("Pipeline start: %s (flags=%s)", run_id, flags)
    STATUS.reset(run_id, total_steps=5)
    t0 = time.time()

    # 单飞锁: 同 scope 只有一个 worker 跑
    holder_pid = f"run_pipeline-{uuid.uuid4().hex[:8]}"
    if not acquire_pipeline_lock("pipeline_daily", holder_pid=holder_pid, ttl_seconds=1800):
        logger.warning("pipeline_daily lock held by other worker, skipping")
        return {
            "run_id": run_id, "status": "skipped",
            "reason": "another worker already running pipeline_daily",
        }

    # write-through — DB 是事实源
    global _CURRENT_RUN_ID
    try:
        _CURRENT_RUN_ID = _persist_run_start(
            scope="pipeline_daily", experiment_id=None, run_label=run_id
        )

        # 按顺序跑 (每步独立 try/except, 失败不影响下一步)
        try:
            gp_result = step_1_gp_mining()
            _record_step_result("1_gp_mining", success="error" not in gp_result, error=gp_result.get("error"))

            ml_result = step_2_ml_training()
            _record_step_result("2_ml_training", success="error" not in ml_result, error=ml_result.get("error"))

            decay_result = step_3_factor_decay()
            _record_step_result("3_factor_decay", success="error" not in decay_result, error=decay_result.get("error"))

            health_result = step_4_data_health()
            _record_step_result("4_data_health", success="error" not in health_result, error=health_result.get("error"))

            brief_result = step_5_brief_and_notify()
            _record_step_result("5_brief_notify", success="error" not in brief_result, error=brief_result.get("error"))
        finally:
            finished_run_id = _CURRENT_RUN_ID
            _CURRENT_RUN_ID = None

        elapsed = time.time() - t0
        summary = {
            "elapsed_s": round(elapsed, 1),
            "gp_candidates": len(gp_result.get("candidates", [])),
            "ml_ir_lift_pct": ml_result.get("comparison", {}).get("ir_lift_pct"),
            "decay_warnings": len(decay_result.get("warnings", [])),
            "health_status": health_result.get("overall_status"),
            "brief_id": brief_result.get("brief_id"),
            "notify_ok": brief_result.get("notify", {}).get("sent", False),
            "flags": flags,
        }
        final_status = "done" if not brief_result.get("error") else "partial"
        STATUS.finish(final_status, summary)
        _persist_run_finish(finished_run_id, final_status, summary)
        logger.info("Pipeline %s: %s in %.1fs", run_id, final_status, elapsed)
        return STATUS.get()
    finally:
        release_pipeline_lock("pipeline_daily", holder_pid=holder_pid)


# ════════════════════════════════════════════════════════════
#  CLI 入口 (供 cron / 手动调用)
# ════════════════════════════════════════════════════════════

def main():
    """CLI 入口: python -m services.quant_pipeline"""
    import sys
    import json
    result = run_pipeline()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
