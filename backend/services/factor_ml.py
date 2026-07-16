"""Phase 3: LightGBM ML 因子生成

思路:
  1. 用 15 个价格/技术因子 + 真实收益, 训练 LightGBM 回归器预测次日收益
  2. 模型预测值 = "组合因子" (非线性组合因子)
  3. 评估这个组合因子的 IC/IR/胜率
  4. 输出特征重要性 (哪些因子贡献最大)

为什么 LightGBM:
  - 非线性: 树模型自动发现因子之间的交互
  - 鲁棒: 对异常值/缺失值不敏感
  - 可解释: feature_importances_ 直接展示哪些因子最有效
  - 速度快: 5 万样本 ~ 10 秒
"""
import logging
import time
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import lightgbm as lgb

from database import query_all, execute

logger = logging.getLogger(__name__)

# 模型保存目录
MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════
#  因子特征 (复用 factor_expr 的算子)
# ═══════════════════════════════════════════════════════════

def _compute_features(df: pd.DataFrame) -> dict[str, pd.Series]:
    """对单只股票计算所有 ML 特征 (15 个)

    与 factor_lab.py 的 FACTOR_REGISTRY 一致
    """
    closes = df["close"].copy()
    volumes = df["volume"].copy() if "volume" in df.columns else pd.Series(0.0, index=df.index)

    features = {
        # 动量
        "ret_5d": closes.pct_change(5),
        "ret_10d": closes.pct_change(10),
        "ret_20d": closes.pct_change(20),
        # 均线
        "ma5": closes.rolling(5).mean() / closes - 1,
        "ma10": closes.rolling(10).mean() / closes - 1,
        "ma20": closes.rolling(20).mean() / closes - 1,
        # RSI
        "rsi_14": _rsi(closes, 14),
        # 波动
        "volatility": closes.pct_change().rolling(20).std(),
        # MACD
        "macd_signal": _macd_signal(closes),
        # 量能
        "vol_ratio": volumes.rolling(5).mean() / volumes.rolling(25).mean(),
        # 振幅
        "amplitude": (closes.rolling(20).max() - closes.rolling(20).min()) / closes,
        # 价格位置 (布林带)
        "price_pos": _price_position(closes, 20),
        # MA 多头排列
        "ma_disp": (closes.rolling(5).mean() > closes.rolling(20).mean()).astype(float),
        # 收益率反转
        "neg_ret_1d": -closes.pct_change(1),
        "neg_ret_5d": -closes.pct_change(5),
    }
    return features


def _rsi(closes, period):
    diff = closes.diff()
    gains = diff.clip(lower=0).rolling(period).mean()
    losses = (-diff.clip(upper=0)).rolling(period).mean()
    rs = gains / losses.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def _macd_signal(closes):
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    return (dif - dea) / closes


def _price_position(closes, n):
    ma = closes.rolling(n).mean()
    std = closes.rolling(n).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    return (closes - lower) / (upper - lower).replace(0, 1e-9)


# ═══════════════════════════════════════════════════════════
#  数据准备
# ═══════════════════════════════════════════════════════════

def _build_panel(panels: dict[str, pd.DataFrame], feature_names: list[str]) -> pd.DataFrame:
    """把所有股票的所有特征展开成 long DataFrame

    Returns:
        DataFrame with columns: [trade_date, stock_code, ret_5d, ret_10d, ..., fwd_ret_1d]
        每行 = 一天一只股票
    """
    rows = []
    for code, df in panels.items():
        feats = _compute_features(df)
        feat_df = pd.DataFrame(feats, index=df.index)
        feat_df["stock_code"] = code
        # 加 1 日 forward return (预测目标)
        feat_df["fwd_ret_1d"] = df["close"].pct_change().shift(-1)
        rows.append(feat_df)

    if not rows:
        return pd.DataFrame()

    big = pd.concat(rows)
    big = big.reset_index().rename(columns={"index": "trade_date"})
    big = big.dropna(subset=["fwd_ret_1d"] + feature_names, how="any")
    return big


# ═══════════════════════════════════════════════════════════
#  LightGBM 训练
# ═══════════════════════════════════════════════════════════

FEATURE_NAMES = [
    "ret_5d", "ret_10d", "ret_20d",
    "ma5", "ma10", "ma20",
    "rsi_14",
    "volatility", "macd_signal", "vol_ratio",
    "amplitude", "price_pos", "ma_disp",
    "neg_ret_1d", "neg_ret_5d",
]


