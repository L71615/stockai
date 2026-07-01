"""Futu OpenD / SDK 访问层 — 统一健康检查、A 股报价与 K 线获取。"""

import logging
from typing import Any

from services.utils import get_market

logger = logging.getLogger(__name__)

try:
    from futu import OpenQuoteContext, RET_OK, KLType, AuType
    _FUTU_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import path covered by monkeypatch tests
    OpenQuoteContext = None
    RET_OK = None
    KLType = None
    AuType = None
    _FUTU_IMPORT_ERROR = exc


_INTERVAL_MAP = {
    "1d": lambda: KLType.K_DAY,
    "1m": lambda: KLType.K_1M,
}


def is_futu_available() -> bool:
    """Whether the futu SDK imported successfully in this environment."""
    return _FUTU_IMPORT_ERROR is None and OpenQuoteContext is not None


def _market_prefix(code: str) -> str:
    return "SH" if get_market(code) == "1" else "SZ"


def _to_symbol(code: str) -> str:
    return f"{_market_prefix(code)}.{code.strip()}"


class FutuClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 11111) -> None:
        self.host = host
        self.port = port

    def _make_ctx(self):
        if not is_futu_available():
            raise RuntimeError(str(_FUTU_IMPORT_ERROR))
        return OpenQuoteContext(host=self.host, port=self.port)

    def healthcheck(self) -> dict[str, Any]:
        if not is_futu_available():
            return {
                "ok": False,
                "source": "futu",
                "host": self.host,
                "port": self.port,
                "message": str(_FUTU_IMPORT_ERROR),
            }
        return {
            "ok": True,
            "source": "futu",
            "host": self.host,
            "port": self.port,
            "message": "sdk import ok",
        }

    def get_snapshot(self, codes: list[str]) -> list[dict[str, Any]]:
        if not is_futu_available():
            return [{"error": str(_FUTU_IMPORT_ERROR), "source": "futu"}]

        ctx = self._make_ctx()
        try:
            symbols = [_to_symbol(code) for code in codes]
            ret, data = ctx.get_market_snapshot(symbols)
            if ret != RET_OK:
                return [{"error": str(data), "source": "futu"}]

            rows = []
            for _, row in data.iterrows():
                symbol = row["code"]
                code = symbol.split(".", 1)[1]
                rows.append({
                    "code": code,
                    "market": symbol.split(".", 1)[0],
                    "symbol": symbol,
                    "name": row.get("name", ""),
                    "price": row.get("last_price"),
                    "open_price": row.get("open_price"),
                    "high_price": row.get("high_price"),
                    "low_price": row.get("low_price"),
                    "prev_close": row.get("prev_close_price"),
                    "change": None,
                    "change_pct": None,
                    "volume": row.get("volume"),
                    "turnover": row.get("turnover"),
                    "quote_time": row.get("update_time"),
                    "source": "futu",
                    "raw_payload": row.to_json(force_ascii=False),
                })
            return rows
        finally:
            ctx.close()

    def get_kline(self, code: str, interval: str, count: int = 200, adjust_type: str = "qfq") -> dict[str, Any]:
        if not is_futu_available():
            return {"error": str(_FUTU_IMPORT_ERROR), "source": "futu", "code": code}
        if interval not in _INTERVAL_MAP:
            return {"error": f"unsupported interval: {interval}", "source": "futu", "code": code}

        autype = AuType.QFQ if adjust_type == "qfq" else AuType.NONE
        ctx = self._make_ctx()
        try:
            symbol = _to_symbol(code)
            ret, data, _ = ctx.request_history_kline(
                symbol,
                ktype=_INTERVAL_MAP[interval](),
                autype=autype,
                max_count=count,
            )
            if ret != RET_OK:
                return {"error": str(data), "source": "futu", "code": code}

            dates = [str(v).split(" ", 1)[0] for v in data["time_key"].tolist()]
            turnovers = data["turnover"].tolist() if "turnover" in data else [None] * len(dates)
            return {
                "code": code,
                "market": _market_prefix(code),
                "symbol": symbol,
                "interval": interval,
                "adjust_type": adjust_type,
                "dates": dates,
                "opens": data["open"].tolist(),
                "highs": data["high"].tolist(),
                "lows": data["low"].tolist(),
                "closes": data["close"].tolist(),
                "volumes": data["volume"].tolist(),
                "turnovers": turnovers,
                "raw_rows": data.to_dict(orient="records"),
                "source": "futu",
            }
        finally:
            ctx.close()
