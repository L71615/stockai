"""StockAI — 股市数据服务（多源适配器模式，借鉴 DSA 的 data_provider 设计）

数据源优先级：东方财富 > akshare > 新浪
每个数据源实现相同的 fetch_quote(code) 接口，挂了自动降级。
"""

import httpx
from typing import Optional


# ==================== 股票代码工具 ====================

def normalize_market(code: str) -> str:
    """判断股票所属市场"""
    if code.startswith(("60", "68")):
        return "SH"
    elif code.startswith(("00", "30", "002")):
        return "SZ"
    elif code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def to_eastmoney_secid(code: str) -> str:
    """转为东方财富 secid 格式"""
    m = "1" if normalize_market(code) == "SH" else "0"
    return f"{m}.{code}"


# ==================== 数据源适配器 ====================

class BaseDataProvider:
    """数据源基类"""

    name: str = "base"

    async def fetch_quote(self, code: str) -> Optional[dict]:
        raise NotImplementedError


class EastMoneyProvider(BaseDataProvider):
    """东方财富 API（免费、无 Key、数据全）"""

    name = "eastmoney"

    async def fetch_quote(self, code: str) -> Optional[dict]:
        try:
            secid = to_eastmoney_secid(code)
            url = (
                f"https://push2.eastmoney.com/api/qt/stock/get"
                f"?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f169,f170,f116"
            )
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                data = resp.json()
            d = data.get("data")
            if not d:
                return None
            return {
                "code": d["f57"],
                "name": d["f58"],
                "price": d.get("f43", 0) / 100 if d.get("f43") else None,
                "change": d.get("f169", 0) / 100 if d.get("f169") else None,
                "change_pct": d.get("f170", 0) / 100 if d.get("f170") else None,
                "high": d.get("f44", 0) / 100 if d.get("f44") else None,
                "low": d.get("f45", 0) / 100 if d.get("f45") else None,
                "volume": d.get("f47"),
                "amount": d.get("f48"),
                "source": self.name,
            }
        except Exception:
            return None


class AkShareProvider(BaseDataProvider):
    """AkShare 数据源（功能强大，离线候选）"""

    name = "akshare"

    async def fetch_quote(self, code: str) -> Optional[dict]:
        try:
            from akshare import stock_zh_a_spot_em

            df = stock_zh_a_spot_em()
            row = df[df["代码"] == code]
            if row.empty:
                return None
            r = row.iloc[0]
            return {
                "code": code,
                "name": r.get("名称"),
                "price": float(r.get("最新价", 0)),
                "change": float(r.get("涨跌额", 0)),
                "change_pct": float(r.get("涨跌幅", 0)),
                "high": float(r.get("最高", 0)),
                "low": float(r.get("最低", 0)),
                "volume": int(r.get("成交量", 0)),
                "amount": float(r.get("成交额", 0)),
                "source": self.name,
            }
        except Exception:
            return None


# ==================== 多源调度器 ====================

class StockDataService:
    """多数据源调度器：按优先级尝试，失败则降级"""

    def __init__(self):
        self.providers: list[BaseDataProvider] = [
            AkShareProvider(),
            EastMoneyProvider(),
        ]

    async def get_quote(self, code: str) -> Optional[dict]:
        for provider in self.providers:
            result = await provider.fetch_quote(code)
            if result:
                return result
        return None

    async def get_quotes_batch(self, codes: list[str]) -> dict[str, dict]:
        """批量获取行情"""
        results = {}
        for code in codes:
            results[code] = await self.get_quote(code)
        return results

    async def get_market_indices(self) -> list[dict]:
        """获取大盘指数（上证/深证/创业板），使用腾讯 API"""
        from services.akshare_adapter import get_index_quote
        results = []
        for code, name in [("000001", "上证指数"), ("399001", "深证成指"), ("399006", "创业板指")]:
            q = get_index_quote(code)
            if q:
                results.append({
                    "name": q.get("name") or name,
                    "price": q.get("price"),
                    "change": q.get("change"),
                    "change_pct": q.get("change_pct"),
                })
            else:
                results.append({
                    "name": name, "price": None, "change": None, "change_pct": None,
                })
        return results


# 全局单例
stock_service = StockDataService()