def train_ml_factor(stock_pool: str = "csi800",
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None,
                    n_estimators: int = 100,
                    max_depth: int = 4,
                    learning_rate: float = 0.05,
                    train_ratio: float = 0.7) -> dict:
    """训练 LightGBM 模型, 返回组合因子的 IC 指标

    Args:
        n_estimators: 树的数量 (越多越准但越慢)
        max_depth: 单树最大深度 (越小越不容易过拟合)
        train_ratio: 训练集比例, 余下做验证集

    Returns:
        {
            'run_id': str,
            'feature_importance': [{name, importance}, ...],
            'train_metrics': {ic_mean, ir, win_rate, ...},
            'test_metrics': {ic_mean, ir, win_rate, ...},
            'top_decile_return': float,  # top 10% 平均收益
            'bottom_decile_return': float,  # bottom 10% 平均收益
            'spread': float,  # top - bottom (越高越好)
            'sample_count': N,
            'train_days': M,
            'test_days': K,
            'model_path': str,  # .pkl 文件路径
        }
    """
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=270)).strftime("%Y-%m-%d")

    run_id = f"ml-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # 加载股票池
    from services.factor_lab import get_stock_pool, load_kline_panel
    stock_codes = get_stock_pool(stock_pool)
    panels = load_kline_panel(stock_codes, start_date, end_date)
    if not panels:
        return {"error": "股票池为空"}

    logger.info("ML train start: %d stocks, %s ~ %s", len(panels), start_date, end_date)

    # 构建特征面板
    big = _build_panel(panels, FEATURE_NAMES)
    if len(big) < 1000:
        return {"error": f"样本太少: {len(big)}"}

    logger.info("ML feature panel: %d rows", len(big))

    # 按时序分训练/验证集 (前 train_ratio 做训练, 后做测试)
    all_dates = sorted(big["trade_date"].unique())
    split_idx = int(len(all_dates) * train_ratio)
    train_dates = all_dates[:split_idx]
    test_dates = all_dates[split_idx:]

    train_df = big[big["trade_date"].isin(train_dates)]
    test_df = big[big["trade_date"].isin(test_dates)]

    X_train = train_df[FEATURE_NAMES]
    y_train = train_df["fwd_ret_1d"]
    X_test = test_df[FEATURE_NAMES]
    y_test = test_df["fwd_ret_1d"]

    logger.info("ML split: train=%d, test=%d", len(X_train), len(X_test))

    # 训练 LightGBM
    model = lgb.LGBMRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        num_leaves=min(2 ** max_depth, 31),
        min_child_samples=100,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    t0 = time.time()
    model.fit(X_train, y_train)
    train_time = time.time() - t0

    # 预测 (在测试集上)
    pred_test = model.predict(X_test)

    # 特征重要性
    importance_pairs = sorted(
        zip(FEATURE_NAMES, model.feature_importances_),
        key=lambda x: -x[1]
    )
    feature_importance = [
        {"name": name, "importance": float(imp)}
        for name, imp in importance_pairs
    ]

    # 评估组合因子的 IC (在测试集上)
    # pred_test 是每只股票每天的预测值, 它的 IC vs fwd_ret_1d
    test_eval = test_df[["trade_date", "stock_code", "fwd_ret_1d"]].copy()
    test_eval["pred"] = pred_test

    ic_per_day = test_eval.groupby("trade_date").apply(
        lambda g: g["pred"].corr(g["fwd_ret_1d"]) if g["pred"].std() > 0 and g["fwd_ret_1d"].std() > 0 else np.nan
    ).dropna()

    test_metrics = {
        "ic_mean": float(ic_per_day.mean()),
        "ic_std": float(ic_per_day.std()),
        "ir": float(ic_per_day.mean() / ic_per_day.std()) if ic_per_day.std() > 0 else 0.0,
        "win_rate": float((ic_per_day > 0).sum() / len(ic_per_day)) if len(ic_per_day) > 0 else 0.0,
        "valid_days": int(len(ic_per_day)),
    }

    # 训练集 IC (用于对比)
    pred_train = model.predict(X_train)
    train_eval = train_df[["trade_date", "stock_code", "fwd_ret_1d"]].copy()
    train_eval["pred"] = pred_train
    ic_train = train_eval.groupby("trade_date").apply(
        lambda g: g["pred"].corr(g["fwd_ret_1d"]) if g["pred"].std() > 0 and g["fwd_ret_1d"].std() > 0 else np.nan
    ).dropna()
    train_metrics = {
        "ic_mean": float(ic_train.mean()),
        "ic_std": float(ic_train.std()),
        "ir": float(ic_train.mean() / ic_train.std()) if ic_train.std() > 0 else 0.0,
        "win_rate": float((ic_train > 0).sum() / len(ic_train)) if len(ic_train) > 0 else 0.0,
        "valid_days": int(len(ic_train)),
    }

    # 多空对冲: top 10% vs bottom 10%
    test_eval["decile"] = test_eval.groupby("trade_date")["pred"].rank(pct=True)
    top_10 = test_eval[test_eval["decile"] >= 0.9]
    bot_10 = test_eval[test_eval["decile"] <= 0.1]
    top_ret = float(top_10["fwd_ret_1d"].mean()) if len(top_10) > 0 else 0.0
    bot_ret = float(bot_10["fwd_ret_1d"].mean()) if len(bot_10) > 0 else 0.0

    # 保存模型
    model_path = MODEL_DIR / f"{run_id}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": model,
            "feature_names": FEATURE_NAMES,
            "run_id": run_id,
            "stock_pool": stock_pool,
            "start_date": start_date,
            "end_date": end_date,
        }, f)

    # 保存候选到 factor_candidates (作为 "ml_model" 类型)
    summary = (
        f"LightGBM({n_estimators}trees, depth={max_depth}, lr={learning_rate}) | "
        f"test IR={test_metrics['ir']:.3f} | "
        f"top10={top_ret*100:+.2f}% bot10={bot_ret*100:+.2f}%"
    )
    try:
        execute(
            "INSERT INTO factor_candidates "
            "(run_id, expr_text, ic_mean, ir, win_rate, valid_days, tree_depth, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, summary,
             test_metrics["ic_mean"], test_metrics["ir"], test_metrics["win_rate"],
             test_metrics["valid_days"], max_depth,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
    except Exception as e:
        logger.warning("save ml candidate failed: %s", str(e)[:200])

    return {
        "run_id": run_id,
        "feature_importance": feature_importance,
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "top_decile_return": top_ret,
        "bottom_decile_return": bot_ret,
        "spread": top_ret - bot_ret,
        "sample_count": len(big),
        "train_count": len(X_train),
        "test_count": len(X_test),
        "train_days": len(train_dates),
        "test_days": len(test_dates),
        "model_path": str(model_path),
        "n_estimators": n_estimators,
        "max_depth": max_depth,
        "learning_rate": learning_rate,
        "summary": summary,
        "train_time_s": round(train_time, 2),
    }