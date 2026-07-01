import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
os.environ.setdefault("JWT_SECRET", "stockai-script-jwt-secret-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "stockai-script-admin-password")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")

sys.path.insert(0, str(BASE_DIR))

from database import init_db
from services.futu_ingest_service import sync_quote, sync_minute_kline, sync_daily_kline


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync futu data into local sqlite")
    parser.add_argument("--code", required=True)
    parser.add_argument("--type", choices=["quote", "minute", "daily"], required=True)
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()

    init_db()

    if args.type == "quote":
        result = sync_quote(args.code)
    elif args.type == "minute":
        result = sync_minute_kline(args.code, count=args.count)
    else:
        result = sync_daily_kline(args.code, count=args.count)

    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
