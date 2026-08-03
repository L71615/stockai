"""v4.2 M2 — 因子分钟级 (55 因子) 测试

覆盖:
  - TestFactorRegistry: 注册表完整 / 函数签名合法 / 4 个 needs_* 字段正确
  - TestComputeMinuteFactors: 数据不足 / 60 根 / 单因子失败 / 未知因子
  - TestComputeMinuteFactorsWithCache: 首次算 + 写 / 二次命中 / invalidate
  - TestFetchRecentBars: 拉 5 个 list / 数据缺失
  - TestMinuteFactorRestApi: GET /minute + invalidate
  - TestLegacyFactorNameCompat: 大写 key 兼容
"""

import pytest

from services import factor_service
from services.factor_service import (
    MINUTE_FACTOR_REGISTRY,
    compute_minute_factors,
    factor_ma5,
    factor_vol_ma5,
)
from services import realtime_factor_minute
from services.realtime_factor_minute import (
    compute_minute_factors_with_cache,
    fetch_recent_bars,
    invalidate,
    get_all_cached,
    all_factor_names,
)


# ═══════════════════════════════════════════════════════════════
#  55 因子注册表
# ═══════════════════════════════════════════════════════════════


class TestFactorRegistry:
    def test_registry_has_55_factors(self):
        """注册表 >= 50 因子(55 是设计目标,允许 ±5 调整)"""
        assert len(MINUTE_FACTOR_REGISTRY) >= 50
        assert len(MINUTE_FACTOR_REGISTRY) <= 65

    def test_all_factor_names(self):
        """all_factor_names() 返回完整列表"""
        names = all_factor_names()
        assert len(names) == len(MINUTE_FACTOR_REGISTRY)
        assert "ma5" in names
        assert "rsi_14" in names
        assert "klen" in names
        assert "north_flow" in names

    def test_required_factors_present(self):
        """核心因子必须在注册表中"""
        required = {
            "ma5", "ma10", "ma20", "ma60",
            "rsi_14", "macd_signal", "ma_disposition",
            "vol_ma5", "vol_ma10", "vol_ma20", "vol_ratio",
            "obv_divergence", "avg_amount",
            "klen", "kup", "klow", "ksft",
            "rsrs", "atr_14",
        }
        missing = required - set(MINUTE_FACTOR_REGISTRY.keys())
        assert not missing, f"缺失核心因子: {missing}"

    def test_registry_entry_is_5tuple(self):
        """每个 entry 是 (fn, needs_vol, needs_hilo, needs_open, fn_volumes_only)"""
        for name, entry in MINUTE_FACTOR_REGISTRY.items():
            assert len(entry) == 5, f"{name} entry 应是 5-tuple, 实际 {len(entry)}"
            fn, needs_vol, needs_hilo, needs_open, fn_volumes_only = entry
            assert callable(fn), f"{name} fn 不可调用"
            assert isinstance(needs_vol, bool)
            assert isinstance(needs_hilo, bool)
            assert isinstance(needs_open, bool)
            assert isinstance(fn_volumes_only, bool)

    def test_volume_only_factors_dont_take_closes(self):
        """fn_volumes_only=True 的因子函数不应需要 closes"""
        for name, entry in MINUTE_FACTOR_REGISTRY.items():
            fn, needs_vol, needs_hilo, needs_open, fn_volumes_only = entry
            if fn_volumes_only:
                # 检查函数签名只有 volumes 一个参数
                import inspect
                sig = inspect.signature(fn)
                params = list(sig.parameters.keys())
                assert params[0] in ("volumes", "v"), \
                    f"{name} fn_volumes_only=True 但首参是 {params[0]},不是 volumes"

    def test_kline_factors_need_highs_lows_and_opens(self):
        """K 线形态因子(klen/kup/klow/ksft/kmid)需要 highs + lows + opens"""
        for name in ["klen", "kup", "klow", "ksft", "kmid"]:
            entry = MINUTE_FACTOR_REGISTRY[name]
            fn, needs_vol, needs_hilo, needs_open, _ = entry
            assert needs_hilo, f"{name} 应 needs_highs_lows"
            assert needs_open, f"{name} 应 needs_opens"


# ═══════════════════════════════════════════════════════════════
#  compute_minute_factors 入口
# ═══════════════════════════════════════════════════════════════


