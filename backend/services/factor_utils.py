"""
因子工具函数 — 源自 qlib_factor_platform/helpers.py

提供去极值、标准化、中性化、绩效指标、数据验证等纯函数。
所有函数兼容 pandas Series/DataFrame 和 Python list。
"""

import logging
import math
from typing import Dict, List, Any, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger("stockai")


# ═══════════════════════════════════════════════════════════════
#  基础运算
# ═══════════════════════════════════════════════════════════════

def safe_divide(
    numerator: float,
    denominator: float,
    default: float = 0.0,
    epsilon: float = 1e-12
) -> float:
    """安全除法，分母接近零返回 default"""
    try:
        if abs(denominator) < epsilon:
            return default
        return numerator / denominator
    except Exception:
        logger.warning("safe_divide failed", exc_info=True)
        return default


def calculate_returns(
    prices: Union[pd.Series, List[float]],
    method: str = "simple",
    period: int = 1
) -> pd.Series:
    """
    计算收益率序列

    Args:
        prices: 价格序列
        method: "simple" (涨跌幅) / "log" (对数收益率)
        period: 周期 (1=日收益率, 5=周收益率)
    """
    try:
        if not isinstance(prices, pd.Series):
            prices = pd.Series(prices)
        if method == "simple":
            return prices.pct_change(period)
        elif method == "log":
            return np.log(prices / prices.shift(period))
        else:
            raise ValueError(f"不支持的方法: {method}")
    except Exception:
        logger.warning("calculate_returns failed", exc_info=True)
        return pd.Series()


# ═══════════════════════════════════════════════════════════════
#  去极值 & 标准化 & 中性化
# ═══════════════════════════════════════════════════════════════

def winsorize_series(
    data: Union[pd.Series, List[float]],
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99
) -> pd.Series:
    """
    缩尾处理 (MAD法替代: 百分位截断)

    将低于 lower_quantile 分位数的值拉回到该分位数，
    将高于 upper_quantile 分位数的值拉回到该分位数。
    """
    try:
        if not isinstance(data, pd.Series):
            data = pd.Series(data)
        lower = data.quantile(lower_quantile)
        upper = data.quantile(upper_quantile)
        return data.clip(lower, upper)
    except Exception:
        logger.warning("winsorize_series failed", exc_info=True)
        return data if isinstance(data, pd.Series) else pd.Series(data)


def standardize_series(
    data: Union[pd.Series, List[float]]
) -> pd.Series:
    """
    Z-Score 标准化: (x - mean) / std

    返回值均值为 0，标准差为 1。
    """
    try:
        if not isinstance(data, pd.Series):
            data = pd.Series(data)
        mean_val = data.mean()
        std_val = data.std()
        if std_val == 0:
            return data - mean_val
        return (data - mean_val) / std_val
    except Exception:
        logger.warning("standardize_series failed", exc_info=True)
        return data if isinstance(data, pd.Series) else pd.Series(data)


