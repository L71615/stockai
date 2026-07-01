import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.futu_ingest_service import sync_quote, sync_minute_kline, sync_daily_kline


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync futu data into local sqlite")
    parser.add_argument("--code", required=True)
    parser.add_argument("--type", choices=["quote", "minute", "daily"], required=True)
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()

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
