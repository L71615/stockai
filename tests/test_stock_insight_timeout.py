import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def test_stock_insight_does_not_fail_when_factor_fetch_errors(client, monkeypatch):
    monkeypatch.setattr(
        "services.technical.fetch_kline",
        lambda code, market=None, days=120: {
            "code": code,
            "dates": ["2026-07-01"] * 60,
            "opens": [10.0] * 60,
            "closes": [10.0] * 60,
            "highs": [10.5] * 60,
            "lows": [9.5] * 60,
            "volumes": [1000.0] * 60,
        },
    )
    monkeypatch.setattr(
        "services.technical.get_indicators",
        lambda code, market=None, days=120: {
            "name": "测试股票",
            "price": 10.0,
            "MA": {},
            "MACD": {},
            "KDJ": {},
            "RSI": [],
            "signal": "ok",
        },
    )
    monkeypatch.setattr(
        "routers.stocks._cached_quote",
        lambda code, market=None: {
            "code": code,
            "name": "测试股票",
            "price": 10.0,
            "change_pct": 0.0,
        },
    )
    monkeypatch.setattr(
        "services.baostock_adapter.get_stock_factors",
        lambda code: (_ for _ in ()).throw(TimeoutError("slow factors")),
    )

    resp = client.get("/api/quant/stock-insight/600519?days=5")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "600519"
    assert body["price"] == 10.0
    assert body["factors"] == {
        "pe": None,
        "pb": None,
        "roe": None,
        "eps": None,
        "market_cap_billion": None,
        "dividend": None,
        "industry": "",
        "industry_type": "",
    }


def test_stock_insight_returns_quickly_when_factor_fetch_hangs(client, monkeypatch):
    monkeypatch.setattr(
        "services.technical.fetch_kline",
        lambda code, market=None, days=120: {
            "code": code,
            "dates": ["2026-07-01"] * 60,
            "opens": [10.0] * 60,
            "closes": [10.0] * 60,
            "highs": [10.5] * 60,
            "lows": [9.5] * 60,
            "volumes": [1000.0] * 60,
        },
    )
    monkeypatch.setattr(
        "services.technical.get_indicators",
        lambda code, market=None, days=120: {
            "name": "测试股票",
            "price": 10.0,
            "MA": {},
            "MACD": {},
            "KDJ": {},
            "RSI": [],
            "signal": "ok",
        },
    )
    monkeypatch.setattr(
        "routers.stocks._cached_quote",
        lambda code, market=None: {
            "code": code,
            "name": "测试股票",
            "price": 10.0,
            "change_pct": 0.0,
        },
    )

    def slow_factors(code):
        time.sleep(2.0)
        return {"pe": 1.0}

    monkeypatch.setattr("services.baostock_adapter.get_stock_factors", slow_factors)

    started = time.time()
    resp = client.get("/api/quant/stock-insight/600519?days=5")
    elapsed = time.time() - started

    assert resp.status_code == 200
    assert elapsed < 1.0
