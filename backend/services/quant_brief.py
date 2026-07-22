"""
Quant Daily Brief - Markdown 简报生成 (v3.10+)

按 plan-ceo-review 2026-07-22:
  每天 18:00 cron 跑 pipeline → 生成简报 → 推送邮件/Telegram

简报内容:
  - Top 10 新因子 (含 train/test sharpe)
  - 衰减告警 (IC 下降的因子)
  - 数据源健康度
  - 推送状态
"""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 简报 DB 表
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "quant"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_brief(steps_data: dict) -> str:
    """根据 pipeline 5 步输出生成 Markdown 简报

    Args:
        steps_data: quant_pipeline.run_pipeline() 返回的 steps 列表
                   [{name, status, ...}, ...]

    Returns:
        Markdown 格式简报
    """
    today = datetime.now().strftime('%Y-%m-%d')
    md = [f"# StockAI 量化日报 - {today}\n"]

    # ── 摘要 ──
    md.append("## 📊 摘要\n")
    gp_step = _find_step(steps_data, "1_gp_mining")
    ml_step = _find_step(steps_data, "2_ml_training")
    decay_step = _find_step(steps_data, "3_factor_decay")
    health_step = _find_step(steps_data, "4_data_health")

    gp_count = gp_step.get("candidates", 0) if gp_step else 0
    ml_lift = ml_step.get("lift_pct", "N/A") if ml_step else "N/A"
    decay_warns = len(decay_step.get("warnings", [])) if decay_step else 0
    health_status = health_step.get("status", "unknown") if health_step else "unknown"

    md.append(f"- **GP 挖因子**: {gp_count} 个候选")
    md.append(f"- **ML 训练**: train→test IR 提升 **{ml_lift}%**")
    md.append(f"- **衰减告警**: {decay_warns} 个因子需要关注")
    md.append(f"- **数据源健康**: {health_status}")
    md.append("")

    # ── GP 候选 ──
    md.append("## 🧬 新挖因子 (Top 10)\n")
    if gp_step and gp_step.get("candidates"):
        md.append("| 因子表达式 | IR | 备注 |")
        md.append("|---|---|---|")
        for c in gp_step["candidates"][:10]:
            expr = c.get("expr_text", "")[:60]
            ir = c.get("ir", 0)
            md.append(f"| `{expr}...` | {ir:.3f} | - |")
    else:
        md.append("_本次 GP 未产出候选_\n")
    md.append("")

    # ── 衰减告警 ──
    md.append("## ⚠️ 衰减告警\n")
    if decay_step and decay_step.get("warnings"):
        for w in decay_step["warnings"]:
            md.append(f"### {w.get('level', '?').upper()}: {w.get('message', '')}\n")
            for f in w.get("factors", [])[:5]:
                md.append(f"- `{f}`")
            md.append("")
    else:
        md.append("_本次未检测到衰减告警_\n")
    md.append("")

    # ── 数据源健康 ──
    md.append("## 🏥 数据源健康\n")
    if health_step:
        md.append(f"- **整体状态**: {health_step.get('status', 'unknown')}")
        issues = health_step.get("issues", [])
        if issues:
            md.append(f"- **问题数**: {len(issues)}")
            for issue in issues[:5]:
                md.append(f"  - {issue}")
        else:
            md.append("- **问题数**: 0")
    else:
        md.append("_未获取到健康度数据_\n")
    md.append("")

    # ── 状态汇总 ──
    md.append("## 📈 状态汇总\n")
    if steps_data:
        for step in steps_data:
            name = step.get("name", "?")
            status = step.get("status", "?")
            emoji = "✅" if status == "done" else "❌" if status == "failed" else "⏳"
            md.append(f"- {emoji} `{name}`: {status}")
    md.append("")

    return "\n".join(md)


def _find_step(steps_data, name: str) -> dict:
    """从 steps_data 找特定 step 的输出"""
    if isinstance(steps_data, list):
        for s in steps_data:
            if s.get("name") == name:
                return s
    elif isinstance(steps_data, dict):
        return steps_data.get(name, {})
    return {}


def save_brief(markdown: str) -> str:
    """保存简报到 DB + Markdown 文件

    Returns:
        brief_id (str): 时间戳 ID
    """
    from database import execute
    brief_id = f"brief-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # 1. 保存到 Markdown 文件
    md_path = REPORTS_DIR / f"{brief_id}.md"
    md_path.write_text(markdown, encoding="utf-8")

    # 2. 保存到 DB (quant_briefs 表)
    try:
        execute(
            "INSERT INTO quant_briefs (id, content_md, created_at) VALUES (?, ?, ?)",
            (brief_id, markdown, datetime.now().isoformat()),
        )
    except Exception as e:
        logger.warning("保存简报到 DB 失败 (表可能不存在): %s", e)

    return brief_id


def get_latest_brief() -> Optional[dict]:
    """获取最新简报"""
    from database import query_one
    try:
        row = query_one(
            "SELECT id, content_md, created_at FROM quant_briefs ORDER BY created_at DESC LIMIT 1"
        )
        if row:
            return dict(row)
    except Exception as e:
        logger.warning("读最新简报失败: %s", e)
    return None


def list_briefs(limit: int = 20) -> list:
    """列出最近简报"""
    from database import query_all
    try:
        rows = query_all(
            "SELECT id, created_at FROM quant_briefs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("列简报失败: %s", e)
    return []
