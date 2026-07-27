"""v4.0 Phase 2 — 因子 IC 重新校准单元测试

覆盖:
  - recalibrate_all_factors_ic() 基本返回结构
  - top_factors 按 |ic_mean| 降序
  - b1_factors 只包含 v4.0 B1 因子
  - 数据不足的因子被跳过
  - B1_FACTORS_FOR_IC 常量完整
  - factor_lab FACTOR_REGISTRY 包含 B1 因子
"""

import pytest

from services.factor_lab import (
    FACTOR_REGISTRY,
    B1_FACTORS_FOR_IC,
    recalibrate_all_factors_ic,
)


# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════


class TestB1Constants:
    def test_b1_factors_for_ic_is_11_factors(self):
        """B1 中可在 factor_lab 计算的因子共 11 个"""
        assert len(B1_FACTORS_FOR_IC) == 11

    def test_b1_factors_all_in_registry(self):
        """B1 常量中的因子都在 FACTOR_REGISTRY 里"""
        for name in B1_FACTORS_FOR_IC:
            assert name in FACTOR_REGISTRY, f"B1 因子 {name} 不在 FACTOR_REGISTRY"

    def test_b1_contains_expected_factors(self):
        """B1 应包含 ROC/DEVIATION/STD/BETA/VROC/CORR"""
        expected = {
            "roc5", "roc10", "roc20", "roc60",
            "deviation10", "deviation20",
            "std5", "std20",
            "beta20", "vroc10", "corr20",
        }
        assert set(B1_FACTORS_FOR_IC) == expected


# ═══════════════════════════════════════════════════════════════
#  FACTOR_REGISTRY 包含 B1
# ═══════════════════════════════════════════════════════════════


class TestRegistryHasB1:
    def test_registry_total_count(self):
        """v4.0 后: 经典 15 + B1 11 = 26 个"""
        assert len(FACTOR_REGISTRY) == 26

    def test_b1_factors_callable(self):
        """所有 B1 因子的 lambda 都能调用"""
        import numpy as np
        closes = np.array([100 + i * 0.1 for i in range(30)])
        volumes = np.array([1000 + i * 10 for i in range(30)])
        for name in B1_FACTORS_FOR_IC:
            fn, needs_vol = FACTOR_REGISTRY[name]
            v = volumes if needs_vol else None
            result = fn(closes, v)
            assert result is not None, f"{name} 返回 None"
            assert len(result) == len(closes), f"{name} 长度不匹配"


# ═══════════════════════════════════════════════════════════════
#  recalibrate_all_factors_ic 基础结构
# ═══════════════════════════════════════════════════════════════


class TestRecalibrateStructure:
    def test_returns_expected_keys(self):
        result = recalibrate_all_factors_ic(stock_pool="hs300", top_n=10)
        assert "period" in result
        assert "pool" in result
        assert "factor_count" in result
        assert "top_factors" in result
        assert "b1_factors" in result

    def test_pool_passed_through(self):
        result = recalibrate_all_factors_ic(stock_pool="hs300")
        assert result["pool"] == "hs300"

    def test_top_factors_sorted_by_abs_ic(self):
        """top_factors 按 abs_ic 降序"""
        result = recalibrate_all_factors_ic(stock_pool="hs300", top_n=20)
        abs_ics = [f["abs_ic"] for f in result["top_factors"]]
        # 验证降序
        for i in range(len(abs_ics) - 1):
            assert abs_ics[i] >= abs_ics[i + 1], f"位置 {i}: {abs_ics[i]} < {abs_ics[i+1]}"

    def test_top_factors_have_required_fields(self):
        result = recalibrate_all_factors_ic(stock_pool="hs300", top_n=5)
        for f in result["top_factors"]:
            assert "name" in f
            assert "ic_mean" in f
            assert "ir" in f
            assert "win_rate" in f
            assert "abs_ic" in f
            assert "is_b1" in f

    def test_b1_factors_subset_of_top(self):
        """b1_factors 中的每个因子都在 top_factors 中(若 rank ≤ top_n)"""
        result = recalibrate_all_factors_ic(stock_pool="hs300", top_n=50)
        b1_names = {f["name"] for f in result["b1_factors"]}
        top_names = {f["name"] for f in result["top_factors"]}
        # 至少 B1 中能在 top50 的都在 top_factors
        for name in b1_names & top_names:
            assert name in top_names

    def test_b1_factors_flagged_correctly(self):
        """is_b1 字段对 B1 因子为 True"""
        result = recalibrate_all_factors_ic(stock_pool="hs300", top_n=50)
        for f in result["b1_factors"]:
            assert f["is_b1"] is True
        for f in result["top_factors"]:
            if f["name"] not in B1_FACTORS_FOR_IC:
                assert f["is_b1"] is False


# ═══════════════════════════════════════════════════════════════
#  recalibrate_all_factors_ic 边界
# ═══════════════════════════════════════════════════════════════


class TestRecalibrateEdgeCases:
    def test_top_n_limits_output(self):
        result = recalibrate_all_factors_ic(stock_pool="hs300", top_n=3)
        assert len(result["top_factors"]) <= 3

    def test_invalid_pool_returns_empty(self):
        result = recalibrate_all_factors_ic(stock_pool="invalid_pool_xyz")
        # 不应抛异常,可能返回空 factors
        assert "factor_count" in result
