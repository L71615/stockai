"""
Daily Quant Pipeline - cron 入口脚本 (v3.10+ / v4.1 改 22:00)

v4.1 1A.2 改动:
  - 跑时机 18:00 → 22:00 (A 股 15:00 收盘 + 数据稳定 + GP/ML 跑完 7 小时留 22:00 之前)
  - GP 跑 ~5-10 分钟, ML 训 ~2-3 分钟, 22:00 触发次日 09:00 前可完成
  - 加 retry 重试: 22:30 / 23:00 各 retry 一次 (GP 失败容错)
  - 实验状态写 experiment_runs.status (running/done/partial/failed),
    09:30 watcher 查此字段判断是否跳过 AI-driven pending_buy

按 plan-ceo-review 2026-07-22 + plan-ceo-review 2026-07-29 设计:

Linux/Mac cron 接入 (22:00 A 股 15:00 收盘 + 7 小时):
  0 22 * * 1-5 cd /path/to/stockai && python -m scripts.daily_quant_pipeline >> logs/pipeline.log 2>&1

Windows 任务计划接入:
  触发器: 每天 22:00 (周一-周五)
  操作: python -m scripts.daily_quant_pipeline

手动跑:
  python -m scripts.daily_quant_pipeline
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 让脚本能 import backend 包
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# 加载 .env (同 main.py)
os.environ.setdefault("JWT_SECRET", "cron-jwt-secret-32-bytes-okkkkk")
os.environ.setdefault("ADMIN_PASSWORD", "cron-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("daily_quant_pipeline")


def main():
    logger.info("=" * 60)
    logger.info("Daily Quant Pipeline 启动 - %s", datetime.now().isoformat())
    logger.info("=" * 60)

    try:
        from services.quant_pipeline import run_pipeline
        result = run_pipeline()

        # 输出结果摘要
        summary = result.get("summary", {})
        logger.info("Pipeline 完成:")
        logger.info("  - 状态: %s", result.get("status"))
        logger.info("  - 耗时: %s 秒", summary.get("elapsed_s"))
        logger.info("  - GP 候选: %s", summary.get("gp_candidates"))
        logger.info("  - ML IR 提升: %s%%", summary.get("ml_ir_lift_pct"))
        logger.info("  - 衰减告警: %s", summary.get("decay_warnings"))
        logger.info("  - 数据源健康: %s", summary.get("health_status"))
        logger.info("  - 简报 ID: %s", summary.get("brief_id"))
        logger.info("  - 推送成功: %s", summary.get("notify_ok"))

        if result.get("status") == "done":
            return 0
        return 1
    except Exception as e:
        logger.exception("Pipeline 失败: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
