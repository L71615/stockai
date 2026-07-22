"""
Daily Quant Pipeline - cron 入口脚本 (v3.10+)

按 plan-ceo-review 2026-07-22 设计:
  每天 18:00 跑一次, 编排 GP 挖 / ML 训 / 过拟合 / 简报 / 推送

Linux/Mac cron 接入 (A 股 15:00 收盘, 18:00 跑):
  0 18 * * 1-5 cd /path/to/stockai && python -m scripts.daily_quant_pipeline >> logs/pipeline.log 2>&1

Windows 任务计划接入:
  触发器: 每天 18:00 (周一-周五)
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
