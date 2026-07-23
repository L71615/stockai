"""Futu OpenD / SDK 访问层 — 统一健康检查、A 股报价与 K 线获取。"""

import logging
import socket
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
        """真实探测 OpenD 是否可达 (1 秒 socket connect)

        之前只检查 SDK import, 没用真连 — 撞上 OpenD 未运行时会
        进入 get_snapshot() 内部死循环重试, 永不抛异常, 整个 API 悬挂。
        """
        if not is_futu_available():
            return {
                "ok": False,
                "source": "futu",
                "host": self.host,
                "port": self.port,
                "message": str(_FUTU_IMPORT_ERROR),
            }
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((self.host, self.port))
            s.close()
            return {
                "ok": True,
                "source": "futu",
                "host": self.host,
                "port": self.port,
                "message": "OpenD reachable",
            }
        except Exception as e:
            return {
                "ok": False,
                "source": "futu",
                "host": self.host,
                "port": self.port,
                "message": f"OpenD unreachable: {e}",
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
                # 计算涨跌幅
                price = row.get("last_price")
                prev = row.get("prev_close_price")
                change = round(price - prev, 2) if price is not None and prev is not None and prev > 0 else None
                change_pct = round((price - prev) / prev * 100, 2) if price is not None and prev is not None and prev > 0 else None

                rows.append({
                    "code": code,
                    "market": symbol.split(".", 1)[0],
                    "symbol": symbol,
                    "name": row.get("name", ""),
                    "price": price,
                    "open_price": row.get("open_price"),
                    "high_price": row.get("high_price"),
                    "low_price": row.get("low_price"),
                    "prev_close": prev,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": row.get("volume"),
                    "turnover": row.get("turnover"),
                    # 基本面
                    "pe_ttm": row.get("pe_ttm"),
                    "pb": row.get("pb"),
                    "market_cap": row.get("market_val"),
                    "turnover_rate": row.get("turnover_rate"),
                    "eps": row.get("basic_eps"),
                    "roe": row.get("roe"),
                    "dividend_yield": row.get("dividend_yield_ratio"),
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
