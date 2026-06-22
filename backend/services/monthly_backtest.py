"""
月度因子回测引擎 — 源自 moonshot 项目

核心逻辑:
  1. 按月重采样日线数据（Polars 加速）
  2. 连续因子 → 分层信号（qcut → -1/0/1）
  3. COO (建仓) vs MOM (持仓) 收益区分
  4. 多因子信号融合 + 多空组合
  5. 前复权价格调整
  6. 多权重方案 (等权/市值/因子评分) — 源自 QuantLessMoneyMore
  7. 仓位限制 (max_weight/max_turnover) — 源自 QuantLessMoneyMore

依赖: factor_utils (绩效指标), pandas, polars
"""

import logging
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger("stockai")


# ═══════════════════════════════════════════════════════════════
#  helper.py → 月度重采样 & 前复权 (Polars 加速)
# ═══════════════════════════════════════════════════════════════

def resample_to_month(data: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    按月重采样日线数据（Polars 实现）

    Args:
        data: 需包含 'date' 和 'asset' 列
        **kwargs: 列名=聚合方式 (first/last/mean/max/min/sum)

    Returns:
        MultiIndex(month, asset) 的月度 DataFrame

    Example:
        monthly = resample_to_month(df, open="first", close="last", volume="sum")
    """
    try:
        import polars as pl
        if not kwargs:
            raise ValueError("至少需要指定一个列的聚合方式")

        df_raw = pl.from_pandas(data).lazy()
        df_raw = df_raw.with_columns(pl.col("date").cast(pl.Datetime))

        df_raw = df_raw.with_columns(
            pl.concat_str([
                pl.col("date").dt.year().cast(pl.Utf8),
                pl.lit("-"),
                pl.col("date").dt.month().cast(pl.Utf8).str.pad_start(2, fill_char="0"),
            ]).alias("month")
        )

        agg_methods = {
            "first": lambda col: col.sort_by(pl.col("date")).first(),
            "last":  lambda col: col.sort_by(pl.col("date")).last(),
            "mean":  lambda col: col.mean(),
            "max":   lambda col: col.max(),
            "min":   lambda col: col.min(),
            "sum":   lambda col: col.sum(),
        }

        agg_exprs = []
        for col_name, method in kwargs.items():
            if method not in agg_methods:
                raise ValueError(f"不支持的聚合方式: {method}")
            agg_exprs.append(agg_methods[method](pl.col(col_name)).alias(col_name))

        result = (
            df_raw.group_by(pl.col("asset"), pl.col("month"))
            .agg(agg_exprs)
            .sort(pl.col("month"), pl.col("asset"))
            .collect()
            .to_pandas()
        )
        result["month"] = pd.PeriodIndex(result["month"], freq="M")
        return result.set_index(["month", "asset"])
    except Exception:
        logger.warning("resample_to_month failed", exc_info=True)
        return pd.DataFrame()


def qfq_adjustment(df: pd.DataFrame, adj_factor_col: str = "adjust") -> pd.DataFrame:
    """
    前复权算法（Polars 实现）

    以最新复权因子为基准，调整历史 OHLCV。
    价格: price * adj_factor / latest_adj_factor
    成交量: volume * latest_adj_factor / adj_factor (反向调整)
    """
    try:
        import polars as pl
        if df.empty:
            return df.copy()

        lf = pl.from_pandas(df).lazy()
        result = (
            lf.with_columns(
                [pl.col(adj_factor_col).last().over("asset").alias("latest_adj")]
            )
            .with_columns([
                (pl.col("open") * pl.col(adj_factor_col) / pl.col("latest_adj")).alias("open"),
                (pl.col("high") * pl.col(adj_factor_col) / pl.col("latest_adj")).alias("high"),
                (pl.col("low") * pl.col(adj_factor_col) / pl.col("latest_adj")).alias("low"),
                (pl.col("close") * pl.col(adj_factor_col) / pl.col("latest_adj")).alias("close"),
                (pl.col("volume") * pl.col("latest_adj") / pl.col(adj_factor_col)).alias("volume"),
            ])
            .drop("latest_adj")
            .collect()
        )
        return result.to_pandas()
    except Exception:
        logger.warning("qfq_adjustment failed", exc_info=True)
        return df


# ═══════════════════════════════════════════════════════════════
#  moonshot.py → 月度因子回测核心
# ═══════════════════════════════════════════════════════════════

class MonthlyBacktest:
    """
    月度因子回测引擎

    用法:
        bt = MonthlyBacktest(daily_bars)        # 日线 OHLCV
        bt.append_factor(factor_df, "momentum", quantiles=5)
        strategy_ret, bench_ret = bt.run()
        metrics = bt.evaluate(strategy_ret, bench_ret)
    """

    def __init__(self, daily_bars: pd.DataFrame):
        """
        Args:
            daily_bars: columns=[date, asset, open, close],
                        date 为 datetime, 需已复权
        """
        self.data = resample_to_month(daily_bars, open="first", close="last")
        self.factor_names: list[str] = []
        self.factor_transformers: list = []
        self.strategy_returns: Optional[pd.Series] = None
        self.benchmark_returns: Optional[pd.Series] = None
        self.quantile_returns: Optional[pd.DataFrame] = None

    # ── 辅助 ──

    def _is_signals(self, factor: pd.Series) -> bool:
        return set(factor.unique()).issubset({-1, 0, 1})

    def _is_month_indexed(self, df: pd.DataFrame | pd.Series) -> bool:
        return isinstance(df.index, pd.MultiIndex) and df.index.names == ["month", "asset"]

    # ── 因子注入 ──

    def append_factor(
        self,
        data: pd.DataFrame | pd.Series,
        factor_col: str,
        quantiles: Optional[int] = None,
        resample: Optional[str] = None,
        transform: Optional[Callable] = None,
    ) -> None:
        """
        注入因子数据

        Args:
            data: 含 date/asset/factor_col 的 DataFrame
            factor_col: 因子列名
            quantiles: 连续因子分层数 (如5 → 按月qcut → -1/0/1信号)
            resample: 重采样方式 (first/last/mean 等)
            transform: 因子转换函数
        """
        if isinstance(data, pd.Series):
            data = data.to_frame(name=factor_col)

        if factor_col in self.data.columns:
            raise ValueError(f"因子已存在: {factor_col}")

        self.factor_names.append(factor_col)

        if quantiles is None and transform is None and not self._is_signals(data[factor_col]):
            raise ValueError("因子必须是信号数据(-1/0/1)，或提供 quantiles/transform 参数")

        self.factor_transformers.append(quantiles or transform)

        factor_data = data.copy()
        if not self._is_month_indexed(factor_data):
            if resample is None:
                raise ValueError("非月度索引数据需指定 resample 参数")
            factor_data = resample_to_month(factor_data, **{factor_col: resample})

        self.data[factor_col] = factor_data[factor_col]

    # ── 运行 ──

    def run(self, long_only: bool = True) -> tuple[pd.Series, pd.Series]:
        """运行回测，返回 (策略收益, 基准收益)"""
        if not self.factor_names:
            raise ValueError("请先用 append_factor 添加因子")

        self.benchmark_returns = self._benchmark()
        self.strategy_returns = (
            self._single_factor(long_only)
            if len(self.factor_names) == 1
            else self._multi_factor(long_only)
        )
        return self.strategy_returns, self.benchmark_returns

    def _benchmark(self) -> pd.Series:
        """等权买入持有的月度收益"""
        first = ((self.data["close"] / self.data["open"] - 1)
                 .groupby(level="asset").first().mean())
        prices = self.data["close"].unstack(level="asset")
        rest = prices.pct_change().iloc[1:].mean(axis=1)
        return pd.concat([pd.Series([first], index=[prices.index[0]]), rest])

    # ── 信号生成 ──

    def _discretize(self) -> None:
        """连续因子 → 按月qcut分层 → -1(做空)/0(中性)/1(做多)"""
        for i, name in enumerate(self.factor_names):
            if self._is_signals(self.data[name]):
                continue

            if isinstance(self.factor_transformers[i], int):
                q = self.factor_transformers[i] or 5
                discretized = (
                    self.data.groupby(level="month")[name]
                    .apply(lambda x: pd.qcut(x, q=q, labels=False, duplicates="drop"))
                    .droplevel(0)
                )
                mx, mn = discretized.max(), discretized.min()
                result = discretized.copy()
                result[discretized == mx] = 1
                result[discretized == mn] = -1
                result[(discretized > mn) & (discretized < mx)] = 0
                self.data[name] = result

            elif callable(self.factor_transformers[i]):
                self.data[name] = self.factor_transformers[i](self.data[name])

    def _merge_flags(self) -> pd.Series:
        """多因子融合: 全部=1→做多, 全部=-1→做空, 其他→中性"""
        factors = self.data[self.factor_names]
        all_long = factors.apply(lambda x: (x == 1).all(), axis=1)
        all_short = factors.apply(lambda x: (x == -1).all(), axis=1)
        flag = pd.Series(0, index=factors.index)
        flag[all_long] = 1
        flag[all_short] = -1
        return flag

    # ── 收益计算 ──

    def _single_factor(self, long_only: bool) -> pd.Series:
        factor = self.data[self.factor_names[0]]
        transformer = self.factor_transformers[0]

        if transformer is None:
            return self._flag_returns(factor, long_only)
        elif isinstance(transformer, int):
            return self._quantile_returns(long_only)
        else:
            return self._flag_returns(transformer(factor), long_only)

    def _multi_factor(self, long_only: bool) -> pd.Series:
        self._discretize()
        return self._flag_returns(self._merge_flags(), long_only)

    def _flag_returns(self, flag: pd.Series, long_only: bool) -> pd.Series:
        """
        基于信号计算月度收益
        - 新开仓: COO收益 (Close/Open-1) — 真实建仓成本
        - 持仓中: MOM收益 (pct_change) — 市场价格变动
        """
        df = self.data.copy()
        df["flag"] = flag.groupby(level="asset").shift(1)
        df["mom_returns"] = df.groupby(level="asset")["close"].pct_change()
        df["coo_returns"] = df["close"] / df["open"] - 1

        # 判断新开仓: flag != 上期flag 且 |flag|==1
        prev = df.groupby("asset")["flag"].shift(1)
        prev = prev.where(prev.abs() == 1, 0)
        df["is_new"] = (df["flag"].abs() == 1) & (df["flag"] != prev)

        months = sorted(df.index.get_level_values("month").unique())
        monthly = []
        divider = 1 if long_only else 2

        for m in months:
            md = df.loc[m]
            long_r = self._position_returns(md, 1)
            short_r = 0 if long_only else self._position_returns(md, -1)
            monthly.append((long_r + short_r) / divider)

        return pd.Series(monthly, index=months)

    def _position_returns(self, month_data: pd.DataFrame, direction: int) -> float:
        """计算单一方向持仓的平均收益"""
        assets = month_data[month_data["flag"] == direction]
        if assets.empty:
            return 0.0

        new = assets[assets["is_new"]]
        old = assets[~assets["is_new"]]

        total = 0.0
        if not new.empty:
            total += new["coo_returns"].sum()
        if not old.empty:
            total += old["mom_returns"].sum()

        n = len(assets)
        return (total / n) * direction if n > 0 else 0.0

    def _quantile_returns(self, long_only: bool) -> pd.Series:
        """连续因子分层收益 (top vs bottom)"""
        name = self.factor_names[0]
        q = self.factor_transformers[0] or 5

        df = self.data.copy()
        df["factor"] = df[name].groupby(level="asset").shift(1)
        df["mom_returns"] = df.groupby(level="asset")["close"].pct_change()

        def _monthly_qr(group):
            qs = pd.qcut(group["factor"], q=q, labels=False, duplicates="drop")
            return group.groupby(qs)["mom_returns"].mean()

        qr_raw = df.groupby(level="month").apply(_monthly_qr)
        # unstack 后可能是 Series (单列) 或 DataFrame (多列)
        qr = qr_raw.unstack()
        if isinstance(qr, pd.Series):
            qr = qr.to_frame(name=0)
        self.quantile_returns = qr

        divider = 1 if long_only else 2
        if long_only:
            strategy = qr.iloc[:, -1] / divider
        else:
            strategy = (qr.iloc[:, -1] - qr.iloc[:, 0]) / divider

        return pd.Series(strategy, index=qr.index).fillna(0)

    # ── 评估 ──

    def evaluate(
        self,
        strategy: pd.Series,
        benchmark: Optional[pd.Series] = None,
    ) -> dict:
        """返回核心绩效指标 (用 factor_utils 替代 quantstats)"""
        from services.factor_utils import (
            calculate_annual_return,
            calculate_sharpe_ratio,
            calculate_max_drawdown,
            safe_divide,
        )
        try:
            ann_ret = calculate_annual_return(strategy, periods_per_year=12)
            sharpe = calculate_sharpe_ratio(strategy, periods_per_year=12)
            values = (1 + strategy).cumprod()
            mdd = calculate_max_drawdown(values)
            calmar = safe_divide(ann_ret, abs(mdd)) if mdd != 0 else 0.0
            win = float((strategy > 0).sum() / len(strategy)) if len(strategy) > 0 else 0.0

            metrics = {
                "annual_return": round(ann_ret, 4),
                "sharpe": round(sharpe, 4),
                "max_drawdown": round(mdd, 4),
                "calmar": round(calmar, 4),
                "win_rate": round(win, 4),
                "months": len(strategy),
                "total_return": round(float((1 + strategy).prod() - 1), 4),
            }

            if benchmark is not None:
                # 对齐 index 类型 (PeriodIndex vs DatetimeIndex)
                s = strategy.copy()
                b = benchmark.copy()
                if isinstance(s.index, pd.PeriodIndex) and not isinstance(b.index, pd.PeriodIndex):
                    b.index = pd.PeriodIndex(b.index, freq="M")
                elif not isinstance(s.index, pd.PeriodIndex) and isinstance(b.index, pd.PeriodIndex):
                    s.index = pd.PeriodIndex(s.index, freq="M")
                aligned = pd.concat([s, b], axis=1).dropna()
                excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
                ir = safe_divide(
                    excess.mean() * 12,
                    excess.std() * (12 ** 0.5)
                ) if excess.std() > 0 else 0.0
                metrics["information_ratio"] = round(ir, 4)

            return metrics
        except Exception:
            logger.warning("evaluate failed", exc_info=True)
            return {"error": "评估失败"}


# ═══════════════════════════════════════════════════════════════
#  QuantLessMoneyMore 增强 — 多权重方案 + 仓位限制
# ═══════════════════════════════════════════════════════════════

from dataclasses import dataclass, field


@dataclass
class StrategyConfig:
    """策略配置 — 源自 QuantLessMoneyMore config_loader + strategy_backtest"""
    # 因子处理
    winsorize: bool = True
    winsorize_std: float = 3.0         # MAD 倍数
    normalize_method: str = "zscore"   # zscore / rank / percentile

    # 股票池过滤
    min_market_cap: float = 0.0        # 最小市值 (0=不过滤)
    min_price: float = 0.0             # 最低股价 (0=不过滤)

    # 仓位
    weight_scheme: str = "equal"       # equal / market_cap / factor_score
    max_stock_weight: float = 0.10     # 单票最大权重 (10%)
    max_turnover: float = 1.0          # 最大换手率 (1.0=无限制)
    transaction_cost: float = 0.003    # 交易成本 (0.3%)

    # 回测
    holding_period: int = 1            # 持仓周期 (月)
    n_groups: int = 5                  # 分层数
    long_only: bool = True

    # 风险控制
    max_industry_weight: float = 0.30  # 单行业最大权重
    risk_free_rate: float = 0.0


def apply_weight_scheme(
    factor_values: pd.Series,
    scheme: str = "equal",
    market_cap: Optional[pd.Series] = None,
) -> pd.Series:
    """
    多权重方案 — 源自 QuantLessMoneyMore generate_signals()

    Args:
        factor_values: 因子值 (只含 top 分组股票)
        scheme: equal / market_cap / factor_score
        market_cap: 市值数据 (scheme=market_cap 时必需)

    Returns:
        归一化的权重 Series
    """
    if scheme == "equal":
        weights = pd.Series(1.0, index=factor_values.index)
    elif scheme == "market_cap" and market_cap is not None:
        weights = market_cap.loc[factor_values.index]
    elif scheme == "factor_score":
        weights = factor_values.abs()  # 按因子强度加权
    else:
        weights = pd.Series(1.0, index=factor_values.index)

    weights = weights / weights.sum()
    return weights


def apply_position_limits(
    weights: pd.Series,
    max_weight: float = 0.10,
    max_turnover: float = 1.0,
    prev_weights: Optional[pd.Series] = None,
) -> pd.Series:
    """
    仓位限制 — 源自 QuantLessMoneyMore

    Args:
        weights: 目标权重
        max_weight: 单票最大权重
        max_turnover: 最大换手率 (1.0=无限制)
        prev_weights: 上期权重 (计算换手率用)

    Returns:
        调整后的权重
    """
    # 1. 单票上限裁剪
    weights = weights.clip(upper=max_weight)

    # 2. 换手率限制
    if prev_weights is not None and max_turnover < 1.0:
        turnover = abs(weights - prev_weights.reindex(weights.index, fill_value=0)).sum()
        if turnover > max_turnover:
            ratio = max_turnover / turnover
            weights = prev_weights.reindex(weights.index, fill_value=0) + (weights - prev_weights.reindex(weights.index, fill_value=0)) * ratio

    # 3. 归一化
    total = weights.sum()
    if total > 0:
        weights = weights / total
    return weights


# ═══════════════════════════════════════════════════════════════
#  API 端点用的快捷函数
# ═══════════════════════════════════════════════════════════════

def run_monthly_backtest(
    daily_bars: pd.DataFrame,
    factor_data: pd.DataFrame,
    factor_col: str,
    quantiles: int = 5,
    long_only: bool = True,
) -> dict:
    """
    一键月度因子回测

    Args:
        daily_bars: [date, asset, open, close]
        factor_data: [date, asset, factor_col]
        factor_col: 因子列名
        quantiles: 分层数
        long_only: 仅做多

    Returns:
        {"metrics": {...}, "strategy_returns": [...], "benchmark_returns": [...]}
    """
    bt = MonthlyBacktest(daily_bars)

    # 单资产 → 用因子符号做信号 (因子>0做多, 因子<0做空/中性)
    n_assets = daily_bars["asset"].nunique()
    if n_assets == 1:
        bt.append_factor(
            factor_data, factor_col,
            transform=lambda x: (x > 0).astype(int) - (x < 0).astype(int),
            resample="last",
        )
    else:
        bt.append_factor(factor_data, factor_col, quantiles=quantiles, resample="last")

    strategy, benchmark = bt.run(long_only=long_only)
    metrics = bt.evaluate(strategy, benchmark)

    return {
        "metrics": metrics,
        "strategy_returns": [
            {"month": str(m), "return": round(v, 6)}
            for m, v in strategy.items()
        ],
        "benchmark_returns": [
            {"month": str(m), "return": round(v, 6)}
            for m, v in benchmark.items()
        ],
        "quantile_returns": (
            [
                {"month": str(m), **{str(c): round(v, 6) for c, v in row.items()}}
                for m, row in bt.quantile_returns.iterrows()
            ]
            if bt.quantile_returns is not None
            else None
        ),
    }
