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
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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
        # 收集前面 4 步的输出
        state = STATUS.get()
        steps_data = {s["name"]: s for s in state.get("steps", [])}

        brief_md = generate_brief(steps_data=steps_data)
        brief_id = save_brief(brief_md)

        # 2. 推送
        notify_result = send_notification(
            markdown=(brief_md if isinstance(brief_md, str) else str(brief_md))[:1500] + "\n\n完整简报: /api/pipeline/brief",
            title=f"StockAI 量化日报 {datetime.now().strftime('%Y-%m-%d')}",
        )

        STATUS.step("5_brief_notify", "done",
                    brief_id=brief_id,
                    notify_ok=notify_result.get("ok", False))
        return {"brief_id": brief_id, "notify": notify_result}
    except Exception as e:
        STATUS.error("5_brief_notify", str(e))
        STATUS.step("5_brief_notify", "failed", error=str(e)[:200])
        return {"brief_id": None, "error": str(e)}


# ════════════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════════════

def run_pipeline() -> dict:
    """跑完整 pipeline (5 步)"""
    run_id = f"qp-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    logger.info("Pipeline start: %s", run_id)
    STATUS.reset(run_id, total_steps=5)
    t0 = time.time()

    # 按顺序跑 (每步独立 try/except, 失败不影响下一步)
    gp_result = step_1_gp_mining()
    ml_result = step_2_ml_training()
    decay_result = step_3_factor_decay()
    health_result = step_4_data_health()
    brief_result = step_5_brief_and_notify()

    elapsed = time.time() - t0
    summary = {
        "elapsed_s": round(elapsed, 1),
        "gp_candidates": len(gp_result.get("candidates", [])),
        "ml_ir_lift_pct": ml_result.get("comparison", {}).get("ir_lift_pct"),
        "decay_warnings": len(decay_result.get("warnings", [])),
        "health_status": health_result.get("overall_status"),
        "brief_id": brief_result.get("brief_id"),
        "notify_ok": brief_result.get("notify", {}).get("ok", False),
    }
    final_status = "done" if not brief_result.get("error") else "partial"
    STATUS.finish(final_status, summary)
    logger.info("Pipeline %s: %s in %.1fs", run_id, final_status, elapsed)
    return STATUS.get()


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
