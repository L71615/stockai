"""v4.2.4 leaderboard 向量化 + 缓存回归测试

测试三件事:
1. _pearson_daily 向量化结果 == 原 per-date 循环结果 (数值误差 < 1e-9)
2. get_cached_leaderboard 5min TTL 行为 (miss / hit / invalidate / TTL 过期)
3. per-key asyncio.Lock 防止并发双算

不依赖数据库 — 用纯 DataFrame + monkeypatch fake compute 函数。
"""
import asyncio
import time

import numpy as np
import pandas as pd
import pytest

from services.factor_lab import (
    LEADERBOARD_CACHE_TTL,
    _pearson_daily,
    get_cached_leaderboard,
    invalidate_leaderboard_cache,
)


# ═════════════════════════════════════════════════════════════
#  辅助:构造测试 panel
# ═════════════════════════════════════════════════════════════


def _build_panels(n_dates: int = 30, n_stocks: int = 60, seed: int = 42):
    """构造测试用 factor / return 面板 (不依赖数据库)"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="D")
    stocks = [f"S{i:04d}" for i in range(n_stocks)]
    factor = pd.DataFrame(
        rng.normal(0, 1, (n_dates, n_stocks)), index=dates, columns=stocks
    )
    returns = pd.DataFrame(
        rng.normal(0.001, 0.02, (n_dates, n_stocks)), index=dates, columns=stocks
    )
    # 故意撒一些 NaN 触发 mask 路径
    factor.iloc[0, :3] = np.nan
    returns.iloc[5, 10:13] = np.nan
    return factor, returns


def _reference_pearson_loop(factor: pd.DataFrame, return_panel: pd.DataFrame) -> pd.Series:
    """v4.2.4 之前的 per-date 循环实现,作为 ground truth 参考"""
    forward_returns = return_panel.shift(-1)
    ic_values = {}
    for date in factor.index:
        f = factor.loc[date].dropna()
        r = forward_returns.loc[date].dropna()
        common = f.index.intersection(r.index)
        if len(common) < 30:
            continue
        f_vals = f[common].values.astype(float)
        r_vals = r[common].values.astype(float)
        if np.std(f_vals) < 1e-9 or np.std(r_vals) < 1e-9:
            continue
        try:
            corr = np.corrcoef(f_vals, r_vals)[0, 1]
            if not np.isnan(corr):
                ic_values[date] = float(corr)
        except Exception:
            continue
    return pd.Series(ic_values).sort_index()


# ═════════════════════════════════════════════════════════════
#  P0-1: _pearson_daily 向量化数值一致性
# ═════════════════════════════════════════════════════════════


class TestPearsonDailyVectorization:
    """v4.2.4 向量化必须和原 per-date 循环结果一致 (数值误差 < 1e-9)"""

    def test_matches_reference_loop_with_nans(self):
        """正常含 NaN 数据: 向量化 == 循环 (误差 < 1e-9)"""
        factor, returns = _build_panels()
        vector_result = _pearson_daily(factor, returns)
        ref_result = _reference_pearson_loop(factor, returns)

        # 索引必须完全一致 (sort_index 后)
        assert vector_result.index.equals(ref_result.index), (
            f"index mismatch:\n  vector={vector_result.index}\n  ref={ref_result.index}"
        )
        # 数值误差 < 1e-9 (NumPy 浮点累加顺序差异)
        np.testing.assert_allclose(
            vector_result.values,
            ref_result.values,
            atol=1e-9,
            err_msg="向量化 Pearson 与参考循环数值不一致",
        )

    def test_matches_reference_loop_no_nans(self):
        """全有效数据: 数值一致性"""
        factor, returns = _build_panels(n_dates=20, n_stocks=100, seed=7)
        vector_result = _pearson_daily(factor, returns)
        ref_result = _reference_pearson_loop(factor, returns)
        np.testing.assert_allclose(
            vector_result.values, ref_result.values, atol=1e-9
        )

    def test_matches_reference_loop_perfect_correlation(self):
        """完美正相关: Pearson == 1.0
        注意: _pearson_daily 算的是 Pearson(factor[t], forward_returns[t])
        其中 forward_returns[t] = returns.shift(-1)[t] = returns[t+1]
        所以要让 returns[t+1] = factor[t] * 2 + 1, 才能得到 Pearson == 1.0
        """
        n = 50
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        stocks = [f"S{i}" for i in range(n)]
        factor = pd.DataFrame(np.random.randn(5, n), index=dates, columns=stocks)
        returns = pd.DataFrame(
            np.random.randn(5, n), index=dates, columns=stocks
        )  # 填充垃圾数据, 下面覆盖 t+1 行
        # 让 returns 的 t+1 行 = factor 的 t 行的完美线性函数
        for i in range(len(dates) - 1):
            returns.iloc[i + 1, :] = factor.iloc[i, :] * 2.0 + 1.0
        result = _pearson_daily(factor, returns)
        # 日期 0..3 都应得到 Pearson == 1.0 (日期 4 因 shift(-1) 是 NaN 排除)
        valid = result.dropna()
        assert len(valid) == 4
        np.testing.assert_allclose(valid.values, np.ones(len(valid)), atol=1e-9)

    def test_filters_low_valid_count(self):
        """valid count < 30 时该日被排除"""
        factor = pd.DataFrame(
            np.random.randn(5, 10),  # 只 10 只股 < 30 阈值
            columns=[f"S{i}" for i in range(10)],
        )
        returns = factor.copy()
        result = _pearson_daily(factor, returns)
        assert len(result) == 0

    def test_filters_zero_variance(self):
        """某日 factor 标准差为 0 → 该日被排除

        注意: _pearson_daily 内部 forward_returns = returns.shift(-1),
        所以最后一个日期 (date 2) 对应的 forward_returns 是整行 NaN,
        valid_count = 0, 也会被排除。
        """
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        factor = pd.DataFrame(
            np.random.randn(3, 50), index=dates, columns=[f"S{i}" for i in range(50)]
        )
        returns = pd.DataFrame(
            np.random.randn(3, 50), index=dates, columns=[f"S{i}" for i in range(50)]
        )
        # 中间日期 factor 全 0 → std = 0
        factor.iloc[1, :] = 0.0
        result = _pearson_daily(factor, returns)
        # 只保留 date 0:
        # - date 0: factor 非零 std, returns 也有值 → 保留
        # - date 1: factor 全 0 → std=0 → 排除
        # - date 2: forward_returns = shift(-1) 最后一行 = NaN → 排除
        assert len(result) == 1
        assert dates[0] in result.index
        assert dates[1] not in result.index
        assert dates[2] not in result.index

    def test_handles_all_nan(self):
        """全 NaN 输入 → 空 Series (不崩)"""
        factor = pd.DataFrame(
            [[np.nan] * 5] * 3, columns=[f"S{i}" for i in range(5)]
        )
        returns = factor.copy()
        result = _pearson_daily(factor, returns)
        assert isinstance(result, pd.Series)
        assert len(result) == 0


# ═════════════════════════════════════════════════════════════
#  P0-2: get_cached_leaderboard 缓存行为
# ═════════════════════════════════════════════════════════════


class TestCachedLeaderboard:
    """5min TTL 内存缓存 + per-key asyncio.Lock"""

    def setup_method(self):
        """每个 test 前清缓存,避免污染"""
        invalidate_leaderboard_cache()

    def teardown_method(self):
        invalidate_leaderboard_cache()

    def _run(self, coro):
        """同步跑 async — pytest 默认不 await"""
        return asyncio.run(coro)

    def test_first_call_miss_second_call_hit(self, monkeypatch):
        """首次 miss → 写入缓存 → 二次 hit (不再调 compute)"""
        call_count = [0]

        def fake_compute(factors, stock_pool, start_date, end_date):
            call_count[0] += 1
            return {
                "factors": factors,
                "stock_pool": stock_pool,
                "call_id": call_count[0],
            }

        monkeypatch.setattr(
            "services.factor_lab.compute_factor_leaderboard", fake_compute
        )

        kwargs = dict(
            factors=["ret_5d", "rsi_14"],
            stock_pool="hs300",
            start_date="2025-01-01",
            end_date="2025-06-30",
        )
        # 第一次
        data1, hit1 = self._run(get_cached_leaderboard(**kwargs))
        assert hit1 is False, "首次应 miss"
        assert data1["call_id"] == 1
        assert call_count[0] == 1

        # 第二次 — 命中缓存
        data2, hit2 = self._run(get_cached_leaderboard(**kwargs))
        assert hit2 is True, "二次应 hit"
        assert data2["call_id"] == 1, "缓存命中应返回旧 data"
        assert call_count[0] == 1, "fake_compute 不应被调第二次"

    def test_different_keys_cached_separately(self, monkeypatch):
        """不同 cache key (stock_pool / dates) 独立缓存"""
        call_count = [0]

        def fake_compute(factors, stock_pool, start_date, end_date):
            call_count[0] += 1
            return {"pool": stock_pool, "call_id": call_count[0]}

        monkeypatch.setattr(
            "services.factor_lab.compute_factor_leaderboard", fake_compute
        )

        # 三个不同 key
        self._run(get_cached_leaderboard(stock_pool="hs300"))
        self._run(get_cached_leaderboard(stock_pool="zz500"))
        self._run(get_cached_leaderboard(
            start_date="2024-01-01", end_date="2024-12-31",
        ))
        assert call_count[0] == 3, "三个不同 key 应各算一次"

        # 各自再调应全 hit
        _, h1 = self._run(get_cached_leaderboard(stock_pool="hs300"))
        _, h2 = self._run(get_cached_leaderboard(stock_pool="zz500"))
        _, h3 = self._run(get_cached_leaderboard(
            start_date="2024-01-01", end_date="2024-12-31",
        ))
        assert h1 and h2 and h3, "三个 key 各自应 hit"
        assert call_count[0] == 3, "hit 不应再调 compute"

    def test_factors_sorted_to_canonical_key(self, monkeypatch):
        """factors 列表顺序不影响 cache key (sorted 后)"""
        call_count = [0]

        def fake_compute(factors, stock_pool, start_date, end_date):
            call_count[0] += 1
            return {"call_id": call_count[0]}

        monkeypatch.setattr(
            "services.factor_lab.compute_factor_leaderboard", fake_compute
        )

        # 同 factors 但顺序不同
        self._run(get_cached_leaderboard(factors=["a", "b", "c"], stock_pool="hs300"))
        self._run(get_cached_leaderboard(factors=["c", "a", "b"], stock_pool="hs300"))
        self._run(get_cached_leaderboard(factors=["b", "c", "a"], stock_pool="hs300"))

        assert call_count[0] == 1, "factors 排序不同应是同一 key"

    def test_invalidate_clears_cache(self, monkeypatch):
        """invalidate_leaderboard_cache 后下次调用 miss"""
        call_count = [0]

        def fake_compute(factors, stock_pool, start_date, end_date):
            call_count[0] += 1
            return {"call_id": call_count[0]}

        monkeypatch.setattr(
            "services.factor_lab.compute_factor_leaderboard", fake_compute
        )

        # 填充
        _, hit1 = self._run(get_cached_leaderboard())
        assert hit1 is False
        # 命中
        _, hit2 = self._run(get_cached_leaderboard())
        assert hit2 is True
        # 失效
        invalidate_leaderboard_cache()
        # 再调应 miss
        _, hit3 = self._run(get_cached_leaderboard())
        assert hit3 is False
        assert call_count[0] == 2

    def test_ttl_expiry_triggers_recompute(self, monkeypatch):
        """TTL 过期后下次调用 miss (重算)"""
        # 把 TTL 调到 0.1s 加速测试
        monkeypatch.setattr("services.factor_lab.LEADERBOARD_CACHE_TTL", 0.1)

        call_count = [0]

        def fake_compute(factors, stock_pool, start_date, end_date):
            call_count[0] += 1
            return {"call_id": call_count[0]}

        monkeypatch.setattr(
            "services.factor_lab.compute_factor_leaderboard", fake_compute
        )

        # 第一次
        _, h1 = self._run(get_cached_leaderboard())
        assert h1 is False
        # 立刻再调 — hit
        _, h2 = self._run(get_cached_leaderboard())
        assert h2 is True
        # 等 TTL 过期
        time.sleep(0.15)
        # 第三次 — miss
        _, h3 = self._run(get_cached_leaderboard())
        assert h3 is False
        assert call_count[0] == 2

    def test_concurrent_calls_only_compute_once(self, monkeypatch):
        """per-key asyncio.Lock: 并发调用同一个 key 只算一次

        注意: compute_factor_leaderboard 走 asyncio.to_thread 跑在线程池里,
        slow_compute 是 sync 函数 → 必须用 threading.Event 而不是 asyncio.Event
        """
        import threading

        call_count = [0]
        compute_started = threading.Event()
        compute_can_finish = threading.Event()

        def slow_compute(factors, stock_pool, start_date, end_date):
            call_count[0] += 1
            compute_started.set()
            # 故意卡住等另一个并发协程进 lock
            compute_can_finish.wait(timeout=5)
            return {"call_id": call_count[0]}

        monkeypatch.setattr(
            "services.factor_lab.compute_factor_leaderboard", slow_compute
        )

        async def race():
            t1 = asyncio.create_task(get_cached_leaderboard(stock_pool="hs300"))
            # 等第一个协程开始计算
            await asyncio.sleep(0.05)
            t2 = asyncio.create_task(get_cached_leaderboard(stock_pool="hs300"))
            # 等 t2 拿到 lock (双检锁的第二检看到缓存已写入)
            await asyncio.sleep(0.05)
            compute_can_finish.set()
            return await t1, await t2

        (d1, h1), (d2, h2) = self._run(race())
        assert call_count[0] == 1, (
            f"per-key lock 应保证只算一次, 实际 {call_count[0]} 次"
        )
        # 两个结果应相同 (t2 走双检锁 hit)
        assert d1 == d2
        # 第一个 miss, 第二个 hit (双检锁命中刚写入的缓存)
        assert h1 is False
        assert h2 is True

    def test_concurrent_different_keys_compute_each_once(self, monkeypatch):
        """并发调用不同 key → 各自算一次 (锁不互斥不同 key)"""
        call_count = [0]

        def fake_compute(factors, stock_pool, start_date, end_date):
            call_count[0] += 1
            return {"pool": stock_pool, "call_id": call_count[0]}

        monkeypatch.setattr(
            "services.factor_lab.compute_factor_leaderboard", fake_compute
        )

        async def race():
            return await asyncio.gather(
                get_cached_leaderboard(stock_pool="hs300"),
                get_cached_leaderboard(stock_pool="zz500"),
                get_cached_leaderboard(stock_pool="sz50"),
            )

        results = self._run(race())
        assert call_count[0] == 3, f"三个不同 key 应各算一次, 实际 {call_count[0]}"
        assert all(not hit for _, hit in results), "三个并发首次都应 miss"


# ═════════════════════════════════════════════════════════════
#  P0-3: 向量化性能 smoke test (可选, 跳过时不报错)
# ═════════════════════════════════════════════════════════════


class TestPearsonDailyPerformance:
    """向量化版本必须显著快于 per-date 循环 (smoke test)"""

    @pytest.mark.skipif(
        not hasattr(np, "__version__"),
        reason="性能 smoke 需要 NumPy",
    )
    def test_vectorized_faster_than_loop(self):
        """向量化 < 循环 / 5 (保守阈值, 防止 CI 抖动误判)"""
        factor, returns = _build_panels(n_dates=240, n_stocks=500)

        # 循环
        t0 = time.perf_counter()
        _reference_pearson_loop(factor, returns)
        loop_time = time.perf_counter() - t0

        # 向量化
        t0 = time.perf_counter()
        _pearson_daily(factor, returns)
        vec_time = time.perf_counter() - t0

        assert vec_time < loop_time / 5, (
            f"向量化应至少快 5x: loop={loop_time:.3f}s vec={vec_time:.3f}s"
        )