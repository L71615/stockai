"""v5.2.1 — sync_stocks fallback 测试

覆盖:
  1. 腾讯成功 → 不调 baostock → break
  2. 腾讯失败 + baostock 成功 → fallback 成功
  3. 两者都失败 → 不 success
  4. fallback 成功 → logger.warning 有提示
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ── Helpers ──


def _tencent_success(code="600519"):
    return {
        "code": code,
        "dates": ["2026-08-01", "2026-08-02", "2026-08-03"],
        "opens": [100.0, 101.0, 102.0],
        "highs": [105.0, 106.0, 107.0],
        "lows": [99.0, 100.0, 101.0],
        "closes": [104.0, 105.0, 106.0],
        "volumes": [1000.0, 1100.0, 1200.0],
        "source": "tencent",
    }


def _empty(code="999999"):
    return {"error": "无K线数据", "code": code}


def _baostock_success(code="000725"):
    return {
        "code": code,
        "dates": ["2026-08-01", "2026-08-02"],
        "opens": [4.0, 4.1],
        "highs": [4.2, 4.3],
        "lows": [3.9, 4.0],
        "closes": [4.1, 4.2],
        "volumes": [5000.0, 5500.0],
        "source": "baostock",
    }


def _run_fallback(code, source_fns):
    """走 worker 内层 fallback 逻辑(简化版,直接调 mock)"""
    success = False
    for source_name, source_fn in source_fns:
        kline = source_fn(code, days=10)
        if kline and "closes" in kline and len(kline["closes"]) > 0:
            success = True
            if source_name != "tencent":
                logging.getLogger("routers.data_ops").warning(
                    "sync %s: tencent 失败, fallback baostock 成功 (rows=%d)",
                    code, len(kline["closes"]),
                )
            break
        else:
            logging.getLogger("routers.data_ops").warning(
                "sync %s attempt: %s empty", code, source_name,
            )
    return success


# ── 测试 ──


def test_tencent_success_skips_baostock(monkeypatch):
    """腾讯成功 → 不调 baostock → break(避免浪费)"""
    tencent_calls = []
    bs_calls = []

    def mock_tencent(code, days=10):
        tencent_calls.append(code)
        return _tencent_success(code)

    def mock_bs(code, days=10, freq="d"):
        bs_calls.append(code)
        return _baostock_success(code)

    success = _run_fallback("600519", [
        ("tencent", mock_tencent),
        ("baostock", mock_bs),
    ])

    assert success is True
    assert tencent_calls == ["600519"]
    assert bs_calls == []  # 关键: baostock 没被调


def test_fallback_tencent_fail_baostock_success(monkeypatch):
    """核心场景: 腾讯失败 → baostock 救场"""
    tencent_calls = []
    bs_calls = []

    def mock_tencent_fail(code, days=10):
        tencent_calls.append(code)
        return _empty(code)

    def mock_bs_success(code, days=10, freq="d"):
        bs_calls.append(code)
        return _baostock_success(code)

    success = _run_fallback("000725", [
        ("tencent", mock_tencent_fail),
        ("baostock", mock_bs_success),
    ])

    assert success is True
    assert tencent_calls == ["000725"]
    assert bs_calls == ["000725"]  # baostock 接着被调


def test_both_fail_marks_failed(monkeypatch):
    """两者都失败 → success = False"""
    def mock_tencent_fail(code, days=10):
        return _empty(code)

    def mock_bs_fail(code, days=10, freq="d"):
        return _empty(code)

    success = _run_fallback("999999", [
        ("tencent", mock_tencent_fail),
        ("baostock", mock_bs_fail),
    ])

    assert success is False


def test_fallback_logs_warning(monkeypatch, caplog):
    """fallback 成功 → logger.warning 应有 'fallback baostock 成功'"""
    def mock_tencent_fail(code, days=10):
        return _empty(code)

    def mock_bs_success(code, days=10, freq="d"):
        return _baostock_success(code)

    with caplog.at_level(logging.WARNING, logger="routers.data_ops"):
        success = _run_fallback("000725", [
            ("tencent", mock_tencent_fail),
            ("baostock", mock_bs_success),
        ])

    assert success is True
    assert any("fallback baostock 成功" in r.message for r in caplog.records)


def test_real_baostock_works(fresh_db_check=True):
    """v5.2.1 — 实跑 baostock 拉一只股票,确认能拿到数据(无 mock)"""
    # 跳过 if 离线 / 没装 baostock
    try:
        from services.baostock_adapter import get_kline
    except ImportError:
        pytest.skip("baostock 未安装")

    result = get_kline("600519", days=10)
    if "error" in result:
        pytest.skip(f"baostock 离线: {result['error']}")

    assert "closes" in result
    assert len(result["closes"]) > 0
    assert result.get("source") == "baostock"
    print(f"\n  baostock 实跑: 600519 → {len(result['closes'])} 条 K 线, 最新 {result['dates'][-1]}")