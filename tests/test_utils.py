"""市场识别函数测试 — is_us_stock + is_hk_stock + detect_asset_type

覆盖率：
- is_us_stock: 正常美股 + 边缘（含点号/空字符串/数字/A股代码）
- is_hk_stock: 正常港股 + 边缘（A股6位/短代码）
- detect_asset_type: A股/港股/美股/ETF/基金 全路径
"""
import pytest
from services.utils import is_us_stock, is_hk_stock, detect_asset_type


class TestIsUsStock:
    def test_normal_us_stock(self):
        assert is_us_stock("AAPL") is True
        assert is_us_stock("TSLA") is True
        assert is_us_stock("GOOGL") is True

    def test_lowercase_us_stock(self):
        assert is_us_stock("aapl") is True

    def test_not_us_stock_digits(self):
        assert is_us_stock("000001") is False

    def test_not_us_stock_empty(self):
        assert is_us_stock("") is False

    def test_not_us_stock_with_dot(self):
        # BRK.B 含点号，当前不支持
        assert is_us_stock("BRK.B") is False


class TestIsHkStock:
    def test_normal_hk_stock(self):
        assert is_hk_stock("00700") is True
        assert is_hk_stock("09988") is True

    def test_not_hk_stock_a_share(self):
        assert is_hk_stock("000001") is False  # 6位，不是5位

    def test_not_hk_stock_us(self):
        assert is_hk_stock("AAPL") is False


class TestDetectAssetType:
    def test_a_stock_shanghai(self):
        assert detect_asset_type("600000") == "stock"

    def test_a_stock_shenzhen(self):
        assert detect_asset_type("000001") == "stock"

    def test_hk_stock(self):
        assert detect_asset_type("00700") == "stock"

    def test_us_stock(self):
        assert detect_asset_type("AAPL") == "us_stock"
        assert detect_asset_type("TSLA") == "us_stock"

    def test_etf(self):
        assert detect_asset_type("510050") == "etf"
        assert detect_asset_type("159915") == "etf"

    def test_fund(self):
        # 6位数字但非 A 股/ETF 前缀 → fund
        assert detect_asset_type("501234") == "fund"

    def test_empty(self):
        assert detect_asset_type("") == "fund"
