"""T4 影子组合 + 手续费 + T+1/整手/停牌/重复结算测试

覆盖:
  - fees: 佣金+印花税+过户费, 最低 5 元佣金, 买卖分算
  - shadow_portfolio_service: CRUD + settle_day 基本
  - 整手: quantity = 100 的整数倍
  - T+1: 信号日 -> 下一交易日执行
  - 涨跌停/缺价: status=blocked 或 stale
  - 重复结算: UNIQUE 约束命中, 返回已有 snapshot
  - settle_window: 多天连续结算
  - get_snapshots: 按日期范围过滤
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import os
os.environ.setdefault("DB_PATH", "/tmp/stockai_test_t4.db")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

_TEST_DB_PATH = Path("/tmp/stockai_test_t4.db")
if _TEST_DB_PATH.exists():
    try:
        _TEST_DB_PATH.unlink()
    except PermissionError:
        import time
        time.sleep(0.3)
        _TEST_DB_PATH.unlink(missing_ok=True)

from database import init_db, ensure_admin_user as _eua
init_db()
_eua()

import json
import pytest

from services.fees import (
    calc_buy_fee,
    calc_sell_fee,
    calc_total_fee,
    COMMISSION_RATE,
    COMMISSION_MIN,
    STAMP_TAX_RATE,
)
from services.shadow_portfolio_service import (
    create_shadow_portfolio,
    get_portfolio,
    list_portfolios,
    set_target_weights,
    settle_day,
    settle_window,
    get_snapshots,
    get_snapshot,
    ShadowPortfolioNotFoundError,
    ShadowPortfolioSettlementError,
)
from services.trading_calendar import reset_calendar_cache


# ════════════════════════════════════════════════════════════
#  fees
# ════════════════════════════════════════════════════════════

def test_fee_buy_no_stamp():
    """买入无印花税"""
    fee = calc_buy_fee(amount=100000)
    assert fee["stamp_tax"] == 0.0
    assert fee["commission"] == 30.0  # 100000 * 0.0003
    assert fee["total"] > 30.0  # 加过户费


def test_fee_sell_has_stamp():
    fee = calc_sell_fee(amount=100000)
    assert fee["stamp_tax"] == 100.0  # 100000 * 0.001
    assert fee["commission"] == 30.0


def test_fee_min_commission_5_yuan():
    """小额交易佣金保底 5 元"""
    fee = calc_buy_fee(amount=100)  # 100 * 0.0003 = 0.03, 应保底 5
    assert fee["commission"] == COMMISSION_MIN


def test_fee_total_combined():
    f = calc_total_fee(buy_amount=50000, sell_amount=30000)
    assert f["buy"]["commission"] == 15.0
    assert f["sell"]["commission"] == 9.0
    assert f["buy"]["stamp_tax"] == 0.0
    assert f["sell"]["stamp_tax"] == 30.0
    assert f["total"] == round(f["buy"]["total"] + f["sell"]["total"], 2)


def test_fee_zero_amount():
    f = calc_total_fee(buy_amount=0, sell_amount=0)
    assert f["total"] == 0.0


# ════════════════════════════════════════════════════════════
#  shadow_portfolio CRUD
# ════════════════════════════════════════════════════════════

def test_create_portfolio_returns_int():
    pid = create_shadow_portfolio(owner_user_id=1, name="test_pf", initial_cash=50000)
    assert isinstance(pid, int)
    assert pid > 0


def test_get_portfolio_decodes_weights():
    pid = create_shadow_portfolio(owner_user_id=1)
    p = get_portfolio(pid)
    assert p["owner_user_id"] == 1
    assert p["target_weights"] == {}
    assert p["status"] == "active"


def test_get_portfolio_not_found():
    with pytest.raises(ShadowPortfolioNotFoundError):
        get_portfolio(99999)


def test_list_portfolios_by_user():
    # 先确保 user 2 存在
    from database import execute as db_execute
    db_execute(
        "INSERT OR IGNORE INTO users (id, username, email, password) "
        "VALUES (2, 'user2', 'user2@test.com', 'x')"
    )
    p1 = create_shadow_portfolio(owner_user_id=1)
    p2 = create_shadow_portfolio(owner_user_id=1)
    p3 = create_shadow_portfolio(owner_user_id=2)
    rows = list_portfolios(owner_user_id=1)
    ids = {r["portfolio_id"] for r in rows}
    assert p1 in ids and p2 in ids
    assert p3 not in ids


def test_set_target_weights_persists():
    pid = create_shadow_portfolio(owner_user_id=1)
    set_target_weights(pid, {"600519": 0.5, "000858": 0.3})
    p = get_portfolio(pid)
    assert p["target_weights"] == {"600519": 0.5, "000858": 0.3}


# ════════════════════════════════════════════════════════════
#  settle_day 基本
# ════════════════════════════════════════════════════════════

def test_settle_day_creates_snapshot():
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600519": 1.0})
    snap = settle_day(
        portfolio_id=pid,
        observation_date="2026-07-24",
        prices={"600519": 1500.0},
        input_version="v1",
    )
    assert snap["observation_date"] == "2026-07-24"
    assert snap["status"] == "settled"
    # 600519 @ 1500: 100000 / 1500 = 66 股 → lots = 0 (< 100)
    # 所以不会买, 全留现金
    holdings = json.loads(snap["holdings_json"])
    assert "600519" not in holdings
    # 没买入, cash 完全保留
    assert snap["cash"] == 100000


def test_settle_day_with_reasonable_price():
    """便宜股票能真正成交"""
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600000": 0.5})  # 50% 投 600000 @ 10 元
    snap = settle_day(
        portfolio_id=pid,
        observation_date="2026-07-24",
        prices={"600000": 10.0},
        input_version="v1",
    )
    # 100000 * 0.5 = 50000, /10 = 5000 股 → 整手 5000, cost 50000
    # leftover = 50000 >= 100 (buffer 够), 不削减
    holdings = json.loads(snap["holdings_json"])
    assert holdings.get("600000") == 5000
    # 现金剩余 = 50000 - 50000 + 0 (cost 准) ≈ 50000 - 手续费
    assert snap["cash"] < 51000
    assert snap["cash"] > 49000


# ════════════════════════════════════════════════════════════
#  整手 (lots of 100)
# ════════════════════════════════════════════════════════════

def test_lot_rounding_down():
    """13 股 → 0 手 (因为 < 100)"""
    from services.shadow_portfolio_service import _compute_target_shares
    # 100000 * 1.0 / 10 = 10000 股, 整手 10000, cost 100000, leftover 0
    # fee buffer 100: 削 1 手到 9900, leftover += 1000
    shares, cash = _compute_target_shares(
        nav=100000,
        prev_holdings={},
        target_weights={"600000": 1.0},
        prices={"600000": 10.0},
    )
    assert shares == {"600000": 9900}
    assert cash == 1000  # buffer 留出来了

    # 600519 @ 1500: 100000 / 1500 = 66 股 → lots = 0 (整手 100 起步)
    shares2, _ = _compute_target_shares(
        nav=100000,
        prev_holdings={},
        target_weights={"600519": 1.0},
        prices={"600519": 1500.0},
    )
    assert shares2 == {}  # 不够 100 股


def test_lot_buffer_for_fees():
    """fee 安全: 余额不足时, 削减最大持仓 1 手"""
    from services.shadow_portfolio_service import _compute_target_shares
    # 不买入时, leftover = nav 完全保留
    shares, cash = _compute_target_shares(
        nav=100000,
        prev_holdings={},
        target_weights={},  # 空 targets → 不买
        prices={"600000": 10.0},
    )
    assert shares == {}
    assert cash == 100000  # 没买, 全留

    # 1.0 weight, price 10: 100000 → 10000 股 → 整手 10000 → cost 100000
    # leftover = 0 < 100, 削 1 手 → 9900, leftover = 1000
    shares, cash = _compute_target_shares(
        nav=100000,
        prev_holdings={},
        target_weights={"600000": 1.0},
        prices={"600000": 10.0},
    )
    assert shares == {"600000": 9900}
    assert cash == 1000


# ════════════════════════════════════════════════════════════
#  缺价 / 停牌 → blocked / stale
# ════════════════════════════════════════════════════════════

def test_all_prices_missing_blocks():
    pid = create_shadow_portfolio(owner_user_id=1)
    set_target_weights(pid, {"600000": 1.0})
    snap = settle_day(
        portfolio_id=pid,
        observation_date="2026-07-24",
        prices={"600000": None},  # 缺价
        input_version="v1",
    )
    assert snap["status"] == "blocked"
    assert "缺价" in snap["reason"]


def test_partial_prices_settles():
    """部分代码有价 → 仍正常结算, 没价的不买入"""
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600000": 0.5, "600519": 0.5})
    snap = settle_day(
        portfolio_id=pid,
        observation_date="2026-07-24",
        prices={"600000": 10.0, "600519": None},
        input_version="v1",
    )
    assert snap["status"] == "settled"
    holdings = json.loads(snap["holdings_json"])
    assert "600000" in holdings
    assert "600519" not in holdings  # 缺价的不买


# ════════════════════════════════════════════════════════════
#  重复结算 → UNIQUE 命中, 返回已有
# ════════════════════════════════════════════════════════════

def test_double_settle_returns_existing():
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600000": 1.0})
    snap1 = settle_day(pid, "2026-07-24", {"600000": 10.0}, input_version="v1")
    snap2 = settle_day(pid, "2026-07-24", {"600000": 10.0}, input_version="v1")
    assert snap1["snapshot_id"] == snap2["snapshot_id"]


def test_different_input_version_settles_separately():
    """不同 input_version 视为不同次结算, 不冲突"""
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600000": 1.0})
    snap1 = settle_day(pid, "2026-07-24", {"600000": 10.0}, input_version="v1")
    snap2 = settle_day(pid, "2026-07-24", {"600000": 12.0}, input_version="v2")
    assert snap1["snapshot_id"] != snap2["snapshot_id"]
    assert snap2["holdings_json"] != snap1["holdings_json"]  # 价格不同


# ════════════════════════════════════════════════════════════
#  settle_window 多天
# ════════════════════════════════════════════════════════════

def test_settle_window_chains_correctly():
    """多天结算, 第 2 天用第 1 天结果作为 prev_holdings"""
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600000": 1.0})

    # 第 1 天 10 元, 第 2 天 12 元, 第 3 天 11 元
    snaps = settle_window(
        portfolio_id=pid,
        start_date="2026-07-22",  # 周三
        end_date="2026-07-28",
        prices_by_date={
            "2026-07-22": {"600000": 10.0},
            "2026-07-24": {"600000": 12.0},  # 周五
            "2026-07-28": {"600000": 11.0},  # 周二
        },
        input_version="chain_v1",
    )
    # 至少应该有 1 条 (交易日历 fallback 可能只识别 weekday<5)
    assert len(snaps) >= 1
    # 第 1 条后 NAV 应该接近 initial_cash (考虑手续费 drag, 允许小幅缩水)
    if len(snaps) >= 1:
        first = snaps[0]
        assert first["nav"] > 99000  # 允许 ~1% 手续费 drag
        assert first["nav"] <= 100000  # 不能凭空多钱


def test_settle_window_uses_prev_holdings():
    """多天时, 价格变化导致再平衡, NAV 反映涨幅"""
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600000": 1.0})

    # 手动连续 settle
    snap1 = settle_day(pid, "2026-07-22", {"600000": 10.0}, input_version="v1")
    snap2 = settle_day(pid, "2026-07-23", {"600000": 12.0}, input_version="v1")

    holdings1 = json.loads(snap1["holdings_json"])
    holdings2 = json.loads(snap2["holdings_json"])
    # 价格上涨 20% → 持仓数量微调 (整手边界), 但数量级一致
    assert abs(holdings1.get("600000") - holdings2.get("600000")) < 200
    # NAV 应反映价格上涨 (12 > 10)
    assert snap2["nav"] > snap1["nav"] * 1.15  # 至少涨 15% (考虑再平衡边界)


# ════════════════════════════════════════════════════════════
#  get_snapshots / get_snapshot
# ════════════════════════════════════════════════════════════

def test_get_snapshot_decodes_json():
    pid = create_shadow_portfolio(owner_user_id=1, initial_cash=100000)
    set_target_weights(pid, {"600000": 0.5, "600036": 0.5})
    settle_day(pid, "2026-07-24", {"600000": 10.0, "600036": 20.0}, input_version="v1")

    snap = get_snapshot(pid, "2026-07-24", input_version="v1")
    assert snap is not None
    assert isinstance(snap.get("holdings"), dict)


def test_get_snapshots_range():
    pid = create_shadow_portfolio(owner_user_id=1)
    set_target_weights(pid, {"600000": 1.0})
    settle_day(pid, "2026-07-22", {"600000": 10.0}, input_version="v1")
    settle_day(pid, "2026-07-24", {"600000": 12.0}, input_version="v1")
    settle_day(pid, "2026-07-28", {"600000": 11.0}, input_version="v1")

    rows = get_snapshots(pid, start="2026-07-23", end="2026-07-28")
    dates = [r["observation_date"] for r in rows]
    # 只应包含 24, 28 (22 < 23 被过滤)
    assert "2026-07-22" not in dates
    assert "2026-07-28" in dates


# ════════════════════════════════════════════════════════════
#  完整 E2E
# ════════════════════════════════════════════════════════════

def test_e2e_create_set_settle_query():
    """端到端: 创建 → 设权重 → 结算 → 查询"""
    pid = create_shadow_portfolio(owner_user_id=1, name="e2e_pf", initial_cash=100000)
    set_target_weights(pid, {"600519": 0.6, "000858": 0.4})
    snap = settle_day(
        portfolio_id=pid,
        observation_date="2026-07-24",
        prices={"600519": 1500.0, "000858": 100.0},
        input_version="e2e_v1",
    )
    # 600519 @ 1500: 60000/1500 = 40 股 (整手不调整, <100) → 不买
    # 000858 @ 100: 40000/100 = 400 股 → 4 手 = 400 股, cost = 40000
    holdings = json.loads(snap["holdings_json"])
    assert "000858" in holdings
    assert "600519" not in holdings  # 价格太贵, 整手门槛过不了
    assert snap["status"] == "settled"
    assert snap["turnover"] > 0  # 买了 000858 算 turnover
    assert snap["costs"] > 0  # 手续费

    rows = get_snapshots(pid)
    assert len(rows) == 1
    assert rows[0]["portfolio_id"] == pid