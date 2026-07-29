"""v4.1 1A.4: 定期把 ≥fwd_days 的已决策 proposal 写入 proposal_outcomes

用法:
    python -m scripts.record_retrospectives [--fwd-days 30]

cron / scheduler 调用: 每日 22:30 跑一次
"""
import argparse
import json
import logging
import sys

from services.retrospective_service import run_retrospective_writer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fwd-days", type=int, default=30, help="前向观察天数 (默认 30)")
    args = parser.parse_args()

    result = run_retrospective_writer(fwd_days=args.fwd_days)
    logger.info(
        "retrospective_writer: scanned=%d written=%d skipped_existing=%d errors=%d",
        result["scanned"], result["written"], result["skipped_existing"], len(result["errors"]),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())