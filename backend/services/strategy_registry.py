r"""YAML 策略注册中心 — 自动扫描 backend/strategies/*.yaml

设计灵感来自 quant-trading-system (D:\some-oss\quant-trading-system)
的 strategies/registry.py,但适配 StockAI 的 YAML 策略格式。

核心能力:
  1. 自动扫描:无需手动注册,丢 YAML 进目录即可被发现
  2. mtime 失效:目录/文件变更时自动重扫,无需重启
  3. 校验:validate(strategy_ids) → (valid, invalid),防止 typo 静默通过
  4. 单例:全进程共享一份元信息,避免每次请求扫盘

用法:
    from services.strategy_registry import get_registry

    registry = get_registry()
    all_strategies = registry.scan()          # 扫描并返回
    info = registry.get("turtle_s1")           # 取单个
    valid, invalid = registry.validate(["turtle_s1", "typo"])  # 校验

未来扩展:
  - 热加载:watchdog 监听目录变更,自动 invalidate
  - 版本:每个 YAML 加 version 字段,做版本对比
  - 远程:从 URL 拉取策略(只读)
"""
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class StrategyInfo:
    """单个策略的元信息(从 YAML 解析)"""
    id: str
    name: str
    description: str = ""
    source: str = ""
    source_url: str = ""
    tags: list[str] = field(default_factory=list)
    params: list[dict[str, Any]] = field(default_factory=list)
    market_state: list[str] = field(default_factory=list)
    recommended_position: str = ""
    conditions_count: int = 0
    yaml_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class YamlStrategyRegistry:
    """YAML 策略注册表 — 单例

    mtime-based 失效:每次 scan() 检查目录 mtime,
    与上次扫描时的 mtime 不同则重扫。同目录内单个 YAML 文件被修改,
    也会被检测到(目录 mtime 在大多数 OS 上会因为子文件变更而更新)。
    """

    _instance: "YamlStrategyRegistry | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._strategies: dict[str, StrategyInfo] = {}
            cls._instance._scan_time: float | None = None
            cls._instance._dir_mtime: float | None = None
        return cls._instance

    @property
    def strategies_dir(self) -> str:
        """backend/strategies/ 绝对路径"""
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "strategies",
        )

    def scan(self, force: bool = False) -> list[StrategyInfo]:
        """扫描目录,返回所有策略元信息

        Args:
            force: True 强制重扫(忽略 mtime 缓存)

        Returns:
            StrategyInfo 列表(按 id 排序)
        """
        strategies_dir = self.strategies_dir

        if not os.path.isdir(strategies_dir):
            logger.warning("strategy_registry: strategies 目录不存在: %s", strategies_dir)
            return []

        # mtime 检查:目录没变且已扫过则直接返回缓存
        current_mtime = os.path.getmtime(strategies_dir)
        if (
            not force
            and self._scan_time is not None
            and self._dir_mtime is not None
            and current_mtime == self._dir_mtime
        ):
            return sorted(self._strategies.values(), key=lambda s: s.id)

        new_strategies: dict[str, StrategyInfo] = {}
        for fname in sorted(os.listdir(strategies_dir)):
            if not fname.endswith(".yaml") or fname.startswith(("_", ".")):
                continue
            yaml_path = os.path.join(strategies_dir, fname)
            info = self._parse_yaml(yaml_path)
            if info is not None:
                # id 冲突时:后扫到的覆盖(允许用户 hot-fix)
                new_strategies[info.id] = info

        self._strategies = new_strategies
        self._scan_time = time.time()
        self._dir_mtime = current_mtime
        logger.debug("strategy_registry: 扫描完成,共 %d 个策略", len(new_strategies))
        return sorted(self._strategies.values(), key=lambda s: s.id)

    def get(self, strategy_id: str) -> StrategyInfo | None:
        """按 id 取单个策略(自动触发 scan)"""
        self.scan()
        return self._strategies.get(strategy_id)

    def get_many(self, strategy_ids: list[str]) -> dict[str, StrategyInfo]:
        """批量取(不存在的 id 跳过,不抛错)"""
        self.scan()
        return {
            sid: self._strategies[sid]
            for sid in strategy_ids
            if sid in self._strategies
        }

    def validate(self, strategy_ids: list[str]) -> tuple[list[str], list[str]]:
        """校验 strategy_ids 列表,返回 (valid_ids, invalid_ids)

        用于 run_strategy_backtest 入口:防止用户传 typo 时静默通过
        """
        self.scan()
        valid: list[str] = []
        invalid: list[str] = []
        for sid in strategy_ids:
            if sid in self._strategies:
                valid.append(sid)
            else:
                invalid.append(sid)
        return valid, invalid

    def invalidate(self) -> None:
        """手动失效缓存(下次 scan 强制重扫)"""
        self._scan_time = None
        self._dir_mtime = None

    def _parse_yaml(self, yaml_path: str) -> StrategyInfo | None:
        """解析单个 YAML 文件,失败返回 None(不中断扫描)"""
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.warning("strategy_registry: 解析失败 %s: %s", yaml_path, e)
            return None

        if not isinstance(data, dict):
            logger.warning("strategy_registry: %s 不是有效 dict", yaml_path)
            return None

        # id 缺失则用文件名
        file_id = os.path.basename(yaml_path).replace(".yaml", "")
        return StrategyInfo(
            id=data.get("id", file_id),
            name=data.get("name", file_id),
            description=data.get("description", ""),
            source=data.get("source", ""),
            source_url=data.get("source_url", ""),
            tags=data.get("tags", []) or [],
            params=data.get("params", []) or [],
            market_state=data.get("market_state", []) or [],
            recommended_position=data.get("recommended_position", ""),
            conditions_count=len(data.get("conditions", []) or []),
            yaml_path=yaml_path,
        )


# ═══════════════════════════════════════════════════════════════
#  全局访问入口
# ═══════════════════════════════════════════════════════════════


def get_registry() -> YamlStrategyRegistry:
    """获取全局单例"""
    return YamlStrategyRegistry()


def list_strategies(force: bool = False) -> list[dict]:
    """便捷函数:返回所有策略的 dict 列表(供 API 直接序列化)

    与原 _list_available_strategies() 输出格式兼容,
    便于 router 层零改动接入。
    """
    return [info.to_dict() for info in get_registry().scan(force=force)]