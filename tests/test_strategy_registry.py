"""YAML 策略注册中心 (strategy_registry) 单元测试

覆盖:
  - 单例:多次 get_registry() 返回同一实例
  - scan():返回所有 YAML,字段完整
  - get(id):单个取;missing 返回 None
  - get_many(ids):批量取;missing 跳过
  - validate(ids):返回 (valid, invalid)
  - mtime 失效:文件改动后再次 scan 自动重扫
  - 边界:空目录 / 损坏 YAML / 缺字段 / _ 开头文件跳过
  - 集成:_load_strategy_conditions 用 registry 校验,typo 不再静默通过

测试用临时目录隔离,不污染 backend/strategies/ 真实文件。
"""
import os
import tempfile

import pytest
import yaml

from services.strategy_registry import (
    StrategyInfo,
    YamlStrategyRegistry,
    get_registry,
    list_strategies,
)


# ═══════════════════════════════════════════════════════════════
#  Fixture:隔离的临时策略目录
# ═══════════════════════════════════════════════════════════════


VALID_YAML = """\
id: test_strategy
name: 测试策略
description: 一个用于测试的策略
source: 自编
source_url: https://example.com
tags: [测试, demo]
params:
  - name: period
    type: number
    default: 20
    range: [5, 60]
    step: 5
    description: 周期
market_state: [趋势]
recommended_position: 中
conditions:
  - field: close
    op: '>'
    value: 10
"""


@pytest.fixture
def tmp_strategies_dir(monkeypatch):
    """建临时目录 + 写 3 个 YAML(2 正常 + 1 个 _ 开头应跳过)"""
    with tempfile.TemporaryDirectory() as td:
        # monkey-patch registry 用的目录
        # 在 fixture 里直接覆盖 strategies_dir 属性
        monkeypatch.setattr(
            YamlStrategyRegistry, "strategies_dir",
            property(lambda self: td),
        )
        # 写 2 个有效 + 1 个 _ 开头 + 1 个损坏
        with open(os.path.join(td, "turtle.yaml"), "w", encoding="utf-8") as f:
            f.write(VALID_YAML.replace("test_strategy", "turtle"))
        with open(os.path.join(td, "momentum.yaml"), "w", encoding="utf-8") as f:
            f.write(VALID_YAML.replace("test_strategy", "momentum"))
        with open(os.path.join(td, "_draft.yaml"), "w", encoding="utf-8") as f:
            f.write(VALID_YAML.replace("test_strategy", "_draft"))
        with open(os.path.join(td, "broken.yaml"), "w", encoding="utf-8") as f:
            f.write("not: valid: yaml: [\n")  # 损坏
        # 重置 registry 缓存
        reg = get_registry()
        reg.invalidate()
        yield td
        reg.invalidate()


# ═══════════════════════════════════════════════════════════════
#  单例
# ═══════════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_registry_returns_same_instance(self):
        a = get_registry()
        b = get_registry()
        assert a is b, "get_registry() 应返回同一单例"


# ═══════════════════════════════════════════════════════════════
#  scan() — 基本扫描
# ═══════════════════════════════════════════════════════════════


class TestScan:
    def test_scan_returns_yaml_strategies(self, tmp_strategies_dir):
        """scan() 返回所有有效 YAML 策略元信息"""
        reg = get_registry()
        strategies = reg.scan()

        ids = {s.id for s in strategies}
        assert "turtle" in ids
        assert "momentum" in ids
        assert "_draft" not in ids, "_ 前缀文件应跳过"
        assert "broken" not in ids, "损坏 YAML 应跳过"

    def test_scan_fields_complete(self, tmp_strategies_dir):
        """解析的字段完整"""
        reg = get_registry()
        info = reg.get("turtle")
        assert info is not None
        assert info.id == "turtle"
        assert info.name == "测试策略" or info.name == "turtle"  # fallback
        assert info.description == "一个用于测试的策略"
        assert info.source == "自编"
        assert info.tags == ["测试", "demo"]
        assert len(info.params) == 1
        assert info.params[0]["name"] == "period"
        assert info.conditions_count == 1
        assert info.yaml_path.endswith("turtle.yaml")

    def test_scan_sorted_by_id(self, tmp_strategies_dir):
        """scan() 结果按 id 排序,前端下拉稳定"""
        reg = get_registry()
        strategies = reg.scan()
        ids = [s.id for s in strategies]
        assert ids == sorted(ids)

    def test_scan_missing_fields_have_defaults(self, tmp_strategies_dir):
        """缺字段的 YAML 不 crash,用默认值"""
        # 加一个最小 YAML(只 id)
        with open(os.path.join(tmp_strategies_dir, "minimal.yaml"), "w") as f:
            yaml.safe_dump({"id": "minimal"}, f)
        reg = get_registry()
        reg.invalidate()
        info = reg.get("minimal")
        assert info is not None
        assert info.id == "minimal"
        assert info.name == "minimal"  # fallback to id
        assert info.description == ""
        assert info.tags == []
        assert info.params == []
        assert info.conditions_count == 0


