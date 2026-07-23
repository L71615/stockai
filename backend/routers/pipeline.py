"""
Pipeline Router - 自动量化研究 pipeline API (v3.10+)

按 plan-ceo-review 2026-07-22:
  端点: GET /status / GET /brief / GET /briefs / POST /run
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from services.quant_pipeline import STATUS, run_pipeline
from services.quant_brief import get_latest_brief, list_briefs
from services.health_monitor import check_all as check_health

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pipeline", tags=["Pipeline"])


@router.get("/status")
def get_status():
    """获取当前 pipeline 状态 (5 步进度)"""
    state = STATUS.get()
    if not state:
        return {"status": "idle", "message": "Pipeline 未运行, 调 POST /run 触发"}
    return state


@router.post("/run")
def trigger_run():
    """手动触发一次 pipeline (后台跑, 用真后台线程避免阻塞事件循环)"""
    state = STATUS.get()
    if state.get("status") == "running":
        raise HTTPException(409, f"Pipeline 正在跑 ({state.get('run_id', '?')}), 完成后重试")

    def _worker():
        try:
            run_pipeline()
        except Exception as e:
            logger.exception("Pipeline 后台跑失败: %s", e)

    # 用 daemon 线程而不是 BackgroundTasks —
    # BackgroundTasks 会占满 starlette anyio threadpool (默认 40),
    # 阻塞所有后续请求的事件循环, 直到 5 分钟 pipeline 跑完
    # daemon 线程完全独立于事件循环, 跑死也不影响 HTTP 服务
    threading.Thread(target=_worker, daemon=True).start()
    return {
        "message": "Pipeline 已在后台启动, 用 GET /status 查进度",
        "started_at": datetime.now().isoformat(),
    }


@router.get("/brief")
def get_brief():
    """获取最新简报 (Markdown 内容)"""
    brief = get_latest_brief()
    if not brief:
        raise HTTPException(404, "暂无简报, 请先 POST /api/pipeline/run")
    return brief


@router.get("/briefs")
def get_briefs_list(limit: int = 20):
    """列出最近简报"""
    briefs = list_briefs(limit=limit)
    return {"count": len(briefs), "briefs": briefs}


@router.get("/health")
def get_health():
    """数据源健康度 (akshare + Futu + DB)"""
    return check_health()
