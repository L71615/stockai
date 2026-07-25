"""因子生命周期管理 — 自动评估/告警/退役 (v3.11+)

规则 (从 validation_policy 读, 不再写死):
  IR >= ir_active            → active
  0 <= IR < ir_active        → warning (累加 warning_days)
  warning_days >= policy.warning_days_retire → retired

表: factor_lifecycle_status (factor_name PK)
"""
import logging
from datetime import datetime, timedelta

from database import query_all, execute

logger = logging.getLogger(__name__)


# 向后兼容: 旧调用方可能引用这些常量, 启动时从 policy 注入
IR_ACTIVE = 0.15
IR_WARNING = 0.05
WARNING_DAYS_RETIRE = 14
EVAL_DAYS = 120


def _load_thresholds_into_globals() -> None:
    """从 policy 读阈值写到模块全局, 兼容老代码引用 IR_ACTIVE 等常量."""
    global IR_ACTIVE, IR_WARNING, WARNING_DAYS_RETIRE, EVAL_DAYS
    try:
        from services.validation_policy import get_current_policy
        p = get_current_policy()
        IR_ACTIVE = p.ir_active
        IR_WARNING = p.ir_warning
        WARNING_DAYS_RETIRE = p.warning_days_retire
        EVAL_DAYS = p.eval_days
    except Exception as e:
        logger.debug("policy 加载失败, 用模块默认值: %s", str(e)[:200])


# 启动时尝试同步一次 (失败用默认值)
_load_thresholds_into_globals()


def evaluate_factor(factor_name: str, end_date: str = None, days: int = EVAL_DAYS) -> dict:
    """对单个因子跑最近 N 天 IC, 返回指标"""
    from services.factor_lab import (
        get_stock_pool, load_kline_panel, compute_factor_metrics, FACTOR_REGISTRY
    )

    if factor_name not in FACTOR_REGISTRY:
        return {"error": f"未知因子: {factor_name}"}

    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days + 60)).strftime("%Y-%m-%d")

    # 用 csi800 池 (速度 + 稳定性平衡)
    stock_codes = get_stock_pool("csi800")
    panels = load_kline_panel(stock_codes, start_date, end_date)
    if not panels:
        return {"error": "数据不足"}

    try:
        result = compute_factor_metrics([factor_name], "csi800", start_date, end_date)
        m = result.get("factors", {}).get(factor_name)
        if not m:
            return {"error": "无指标结果"}
        return {
            "factor_name": factor_name,
            "ic_mean": m.get("ic_mean", 0),
            "ir": m.get("ir", 0),
            "win_rate": m.get("win_rate", 0),
            "valid_days": m.get("valid_days", 0),
        }
    except Exception as e:
        logger.warning("evaluate_factor(%s) failed: %s", factor_name, str(e)[:200])
        return {"error": str(e)[:200]}


def classify(ir: float, warning_days: int) -> str:
    """根据 IR 和连续 warning 天数, 返回状态 (委托给 validation_policy)."""
    from services.validation_policy import classify_lifecycle
    return classify_lifecycle(ir, warning_days)


def update_all_factors() -> dict:
    """评估所有内置因子, 更新 lifecycle_status 表

    Returns:
        {updated, statuses, retired, warnings, thresholds{policy_version, policy_hash}, evaluated_at}
    """
    from services.factor_lab import FACTOR_REGISTRY
    from services.validation_policy import get_current_policy, compute_next_warning_days

    p = get_current_policy()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 读已有状态 (用来算 warning_days 累计)
    existing = {
        r["factor_name"]: r
        for r in query_all(
            "SELECT factor_name, status, warning_days FROM factor_lifecycle_status"
        )
    }

    updated = 0
    statuses = {}
    retired_list = []
    new_warnings = []

    for factor_name in FACTOR_REGISTRY.keys():
        result = evaluate_factor(factor_name)
        if "error" in result:
            logger.warning("skip %s: %s", factor_name, result["error"])
            continue

        ir = result.get("ir", 0)
        ic = result.get("ic_mean", 0)
        win_rate = result.get("win_rate", 0)
        prev = existing.get(factor_name, {})
        prev_status = prev.get("status", "active")
        prev_warning_days = prev.get("warning_days", 0) or 0

        new_warning_days = compute_next_warning_days(ir, prev_status, prev_warning_days)
        status = classify(ir, new_warning_days)

        # 备注 (含 policy version 便于审计)
        note = ""
        if status == "retired":
            note = (f"IR={ir:.3f} 连续 {new_warning_days} 天低于阈值 "
                    f"(IR<{p.ir_warning}, policy={p.version})")
            retired_list.append(factor_name)
        elif status == "warning":
            note = (f"IR={ir:.3f} 接近退役阈值 "
                    f"({new_warning_days}/{p.warning_days_retire} 天, policy={p.version})")
            new_warnings.append(factor_name)
        elif status == "active":
            note = f"IR={ir:.3f} 胜率={win_rate:.2%} (policy={p.version})"

        # 写表 (ic_current 字段在 schema 里是 ic_current, 沿用)
        try:
            execute(
                """INSERT INTO factor_lifecycle_status
                   (factor_name, status, ic_current, ir_current, warning_days, last_check, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(factor_name) DO UPDATE SET
                     status=excluded.status,
                     ic_current=excluded.ic_current,
                     ir_current=excluded.ir_current,
                     warning_days=excluded.warning_days,
                     last_check=excluded.last_check,
                     note=excluded.note""",
                (factor_name, status, ic, ir, new_warning_days, now, note),
            )
            statuses[factor_name] = status
            updated += 1
        except Exception as e:
            logger.warning("write %s failed: %s", factor_name, str(e)[:200])

    return {
        "updated": updated,
        "statuses": statuses,
        "retired": retired_list,
        "warnings": new_warnings,
        "thresholds": {
            "ir_active": p.ir_active,
            "ir_warning": p.ir_warning,
            "warning_days_retire": p.warning_days_retire,
            "eval_days": p.eval_days,
            "policy_version": p.version,
            "policy_hash": p.hash(),
        },
        "evaluated_at": now,
    }


def get_all_statuses() -> list[dict]:
    """获取所有因子的当前状态"""
    return query_all(
        "SELECT factor_name, status, ic_current, ir_current, warning_days, last_check, note "
        "FROM factor_lifecycle_status ORDER BY "
        "CASE status WHEN 'retired' THEN 2 WHEN 'warning' THEN 1 ELSE 0 END, "
        "factor_name"
    )


def reset_factor(factor_name: str) -> bool:
    """手动重置因子状态 (例如发现误判时)"""
    cur = execute(
        "UPDATE factor_lifecycle_status SET warning_days=0, status='active', "
        "note='手动重置' WHERE factor_name = ?",
        (factor_name,),
    )
    return cur.rowcount > 0 if hasattr(cur, "rowcount") else True