"""Provider 接口定义 + 数据载体"""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class StockInfo:
    """单只股票基本信息 (name + industry + list_date)"""
    code: str
    name: str = ""
    industry: str = ""
    list_date: str = ""

    def to_row(self) -> dict:
        """转成可批量 INSERT 的 dict (供 stock_info 表)"""
        return {
            "stock_code": self.code,
            "name": self.name,
            "industry": self.industry,
            "list_date": self.list_date,
        }


@dataclass
class KLine:
    """单根 K 线"""
    trade_date: str   # 'YYYY-MM-DD'
    open:  float = 0.0
    high:  float = 0.0
    low:   float = 0.0
    close: float = 0.0
    volume: float = 0.0

    def to_row(self, code: str) -> tuple:
        return (code, self.trade_date, self.open, self.high, self.low, self.close, self.volume)


@runtime_checkable
class StockInfoProvider(Protocol):
    """股票基本信息拉取接口

    实现类至少提供 name 属性 (string, 标识数据源)
    """
    name: str

    def fetch_one(self, code: str) -> StockInfo | None:
        """按 code 单只拉取，失败/无数据返回 None"""
        ...

    def fetch_all(self) -> list[StockInfo]:
        """全市场一次性拉取，失败时 raise 或返回 []"""
        ...


@runtime_checkable
class KLineProvider(Protocol):
    """K 线拉取接口"""
    name: str

    def fetch(self, code: str, days: int = 252) -> list[KLine] | None:
        """按 code 单只拉 days 天的日 K 线，返回 None 表示失败/无数据"""
        ...
