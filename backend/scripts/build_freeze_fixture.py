"""freeze fixture builder — 生成 frozen snapshot demo 数据

用法:
    python -m backend.scripts.build_freeze_fixture --output tests/fixtures/freeze_demo.json

输出 JSON 结构:
{
  "experiment_id": "exp-fixture-demo",
  "as_of_date": "2026-07-24",
  "stock_pool": [...],
  "stock_pool_source": "csi800",
  "kline_window": {"start": "...", "end": "...", "count": 250},
  "factor_values": {"600519": 0.045, "000858": -0.012, ...},
  "equity_curve": [{"date": "...", "value": 100500.0}, ...],
  "trades": [{"date": "...", "code": "600519", "direction": "buy", ...}, ...],
  "config": {"policy_version": "v1.0.0", "cost_bps": 30, "rebalance": "weekly"},
  "validation_window": {"start": "2024-01-01", "end": "2026-07-24"},
  "oos_window": {"start": "2025-09-01", "end": "2026-07-24"}
}

fixture 故意构造:
  - 60 个交易日的 equity_curve, 单调上升 (稳赚)
  - trade dates 全部 ≤ as_of_date
  - factor values 范围 [-0.1, 0.1]
  - 不含未来行, 测试用例故意构造 future row 用来验证 leakage 检测
"""
from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path


def _trading_days(start: str, end: str) -> list[str]:
    """简化交易日列表: 跳过周末"""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    days = []
    cur = s
    while cur <= e:
        if cur.weekday() < 5:  # Mon-Fri
            days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def build_fixture(*, as_of_date: str = "2026-07-24", seed: int = 42) -> dict:
    """构造一个 demo freeze snapshot."""
    rng = random.Random(seed)

    pool = [
        "600519", "000858", "000001", "600036", "601318",
        "601398", "600000", "601628", "600276", "002415",
    ]

    # 60 个交易日
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    days = []
    cur = end
    for _ in range(60):
        while cur.weekday() >= 5:
            cur -= timedelta(days=1)
        days.append(cur.strftime("%Y-%m-%d"))
        cur -= timedelta(days=1)
    days.reverse()  # 升序

    # equity_curve: 单调 + 一点点噪声
    initial = 100000.0
    curve = []
    val = initial
    for i, d in enumerate(days):
        ret = 0.001 + rng.uniform(-0.005, 0.012)  # 平均日 0.1%, 偶尔亏
        val *= (1 + ret)
        curve.append({"date": d, "value": round(val, 2)})

    # trades: 每周一笔买入
    trades = []
    for i in range(0, len(days), 5):
        d = days[i]
        code = rng.choice(pool)
        price = rng.uniform(10, 200)
        shares = 100
        trades.append({
            "date": d,
            "code": code,
            "direction": "buy",
            "price": round(price, 2),
            "shares": shares,
        })

    # factor values: 每只股票一个 IC 排名分
    factor_values = {c: round(rng.uniform(-0.1, 0.1), 4) for c in pool}

    return {
        "experiment_id": "exp-fixture-demo",
        "as_of_date": as_of_date,
        "stock_pool": pool,
        "stock_pool_source": "csi800",
        "kline_window": {
            "start": days[0],
            "end": days[-1],
            "count": len(days),
        },
        "factor_values": factor_values,
        "equity_curve": curve,
        "trades": trades,
        "config": {
            "policy_version": "v1.0.0",
            "cost_bps": 30,
            "rebalance": "weekly",
            "initial_cash": initial,
        },
        "validation_window": {"start": days[0], "end": days[-1]},
        "oos_window": {"start": days[len(days) // 2], "end": days[-1]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="build freeze fixture JSON")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "freeze_demo.json"),
        help="output JSON path",
    )
    parser.add_argument("--as-of", default="2026-07-24", help="as_of_date (YYYY-MM-DD)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    fixture = build_fixture(as_of_date=args.as_of, seed=args.seed)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[freeze_fixture] wrote {out_path} ({len(fixture['equity_curve'])} days, {len(fixture['trades'])} trades)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())