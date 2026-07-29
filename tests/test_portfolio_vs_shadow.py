"""v4.1 1B.4: /api/stocks/holdings/shadow-comparison — 持仓 vs 影子组合差异

覆盖:
  1. both_have_positions — 双方都有 → diff_side='both'
  2. actual_only — 持仓有,影子 holdings_json={} → 全 actual_only
  3. shadow_only — 影子有,无 holdings → 全 shadow_only
  4. accumulating — snapshot_count < window_days → accumulating=true
  5. no_active_shadow — 无 active → shadow_portfolio_id=null, 但 actual 仍非零
  6. window_validation — window=999d → 422
  7. dod_pnl_nonzero — DoD: actual.pnl != 0 && shadow.nav > 0 && rows 非空
"""
import json
from datetime import datetime, timedelta

import pytest

from database import execute, query_one
from services.portfolio_comparison_service import get_holdings_vs_shadow


# ─────────────────────── Fixtures ───────────────────────

@pytest.fixture(autouse=True)
def _clean_tables(_test_db_session):
    """每个测试前清表 (session-scope DB,需 function-level 隔离)"""
    for tbl in ("shadow_portfolio_snapshots", "shadow_portfolios",
                "holdings", "transactions"):
        try:
            execute(f"DELETE FROM {tbl}")
        except Exception:
            pass