def neutralize_factor(
    factor_data: pd.DataFrame,
    industry_data: Optional[pd.DataFrame] = None,
    market_cap_data: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    因子截面中性化

    当前实现: 减去横截面均值 (市场中性)。
    扩展: 可用 industry/market_cap 做回归取残差。
    """
    try:
        neutralized = factor_data.copy()
        for col in factor_data.columns:
            neutralized[col] = factor_data[col] - factor_data[col].mean()
        return neutralized
    except Exception:
        logger.warning("neutralize_factor failed", exc_info=True)
        return factor_data


# ═══════════════════════════════════════════════════════════════
#  绩效指标
# ═══════════════════════════════════════════════════════════════

def calculate_max_drawdown(values: Union[pd.Series, List[float]]) -> float:
    """
    最大回撤 (向量化实现)

    MDD = min((value - peak) / peak)
    """
    try:
        if not isinstance(values, pd.Series):
            values = pd.Series(values)
        if len(values) == 0:
            return 0.0
        peak = values.expanding().max()
        drawdown = (values - peak) / peak
        result = drawdown.min()
        return float(result) if not pd.isna(result) else 0.0
    except Exception:
        logger.warning("calculate_max_drawdown failed", exc_info=True)
        return 0.0


def calculate_sharpe_ratio(
    returns: Union[pd.Series, List[float]],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252
) -> float:
    """
    年化夏普比率

    Sharpe = (mean_return - rf) / std_return * sqrt(periods_per_year)
    """
    try:
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        excess = returns - risk_free_rate / periods_per_year
        std_val = excess.std()
        if std_val == 0 or pd.isna(std_val):
            return 0.0
        result = excess.mean() / std_val * math.sqrt(periods_per_year)
        return float(result) if not pd.isna(result) else 0.0
    except Exception:
        logger.warning("calculate_sharpe_ratio failed", exc_info=True)
        return 0.0


def calculate_information_ratio(
    excess_returns: Union[pd.Series, List[float]],
    periods_per_year: int = 252
) -> float:
    """
    年化信息比率

    IR = mean(excess) / std(excess) * sqrt(periods_per_year)
    """
    try:
        if not isinstance(excess_returns, pd.Series):
            excess_returns = pd.Series(excess_returns)
        std_val = excess_returns.std()
        if std_val == 0 or pd.isna(std_val):
            return 0.0
        result = excess_returns.mean() / std_val * math.sqrt(periods_per_year)
        return float(result) if not pd.isna(result) else 0.0
    except Exception:
        logger.warning("calculate_information_ratio failed", exc_info=True)
        return 0.0


def calculate_calmar_ratio(
    returns: Union[pd.Series, List[float]],
    periods_per_year: int = 252
) -> float:
    """
    卡玛比率 = 年化收益 / |最大回撤|
    """
    try:
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        if len(returns) == 0:
            return 0.0
        cumulative = (1 + returns).cumprod()
        annual_return = (cumulative.iloc[-1]) ** (periods_per_year / len(returns)) - 1
        mdd = calculate_max_drawdown(cumulative)
        if mdd == 0:
            return 0.0
        return float(annual_return / abs(mdd))
    except Exception:
        logger.warning("calculate_calmar_ratio failed", exc_info=True)
        return 0.0


def calculate_turnover(
    current_positions: Union[pd.Series, Dict[str, float]],
    previous_positions: Union[pd.Series, Dict[str, float]],
    method: str = "count"
) -> float:
    """
    换手率

    Args:
        method: "count" (基于持仓数量) / "value" (基于持仓权重)
    """
    try:
        if isinstance(current_positions, dict):
            current_positions = pd.Series(current_positions)
        if isinstance(previous_positions, dict):
            previous_positions = pd.Series(previous_positions)

        if method == "count":
            cur_set = set(current_positions.index)
            prev_set = set(previous_positions.index)
            if len(prev_set) == 0:
                return 0.0
            changed = len(cur_set.symmetric_difference(prev_set))
            return changed / len(prev_set)

        elif method == "value":
            cur_w = current_positions / current_positions.sum()
            prev_w = previous_positions / previous_positions.sum()
            common = cur_w.index.intersection(prev_w.index)
            if len(common) == 0:
                return 0.0
            weight_changes = abs(cur_w[common] - prev_w[common])
            return float(weight_changes.sum() / 2)

        else:
            raise ValueError(f"不支持的方法: {method}")
    except Exception:
        logger.warning("calculate_turnover failed", exc_info=True)
        return 0.0


def calculate_annual_return(
    returns: Union[pd.Series, List[float]],
    periods_per_year: int = 252
) -> float:
    """年化收益率"""
    try:
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        if len(returns) == 0:
            return 0.0
        cumulative = (1 + returns).prod()
        result = cumulative ** (periods_per_year / len(returns)) - 1
        return float(result) if not pd.isna(result) else 0.0
    except Exception:
        logger.warning("calculate_annual_return failed", exc_info=True)
        return 0.0


def calculate_volatility(
    returns: Union[pd.Series, List[float]],
    periods_per_year: int = 252
) -> float:
    """年化波动率"""
    try:
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        std_val = returns.std()
        if pd.isna(std_val):
            return 0.0
        return float(std_val * math.sqrt(periods_per_year))
    except Exception:
        logger.warning("calculate_volatility failed", exc_info=True)
        return 0.0


def calculate_sortino_ratio(
    returns: Union[pd.Series, List[float]],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252
) -> float:
    """
    索提诺比率 — 只惩罚下行波动

    Sortino = (mean_return - rf) / std(negative_returns) * sqrt(N)
    """
    try:
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        excess = returns - risk_free_rate / periods_per_year
        downside = excess[excess < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        result = excess.mean() / downside.std() * math.sqrt(periods_per_year)
        return float(result) if not pd.isna(result) else 0.0
    except Exception:
        logger.warning("calculate_sortino_ratio failed", exc_info=True)
        return 0.0


def calculate_win_rate(returns: Union[pd.Series, List[float]]) -> float:
    """胜率 = 正收益天数 / 总天数"""
    try:
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        if len(returns) == 0:
            return 0.0
        return float((returns > 0).sum() / len(returns))
    except Exception:
        logger.warning("calculate_win_rate failed", exc_info=True)
        return 0.0


# ═══════════════════════════════════════════════════════════════
#  因子分析
# ═══════════════════════════════════════════════════════════════

def calculate_ic(
    factor_values: Union[pd.Series, List[float]],
    forward_returns: Union[pd.Series, List[float]],
    method: str = "spearman"
) -> float:
    """
    因子 IC (Information Coefficient)

    Args:
        method: "spearman" (秩相关) / "pearson" (线性相关)
    """
    try:
        if not isinstance(factor_values, pd.Series):
            factor_values = pd.Series(factor_values)
        if not isinstance(forward_returns, pd.Series):
            forward_returns = pd.Series(forward_returns)

        # 对齐索引，删除 NaN
        mask = factor_values.notna() & forward_returns.notna()
        fv = factor_values[mask]
        fr = forward_returns[mask]

        if len(fv) < 10:
            return 0.0

        if method == "spearman":
            result = fv.corr(fr, method="spearman")
        elif method == "pearson":
            result = fv.corr(fr, method="pearson")
        else:
            raise ValueError(f"不支持的方法: {method}")

        return float(result) if not pd.isna(result) else 0.0
    except Exception:
        logger.warning("calculate_ic failed", exc_info=True)
        return 0.0


# ═══════════════════════════════════════════════════════════════
#  数据质量验证
# ═══════════════════════════════════════════════════════════════

def validate_factor_data(
    factor_data: pd.DataFrame,
    min_stocks: int = 10,
    min_periods: int = 20
) -> Dict[str, Any]:
    """
    因子数据质量检查

    Returns: {"is_valid": bool, "errors": [...], "warnings": [...]}
    """
    try:
        result = {"is_valid": True, "errors": [], "warnings": []}

        if factor_data.empty:
            result["is_valid"] = False
            result["errors"].append("因子数据为空")
            return result

        n_stocks = len(factor_data.columns)
        n_periods = len(factor_data)

        if n_stocks < min_stocks:
            result["is_valid"] = False
            result["errors"].append(f"股票数量不足: {n_stocks} < {min_stocks}")

        if n_periods < min_periods:
            result["is_valid"] = False
            result["errors"].append(f"时间周期不足: {n_periods} < {min_periods}")

        missing_ratio = factor_data.isnull().sum().sum() / (n_stocks * n_periods)
        if missing_ratio > 0.5:
            result["warnings"].append(f"缺失值比例较高: {missing_ratio:.2%}")

        inf_count = np.isinf(factor_data.values).sum()
        if inf_count > 0:
            result["errors"].append(f"存在无穷值: {inf_count}")
            result["is_valid"] = False

        return result
    except Exception:
        logger.warning("validate_factor_data failed", exc_info=True)
        return {"is_valid": False, "errors": [str(Exception)], "warnings": []}


def validate_missing_rate(
    data: pd.DataFrame,
    max_missing_rate: float = 0.3
) -> Dict[str, Any]:
    """缺失率检查"""
    try:
        rate = data.isnull().sum().sum() / (len(data) * len(data.columns))
        return {
            "passed": rate <= max_missing_rate,
            "missing_rate": round(rate, 4),
            "threshold": max_missing_rate,
        }
    except Exception:
        logger.warning("validate_missing_rate failed", exc_info=True)
        return {"passed": False, "missing_rate": 1.0, "threshold": max_missing_rate}


def validate_outliers(
    data: pd.DataFrame,
    n_std: float = 5.0
) -> Dict[str, Any]:
    """
    异常值检测 (N倍标准差法)

    Returns: {"passed": bool, "outlier_count": int, "outlier_pct": float}
    """
    try:
        mean = data.mean().mean()
        std = data.std().mean()
        if std == 0:
            return {"passed": True, "outlier_count": 0, "outlier_pct": 0.0}
        upper = mean + n_std * std
        lower = mean - n_std * std
        outlier_mask = (data > upper) | (data < lower)
        count = int(outlier_mask.sum().sum())
        total = len(data) * len(data.columns)
        pct = count / total if total > 0 else 0.0
        return {
            "passed": pct < 0.05,
            "outlier_count": count,
            "outlier_pct": round(pct, 4),
        }
    except Exception:
        logger.warning("validate_outliers failed", exc_info=True)
        return {"passed": False, "outlier_count": -1, "outlier_pct": 1.0}