class TestComputeMinuteFactors:
    def test_insufficient_data_returns_empty(self):
        """closes < 5 根 → 返回空 dict"""
        result = compute_minute_factors(code="TEST", closes=[100.0, 101.0, 102.0])
        assert result == {}

    def test_60_bars_returns_55_factors(self):
        """60 根 → 返回 55 因子 dict (v4.2.3: +3 衍生字段 close/open/high, 共 58)"""
        closes = [100.0 + i * 0.1 for i in range(60)]
        opens = [99.5 + i * 0.1 for i in range(60)]
        highs = [100.5 + i * 0.1 for i in range(60)]
        lows = [99.0 + i * 0.1 for i in range(60)]
        volumes = [1000000.0 + i * 1000 for i in range(60)]
        result = compute_minute_factors(
            code="TEST", closes=closes, opens=opens, highs=highs, lows=lows, volumes=volumes,
        )
        # v4.2.3: 注入 close/open/high/low + 衍生字段 (varies by data availability)
        # 至少 55 主因子 + close/open/high 3 个 = 58
        assert len(result) >= len(MINUTE_FACTOR_REGISTRY) + 3
        # 至少 ma5 / rsi_14 / macd_signal 有值(简单行情足以算)
        assert result["ma5"] is not None
        assert result["ma10"] is not None
        assert result["ma20"] is not None
        assert result["rsi_14"] is not None
        # v4.2.3: 衍生字段
        assert result["close"] == closes[-1]
        assert result["open"] == opens[-1]
        assert result["high"] == highs[-1]
        assert result["low"] == lows[-1]
        # high_20d / close_vs_high_20d 等也应有值
        assert result["high_20d"] is not None

    def test_volume_only_factors_with_volumes(self):
        """vol_ma5 / vol_ratio 等纯量因子能正常计算"""
        closes = [100.0] * 60
        volumes = [1000000.0 + i * 1000 for i in range(60)]
        result = compute_minute_factors(code="TEST", closes=closes, volumes=volumes)
        assert result["vol_ma5"] is not None
        assert result["vol_ma10"] is not None
        assert result["vol_ma20"] is not None
        assert result["vol_ratio"] is not None

    def test_volume_only_factors_without_volumes_returns_none(self):
        """vol_ma5 没有 volumes 数据 → None(不抛)"""
        closes = [100.0] * 60
        result = compute_minute_factors(code="TEST", closes=closes)  # no volumes
        assert result["vol_ma5"] is None
        assert result["vol_ratio"] is None

    def test_kline_factors_without_highs_lows_returns_none(self):
        """klen 没有 highs/lows/opens → None"""
        closes = [100.0 + i for i in range(60)]
        result = compute_minute_factors(code="TEST", closes=closes)
        assert result["klen"] is None
        assert result["kup"] is None
        assert result["klow"] is None

    def test_kline_factors_with_ohlc_calculate(self):
        """klen 传入 opens/highs/lows 时能算"""
        closes = [100.0 + i for i in range(60)]
        opens = [99.0 + i for i in range(60)]
        highs = [101.0 + i for i in range(60)]
        lows = [98.0 + i for i in range(60)]
        result = compute_minute_factors(
            code="TEST", closes=closes, opens=opens, highs=highs, lows=lows,
        )
        # klen: (high-low)/close, 大概率有值
        assert result["klen"] is not None

    def test_unknown_factor_raises(self):
        """未知因子名 → ValueError"""
        with pytest.raises(ValueError, match="未知因子名"):
            compute_minute_factors(
                code="TEST", closes=[100.0] * 10,
                factor_names=["MA5", "bogus_factor"],
            )

    def test_subset_factor_names(self):
        """factor_names 子集只算指定因子(v4.2.3: +衍生字段 close/strength_20d)"""
        closes = [100.0 + i * 0.1 for i in range(60)]
        result = compute_minute_factors(
            code="TEST", closes=closes, factor_names=["ma5", "ma20"],
        )
        # v4.2.3: 即使只算 ma5/ma20, 也会注入 close + strength_20d (衍生字段)
        assert "ma5" in result and "ma20" in result
        assert result["ma5"] is not None
        # 衍生字段: close 是 closes[-1]
        assert result["close"] == closes[-1]
        assert result["strength_20d"] is not None  # = ma20


# ═══════════════════════════════════════════════════════════════
#  5m TTL 缓存
# ═══════════════════════════════════════════════════════════════


class TestComputeMinuteFactorsWithCache:
    def test_first_call_writes_cache(self, db):
        """首次调用 → 计算并写 cache"""
        from database import query_all
        closes = [100.0 + i * 0.1 for i in range(60)]
        result = compute_minute_factors_with_cache(
            code="TEST_CACHE", closes=closes, factor_names=["ma5", "rsi_14"],
        )
        assert result["ma5"] is not None
        # 验证 cache 已写
        rows = query_all(
            "SELECT factor_name, value FROM minute_factor_cache WHERE stock_code = ?",
            ("TEST_CACHE",),
        )
        cached_names = {r["factor_name"] for r in rows}
        assert "ma5" in cached_names
        assert "rsi_14" in cached_names

    def test_second_call_uses_cache(self, db):
        """二次调用 → 命中 cache(不重算)"""
        closes = [100.0 + i * 0.1 for i in range(60)]
        # 首次
        compute_minute_factors_with_cache(
            code="TEST_CACHE_HIT", closes=closes, factor_names=["ma5"],
        )
        # 二次 — 改 closes 看是否仍返回缓存值
        result2 = compute_minute_factors_with_cache(
            code="TEST_CACHE_HIT", closes=[200.0] * 60,  # 不同数据
            factor_names=["ma5"],
        )
        cached = get_all_cached("TEST_CACHE_HIT")
        # 应仍是首次算的 ma5 值
        assert result2["ma5"] == cached.get("ma5")

    def test_invalidate_clears_cache(self, db):
        """invalidate 后缓存被清"""
        closes = [100.0 + i * 0.1 for i in range(60)]
        compute_minute_factors_with_cache(
            code="TEST_INV", closes=closes, factor_names=["ma5"],
        )
        assert get_all_cached("TEST_INV") != {}
        invalidate("TEST_INV")
        assert get_all_cached("TEST_INV") == {}


