"""Futu 客户端测试 — SDK 可用性 / 健康检查 / snapshot / kline 映射"""

import sys
import types
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from services.futu_client import is_futu_available, FutuClient


class _FakeCtx:
    def __init__(self, *args, **kwargs):
        pass

    def get_market_snapshot(self, symbols):
        data = pd.DataFrame([
            {
                "code": "SH.600519",
                "last_price": 1234.5,
                "open_price": 1220.0,
                "high_price": 1240.0,
                "low_price": 1218.0,
                "prev_close_price": 1210.0,
                "volume": 2000,
                "turnover": 3000000,
                "update_time": "2026-07-01 10:30:00",
                "name": "贵州茅台",
            }
        ])
        return 0, data

    def request_history_kline(self, code, ktype, autype, max_count):
        data = pd.DataFrame([
            {
                "code": "SH.600519",
                "time_key": "2026-07-01 00:00:00",
                "open": 1200.0,
                "high": 1250.0,
                "low": 1190.0,
                "close": 1234.5,
                "volume": 2000,
                "turnover": 3000000,
            }
        ])
        return 0, data, None

    def close(self):
        return None


def test_is_futu_available_false_when_import_missing(monkeypatch):
    monkeypatch.setattr("services.futu_client._FUTU_IMPORT_ERROR", ImportError("missing"), raising=False)
    assert is_futu_available() is False


def test_healthcheck_returns_error_when_sdk_unavailable(monkeypatch):
    monkeypatch.setattr("services.futu_client._FUTU_IMPORT_ERROR", ImportError("missing"), raising=False)
    client = FutuClient()

    result = client.healthcheck()

    assert result["ok"] is False
    assert result["source"] == "futu"
    assert "missing" in result["message"]


def test_get_snapshot_maps_fields(monkeypatch):
    monkeypatch.setattr("services.futu_client._FUTU_IMPORT_ERROR", None, raising=False)
    monkeypatch.setattr("services.futu_client.OpenQuoteContext", _FakeCtx)
    monkeypatch.setattr("services.futu_client.RET_OK", 0)

    result = FutuClient().get_snapshot(["600519"])

    assert result[0]["code"] == "600519"
    assert result[0]["market"] == "SH"
    assert result[0]["symbol"] == "SH.600519"
    assert result[0]["price"] == 1234.5
    assert result[0]["source"] == "futu"


def test_get_kline_maps_daily_fields(monkeypatch):
    monkeypatch.setattr("services.futu_client._FUTU_IMPORT_ERROR", None, raising=False)
    monkeypatch.setattr("services.futu_client.OpenQuoteContext", _FakeCtx)
    monkeypatch.setattr("services.futu_client.RET_OK", 0)
    monkeypatch.setattr("services.futu_client.KLType", types.SimpleNamespace(K_DAY="K_DAY", K_1M="K_1M"))
    monkeypatch.setattr("services.futu_client.AuType", types.SimpleNamespace(QFQ="QFQ", NONE="NONE"))

    result = FutuClient().get_kline("600519", "1d", count=10)

    assert result["code"] == "600519"
    assert result["market"] == "SH"
    assert result["symbol"] == "SH.600519"
    assert result["interval"] == "1d"
    assert result["dates"] == ["2026-07-01"]
    assert result["closes"] == [1234.5]
    assert result["source"] == "futu"