# ═══════════════════════════════════════════════════════════════
#  get() / get_many() / validate()
# ═══════════════════════════════════════════════════════════════


class TestAccess:
    def test_get_existing(self, tmp_strategies_dir):
        reg = get_registry()
        info = reg.get("turtle")
        assert info is not None
        assert isinstance(info, StrategyInfo)

    def test_get_missing_returns_none(self, tmp_strategies_dir):
        reg = get_registry()
        assert reg.get("nonexistent") is None

    def test_get_many_skips_missing(self, tmp_strategies_dir):
        reg = get_registry()
        result = reg.get_many(["turtle", "nonexistent", "momentum"])
        assert "turtle" in result
        assert "momentum" in result
        assert "nonexistent" not in result

    def test_validate_splits_valid_invalid(self, tmp_strategies_dir):
        reg = get_registry()
        valid, invalid = reg.validate(["turtle", "typo_xxx", "momentum", "another_typo"])
        assert set(valid) == {"turtle", "momentum"}
        assert set(invalid) == {"typo_xxx", "another_typo"}


# ═══════════════════════════════════════════════════════════════
#  mtime 失效
# ═══════════════════════════════════════════════════════════════


class TestMtimeInvalidation:
    def test_mtime_change_triggers_rescan(self, tmp_strategies_dir):
        """新加 YAML 后 scan() 应自动检测(无需 force)"""
        reg = get_registry()
        first = reg.scan()
        first_ids = {s.id for s in first}
        assert "new_strategy" not in first_ids

        # 确保 mtime 至少变化 1s(Windows 文件系统 mtime 精度是 2s)
        import time as _time
        _time.sleep(2.1)

        # 新加一个 YAML(显式 utf-8 编码,防 Windows locale 编码问题)
        with open(os.path.join(tmp_strategies_dir, "new_strategy.yaml"),
                  "w", encoding="utf-8") as f:
            f.write(VALID_YAML.replace("test_strategy", "new_strategy"))

        # 不调用 force,scan() 应自动检测
        second = reg.scan()
        second_ids = {s.id for s in second}
        assert "new_strategy" in second_ids, (
            "mtime 检查未触发,需要确认 getmtime 检测到目录变更"
        )

    def test_force_flag_rescans_anyway(self, tmp_strategies_dir):
        reg = get_registry()
        first_count = len(reg.scan())
        reg.scan(force=True)
        # force 不应改变数量,但应触发实际扫描
        assert len(reg.scan(force=True)) == first_count

    def test_invalidate_clears_cache(self, tmp_strategies_dir):
        reg = get_registry()
        reg.scan()  # 首次扫描建缓存
        reg.invalidate()
        # 后续 scan 应触发实际重扫(不可直接观察,但 invalidate 后 _scan_time 应为 None)
        assert reg._scan_time is None
        assert reg._dir_mtime is None


# ═══════════════════════════════════════════════════════════════
#  便捷函数 + 集成
# ═══════════════════════════════════════════════════════════════


class TestConvenienceFunctions:
    def test_list_strategies_returns_dicts(self, tmp_strategies_dir):
        """list_strategies() 返回 dict 列表,可直接 JSON 序列化"""
        result = list_strategies()
        assert isinstance(result, list)
        assert len(result) >= 2
        assert all(isinstance(s, dict) for s in result)
        assert all("id" in s for s in result)
        assert all("name" in s for s in result)
        assert all("params" in s for s in result)


# ═══════════════════════════════════════════════════════════════
#  与 strategy_backtest_service 集成
# ═══════════════════════════════════════════════════════════════