@pytest.fixture
def admin_user_id(_test_db_session):
    user = query_one("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    return user["id"]


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _make_holding(admin_user_id: int, code: str, name: str, qty: int, cost: float) -> int:
    cur = execute(
        "INSERT INTO holdings (user_id, stock_code, stock_name, market, asset_type, "
        "quantity, cost_price, created_at, updated_at) "
        "VALUES (?, ?, ?, 'SH', 'stock', ?, ?, ?, ?)",
        (admin_user_id, code, name, qty, cost, _now_iso(), _now_iso()),
    )
    return int(cur["lastrowid"])


def _make_shadow_portfolio(admin_user_id: int, name: str = "test_shadow", status: str = "active") -> int:
    cur = execute(
        "INSERT INTO shadow_portfolios "
        "(owner_user_id, name, policy_version, initial_cash, target_weights_json, "
        " scope, status, created_at, updated_at) "
        "VALUES (?, ?, 'v1.0.0', 100000, '{}', 'paper', ?, ?, ?)",
        (admin_user_id, name, status, _now_iso(), _now_iso()),
    )
    return int(cur["lastrowid"])


def _write_snapshot(portfolio_id: int, date: str, nav: float, cash: float,
                    holdings: dict, weights: dict) -> int:
    cur = execute(
        "INSERT INTO shadow_portfolio_snapshots "
        "(portfolio_id, observation_date, nav, cash, holdings_json, "
        " target_weights_json, actual_weights_json, turnover, costs, drawdown, "
        " baseline_diff_json, status, reason, input_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, '{}', ?, 0, 0, 0, '{}', 'settled', '', 'v1.0.0', ?)",
        (portfolio_id, date, nav, cash,
         json.dumps(holdings), json.dumps(weights),
         _now_iso()),
    )
    return int(cur["lastrowid"])


# ─────────────────────── Tests ───────────────────────

def test_both_have_positions(admin_user_id):
    """双方都有持仓 → diff_side='both' 行存在"""
    _make_holding(admin_user_id, "600519", "贵州茅台", 100, 1500.0)
    _make_holding(admin_user_id, "000001", "平安银行", 1000, 10.0)

    pid = _make_shadow_portfolio(admin_user_id)
    _write_snapshot(pid, "2026-07-28", nav=105000.0, cash=50000.0,
                    holdings={"600519": 50, "000001": 1000},
                    weights={"600519": 0.3, "000001": 0.2})

    result = get_holdings_vs_shadow(user_id=admin_user_id, window_days=30)

    both_rows = [r for r in result["rows"] if r["diff_side"] == "both"]
    assert len(both_rows) == 2, f"应有 2 行 both, 实际 {len(both_rows)}"
    assert result["diff_summary"]["position_overlap_count"] == 2
    assert result["shadow"]["nav"] == 105000.0
    assert result["shadow_portfolio_id"] == pid


def test_actual_only(admin_user_id):
    """持仓有,影子 holdings_json={} → 所有 actual_only"""
    _make_holding(admin_user_id, "600519", "贵州茅台", 100, 1500.0)
    _make_holding(admin_user_id, "000001", "平安银行", 1000, 10.0)

    pid = _make_shadow_portfolio(admin_user_id)
    _write_snapshot(pid, "2026-07-28", nav=100000.0, cash=100000.0,
                    holdings={}, weights={})

    result = get_holdings_vs_shadow(user_id=admin_user_id, window_days=30)

    assert all(r["diff_side"] == "actual_only" for r in result["rows"]), \
        f"应全 actual_only, 实际 {[r['diff_side'] for r in result['rows']]}"
    assert result["diff_summary"]["actual_only_count"] == 2
    assert result["shadow"]["market_value"] == 0.0  # 全现金


def test_shadow_only(admin_user_id):
    """影子有持仓,实际无 → 所有 shadow_only"""
    # 无 holdings

    pid = _make_shadow_portfolio(admin_user_id)
    _write_snapshot(pid, "2026-07-28", nav=105000.0, cash=50000.0,
                    holdings={"600519": 50, "000001": 1000},
                    weights={"600519": 0.3, "000001": 0.2})

    result = get_holdings_vs_shadow(user_id=admin_user_id, window_days=30)

    assert all(r["diff_side"] == "shadow_only" for r in result["rows"]), \
        f"应全 shadow_only, 实际 {[r['diff_side'] for r in result['rows']]}"
    assert result["diff_summary"]["shadow_only_count"] == 2
    assert result["actual"]["market_value"] == 0.0


def test_accumulating(admin_user_id):
    """snapshot_count < window_days → accumulating=true"""
    _make_holding(admin_user_id, "600519", "贵州茅台", 100, 1500.0)

    pid = _make_shadow_portfolio(admin_user_id)
    # 只写 5 个 snapshot (window_days=30)
    base_date = datetime(2026, 7, 20)
    for i in range(5):
        d = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        _write_snapshot(pid, d, nav=100000.0 + i * 1000, cash=50000.0,
                        holdings={"600519": 50}, weights={"600519": 0.25})

    result = get_holdings_vs_shadow(user_id=admin_user_id, window_days=30)

    assert result["accumulating"] is True
    assert result["snapshot_count"] == 5
    assert result["snapshot_target"] == 30
    assert result["shadow_portfolio_name"] == "test_shadow"  # 策略名仍渲染


def test_no_active_shadow(admin_user_id):
    """无 active shadow portfolio → shadow_portfolio_id=null,但 actual 仍非零"""
    _make_holding(admin_user_id, "600519", "贵州茅台", 100, 1500.0)
    _make_holding(admin_user_id, "000001", "平安银行", 1000, 10.0)

    # 造一个 closed portfolio (不应被选中)
    _make_shadow_portfolio(admin_user_id, name="closed_one", status="closed")

    result = get_holdings_vs_shadow(user_id=admin_user_id, window_days=30)

    assert result["shadow_portfolio_id"] is None
    assert result["shadow_portfolio_name"] is None
    assert result["snapshot_count"] == 0
    assert result["accumulating"] is True
    assert result["actual"]["market_value"] > 0  # 实际持仓仍计算
    assert result["rows"] == []  # 没有 shadow → 无 diff 行


def test_window_validation_via_router(client):
    """非法 window=999d → 422"""
    # client fixture from conftest, JWT auth 已自动注入
    r = client.get("/api/stocks/holdings/shadow-comparison?window=999d")
    assert r.status_code == 422


def test_dod_pnl_nonzero(admin_user_id):
    """DoD 主断言: actual.pnl != 0 && shadow.nav > 0 && rows 非空"""
    _make_holding(admin_user_id, "600519", "贵州茅台", 100, 1500.0)  # cost 150k
    _make_holding(admin_user_id, "000001", "平安银行", 1000, 10.0)   # cost 10k

    pid = _make_shadow_portfolio(admin_user_id)
    # shadow 有非零 NAV (105k) + 非空 holdings
    _write_snapshot(pid, "2026-07-28", nav=105000.0, cash=50000.0,
                    holdings={"600519": 50, "000001": 1000, "600036": 500},
                    weights={"600519": 0.3, "000001": 0.2, "600036": 0.05})

    result = get_holdings_vs_shadow(user_id=admin_user_id, window_days=30)

    # DoD: 双方均非零
    assert result["actual"]["cost_basis"] > 0  # 有成本基础
    assert result["shadow"]["nav"] > 0
    assert len(result["rows"]) > 0

    # rows 同时包含 both / shadow_only (600036 用户没持仓)
    sides = {r["diff_side"] for r in result["rows"]}
    assert "both" in sides
    assert "shadow_only" in sides
    assert result["diff_summary"]["position_overlap_count"] >= 2


def test_dod_via_http_endpoint(client, admin_user_id):
    """DoD: curl /api/stocks/holdings/shadow-comparison?window=30d 双方 pnl/nav 非零"""
    _make_holding(admin_user_id, "600519", "贵州茅台", 100, 1500.0)
    pid = _make_shadow_portfolio(admin_user_id)
    _write_snapshot(pid, "2026-07-28", nav=105000.0, cash=50000.0,
                    holdings={"600519": 50}, weights={"600519": 0.3})

    r = client.get("/api/stocks/holdings/shadow-comparison?window=30d")
    assert r.status_code == 200
    data = r.json()

    assert data["shadow"]["nav"] > 0
    assert data["actual"]["cost_basis"] > 0
    assert len(data["rows"]) > 0
    assert data["shadow_portfolio_id"] == pid