# ═══════════════════════════════════════════════════════════════
#  fetch_recent_bars(数据获取)
# ═══════════════════════════════════════════════════════════════


class TestFetchRecentBars:
    def test_returns_5_lists(self, db):
        """返回 5 个 list (closes, highs, lows, opens, volumes)"""
        result = fetch_recent_bars("000725", limit=240)
        assert len(result) == 5
        closes, highs, lows, opens, volumes = result
        assert isinstance(closes, list)
        assert isinstance(highs, list)
        assert isinstance(lows, list)
        assert isinstance(opens, list)
        assert isinstance(volumes, list)

    def test_returns_consistent_length(self, db):
        """5 个 list 长度基本一致(historical_kline 高/低/开列都齐)"""
        closes, highs, lows, opens, volumes = fetch_recent_bars("000725", limit=240)
        assert len(closes) == len(highs) == len(lows) == len(opens) == len(volumes)

    def test_missing_stock_returns_empty(self, db):
        """不存在的 stock_code → 返回 5 个空 list"""
        closes, highs, lows, opens, volumes = fetch_recent_bars("NOTEXIST_999999", limit=240)
        assert closes == []
        assert highs == []
        assert lows == []
        assert opens == []
        assert volumes == []


# ═══════════════════════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════════════════════


class TestMinuteFactorRestApi:
    @pytest.fixture
    def _seed_kline(self, client):
        """通过 client 的 app 直接 INSERT 60 根 K 线 — 与 client 请求走同连接池"""
        from datetime import datetime, timedelta
        from database import execute as db_execute
        # 先清旧数据
        db_execute("DELETE FROM historical_kline WHERE stock_code = ?", ("000725",))
        db_execute("DELETE FROM minute_factor_cache WHERE stock_code = ?", ("000725",))
        base = datetime(2026, 1, 1)
        for i in range(60):
            d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            price = 100.0 + i * 0.1
            db_execute(
                """INSERT INTO historical_kline
                   (stock_code, trade_date, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("000725", d, price, price + 0.5, price - 0.5, price, 1000000),
            )
        yield
        # 清理
        db_execute("DELETE FROM historical_kline WHERE stock_code = ?", ("000725",))
        db_execute("DELETE FROM minute_factor_cache WHERE stock_code = ?", ("000725",))

    def test_get_minute_factors(self, client, _seed_kline):
        """GET /api/realtime/factor/{code}/minute 返回正确 JSON"""
        res = client.get("/api/realtime/factor/000725/minute")
        assert res.status_code == 200
        data = res.json()
        assert data["code"] == "000725"
        assert "factors" in data
        assert isinstance(data["factors"], dict)
        assert data["data_source"] == "historical_daily_fallback"
        assert data["bar_count"] > 0

    def test_get_minute_factors_with_names_filter(self, client, _seed_kline):
        """GET ?names=ma5,ma20 只返回指定因子(v4.2.3: +衍生字段)"""
        res = client.get("/api/realtime/factor/000725/minute?names=ma5,ma20")
        assert res.status_code == 200
        data = res.json()
        # v4.2.3: 至少包含 ma5/ma20 + close (衍生字段)
        assert "ma5" in data["factors"]
        assert "ma20" in data["factors"]
        assert "close" in data["factors"]  # 衍生字段自动注入

    def test_get_minute_factors_404(self, client):
        """无 K 线数据 → 404"""
        res = client.get("/api/realtime/factor/NOTEXIST_999999/minute")
        assert res.status_code == 404

    def test_invalidate_endpoint(self, client, _seed_kline):
        """POST /api/realtime/factor/{code}/minute/invalidate 清缓存"""
        # 先调一次确保有 cache
        client.get("/api/realtime/factor/000725/minute?names=ma5")
        # 清缓存
        res = client.post("/api/realtime/factor/000725/minute/invalidate")
        assert res.status_code == 200
        data = res.json()
        assert data["invalidated"] is True


# ═══════════════════════════════════════════════════════════════
#  Legacy 兼容(大写 key)
# ═══════════════════════════════════════════════════════════════


class TestLegacyFactorNameCompat:
    def test_uppercase_factor_name_accepted(self):
        """大写因子名 'MA5' 自动归一化为 'ma5'"""
        closes = [100.0 + i * 0.1 for i in range(60)]
        result = compute_minute_factors(
            code="TEST", closes=closes, factor_names=["MA5", "RSI_14"],
        )
        assert "ma5" in result
        assert "rsi_14" in result
        assert result["ma5"] is not None