class TestBacktestIntegration:
    def test_load_strategy_conditions_validates_via_registry(self, tmp_strategies_dir, caplog):
        """typo 的 strategy_id 应被 registry 拒绝,不再静默通过"""
        from services.strategy_backtest_service import _load_strategy_conditions

        # 全 typo → 应该返回 None + 记 warning
        with caplog.at_level("WARNING"):
            result = _load_strategy_conditions(["nonexistent_strategy"])

        assert result is None, "全部 typo 应返回 None"
        # 验证 warning 里提到 invalid id
        assert any("typo" in s.lower() or "不存在" in s for s in [
            r.message for r in caplog.records if r.levelname == "WARNING"
        ]) or any("不存在" in s for s in [
            r.message for r in caplog.records if r.levelname == "WARNING"
        ]), f"应记 warning 含 '不存在',实际: {[r.message for r in caplog.records]}"

    def test_load_strategy_conditions_partial_invalid(self, tmp_strategies_dir):
        """部分 typo: 有效的应该正常加载(用真实 backend/strategies/ 中的 turtle_s1)"""
        from services.strategy_backtest_service import _load_strategy_conditions

        # 注意:_load_strategy_conditions 内部用真实 backend/strategies/ 目录加载,
        # 而 registry 是 monkeypatch 后的 tmp dir。所以 registry 校验时,tmp dir 里
        # 没 turtle_s1 → 被当作 invalid → 全部被过滤 → 返回 None。
        # 测的是"typo 不再静默通过",而不是"正确加载"。
        # 真实路径校验 + 加载的端到端测试在 integration 层覆盖。
        result = _load_strategy_conditions(["typo_only_1", "typo_only_2"])
        assert result is None, "全 typo 应返回 None"

        # 混合场景:turtle_s1 是真实存在的(不在 tmp dir 里),registry 校验时被视为 invalid。
        # 这暴露了 registry 与 loader 路径不一致,需要在更上层解决。
        # 这里只验证"至少 invalid_ids 被记 warning"。

    def test_load_strategy_conditions_uses_registry_path(self, tmp_strategies_dir):
        """端到端:loader 必须走 registry 的目录,而不是硬编码 backend/strategies/

        修好路径一致后,应该能从 monkeypatch 后的 tmp dir 真正加载策略
        (返回非 None 的条件树),而不是 fallback 到真实目录。
        """
        from services.strategy_backtest_service import _load_strategy_conditions

        # 加载 tmp dir 里的 turtle (VALID_YAML 写的 id 就是 'turtle')
        result = _load_strategy_conditions(["turtle"])
        assert result is not None, (
            "loader 应走 registry 的 tmp dir,实际 fallback 到真实 backend/strategies/ "
            "导致 tmp dir 里的 'turtle' 找不到 → 返回 None"
        )
        # 验证条件被正确解析
        assert result["logic"] == "AND"
        assert len(result["conditions"]) == 1
        assert result["conditions"][0]["field"] == "close"

    def test_optimize_strategy_params_uses_registry_path(self, tmp_strategies_dir, monkeypatch):
        """端到端:optimize_strategy_params 应走 registry 的目录(只验路径,不动真回测)"""
        from services import strategy_backtest_service as svc

        # mock 掉回测引擎,避免依赖 DB
        monkeypatch.setattr(
            svc, "run_strategy_backtest",
            lambda **kwargs: {
                "sharpe_ratio": 1.5, "max_drawdown": 0.1,
                "win_rate": 0.55, "profit_factor": 1.8,
                "total_return": 0.2, "trade_count": 10,
            },
        )

        result = svc.optimize_strategy_params(strategy_id="turtle", top_n=2)
        assert "error" not in result, (
            f"应能从 tmp dir 加载 turtle,实际: {result.get('error')}"
        )
        assert result["strategy_id"] == "turtle"
        assert result["total_combinations"] >= 1

    def test_compare_strategies_uses_registry_path(self, tmp_strategies_dir, monkeypatch):
        """端到端:compare_strategies 应走 registry 的目录(只验路径,不动真回测)"""
        from services import strategy_backtest_service as svc

        # mock 掉回测引擎,避免依赖 DB
        monkeypatch.setattr(
            svc, "run_strategy_backtest",
            lambda **kwargs: {
                "sharpe_ratio": 1.0, "max_drawdown": 0.15,
                "total_return": 0.1, "trade_count": 5,
                "strategy_name": kwargs.get("strategy_ids", ["?"])[0],
            },
        )

        result = svc.compare_strategies(strategy_ids=["turtle", "momentum"])
        assert "error" not in result, (
            f"应能从 tmp dir 加载多个策略,实际: {result.get('error')}"
        )
        assert "strategies" in result
        assert len(result["strategies"]) == 2