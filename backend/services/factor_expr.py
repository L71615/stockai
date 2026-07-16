"""GP 因子挖掘 — 表达式求值引擎

支持表达式:
  叶子: close, open, high, low, volume, returns
  数学: +, -, *, /, abs, log, sign, sqrt, neg
  滚动: mean(n), std(n), delta(n), delay(n), ts_rank(n), ema(n)
  横截面: cs_rank() — 在某天所有股票中的排名 (0~1)

示例:
  "cs_rank(delta(close, 5))"
  "cs_rank(delta(close, 5) / std(returns(close), 20))"
  "mean(delta(close, 1), 5) / std(delta(close, 1), 20)"
"""
import logging
import random
import ast
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#  表达式求值
# ═══════════════════════════════════════════════════════════


class FactorEvalError(Exception):
    pass


# 滚动算子
def _mean(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def _std(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=2).std()


def _sum(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).sum()


def _max(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).max()


def _min(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).min()


def _delta(s: pd.Series, n: int) -> pd.Series:
    return s.diff(n)


def _delay(s: pd.Series, n: int) -> pd.Series:
    return s.shift(n)


def _ts_rank(s: pd.Series, n: int) -> pd.Series:
    """时间序列排名: 当前值在过去 n 日中的分位数"""
    return s.rolling(n, min_periods=1).apply(lambda x: pd.Series(x).rank().iloc[-1] / len(x), raw=False)


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


# 数学算子
def _abs(s): return np.abs(s)
def _sign(s): return np.sign(s)
def _log(s): return np.log(np.abs(s) + 1e-9)
def _sqrt(s): return np.sqrt(np.abs(s))
def _neg(s): return -s
def _safe_div(a, b):
    return a / np.where(np.abs(b) < 1e-9, 1e-9, b)


# 横截面算子
def cs_rank(panels: dict[str, pd.Series], date) -> dict[str, float]:
    """在某天所有股票的横截面排名 (返回 0~1)

    panels: {code: Series(factor_value indexed by date)}
    date: pd.Timestamp
    Returns: {code: rank_0_to_1}
    """
    vals = {}
    for code, s in panels.items():
        if date in s.index and not pd.isna(s.loc[date]):
            vals[code] = float(s.loc[date])
    if not vals:
        return {}
    series = pd.Series(vals)
    return series.rank(pct=True).to_dict()


def safe_eval_expr(expr_text: str, df: pd.DataFrame, panels: dict[str, pd.Series] = None, date=None) -> pd.Series | dict[str, float]:
    """安全求值因子表达式

    Args:
        expr_text: 表达式字符串
        df: 单只股票的 OHLCV DataFrame
        panels: (横截面 cs_rank 用) {code: factor_value_series}
        date: (横截面) 当前评估日期

    Returns:
        Series (时间序列模式) 或 dict (横截面模式)
    """
    # 准备 namespace
    if panels is not None and date is not None:
        # 横截面模式: 表达式结果在每个 code 上算 Series, 然后 cs_rank
        # 先在每只股票上算表达式, 然后取 date 那天的值, 做横截面 rank
        per_code_series = {}
        for code, df_c in panels.items():
            try:
                per_code_series[code] = _eval_single(expr_text, df_c)
            except Exception:
                continue
        if not per_code_series:
            return {}
        return cs_rank(per_code_series, date)

    # 时间序列模式
    return _eval_single(expr_text, df)


def _eval_single(expr_text: str, df: pd.DataFrame) -> pd.Series:
    """对单只股票求值时间序列"""
    if df.empty:
        return pd.Series(dtype=float)

    # 准备数据
    closes = df["close"].copy()
    opens = df["open"].copy() if "open" in df.columns else closes
    highs = df["high"].copy() if "high" in df.columns else closes
    lows = df["low"].copy() if "low" in df.columns else closes
    volumes = df["volume"].copy() if "volume" in df.columns else pd.Series(0, index=df.index)
    returns = closes.pct_change()

    namespace = {
        # 数据
        "close": closes, "open": opens, "high": highs, "low": lows,
        "volume": volumes, "returns": returns,
        # 数学
        "abs": _abs, "sign": _sign, "log": _log, "sqrt": _sqrt, "neg": _neg,
        "max": np.maximum, "min": np.minimum,
        # 滚动
        "mean": _mean, "std": _std, "sum": _sum,
        "rmax": _max, "rmin": _min,
        "delta": _delta, "delay": _delay,
        "ts_rank": _ts_rank, "ema": _ema,
        # 辅助
        "nan": np.nan,
    }

    try:
        tree = ast.parse(expr_text, mode="eval")
        result = _eval_node(tree.body, namespace, df)
    except Exception as e:
        raise FactorEvalError(f"表达式求值失败: {str(e)[:100]}")

    if isinstance(result, pd.Series):
        return result.reindex(df.index)
    if isinstance(result, (int, float, np.number)):
        return pd.Series(result, index=df.index)
    raise FactorEvalError(f"表达式返回类型错误: {type(result)}")


def _eval_node(node, namespace: dict, df: pd.DataFrame):
    """递归求值 AST 节点"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in namespace:
            raise FactorEvalError(f"未知符号: {node.id}")
        val = namespace[node.id]
        if callable(val):
            return val
        return val

    if isinstance(node, ast.Call):
        # 函数调用: func(args)
        if not isinstance(node.func, ast.Name):
            raise FactorEvalError("只支持函数名调用")
        fn_name = node.func.id
        if fn_name not in namespace:
            raise FactorEvalError(f"未知函数: {fn_name}")
        fn = namespace[fn_name]
        if not callable(fn):
            raise FactorEvalError(f"{fn_name} 不可调用")
        args = [_eval_node(a, namespace, df) for a in node.args]
        return fn(*args)

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, namespace, df)
        right = _eval_node(node.right, namespace, df)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Div): return _safe_div(left, right)
        if isinstance(node.op, ast.Pow): return np.power(left, right)
        raise FactorEvalError(f"不支持的二元运算: {type(node.op).__name__}")

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, namespace, df)
        if isinstance(node.op, ast.USub): return -operand
        if isinstance(node.op, ast.UAdd): return operand
        raise FactorEvalError(f"不支持的一元运算")

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, namespace, df)
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval_node(right_node, namespace, df)
            if isinstance(op, ast.Gt): result = left > right
            elif isinstance(op, ast.Lt): result = left < right
            elif isinstance(op, ast.GtE): result = left >= right
            elif isinstance(op, ast.LtE): result = left <= right
            else: raise FactorEvalError("不支持的比较")
            left = result
        return left.astype(float)

    raise FactorEvalError(f"不支持的 AST 节点: {type(node).__name__}")


# ═══════════════════════════════════════════════════════════
#  GP: 随机生成 + 变异 + 交叉
# ═══════════════════════════════════════════════════════════


LEAVES = ["close", "open", "high", "low", "volume", "returns"]
MATH_OPS = ["abs", "sign", "log", "sqrt", "neg"]
ROLL_OPS = [("mean", [3, 5, 10, 20, 60]),
            ("std", [3, 5, 10, 20, 60]),
            ("delta", [1, 3, 5, 10, 20]),
            ("delay", [1, 2, 3, 5, 10]),
            ("ts_rank", [5, 10, 20]),
            ("ema", [5, 10, 20])]
BINARY_OPS = ["+", "-", "*"]


def random_expr(depth: int = 0, max_depth: int = 4) -> str:
    """随机生成因子表达式 (语法树字符串)

    注: 暂不支持 cs_rank (横截面排名), 需 cross_section 模式
    """
    if depth >= max_depth or random.random() < 0.4:
        # 叶子: 简单表达式
        choice = random.random()
        if choice < 0.5:
            return random.choice(LEAVES)
        elif choice < 0.8:
            op, params = random.choice(ROLL_OPS)
            n = random.choice(params)
            return f"{op}({random.choice(LEAVES)}, {n})"
        else:
            return f"{random.choice(MATH_OPS)}({random.choice(LEAVES)})"

    # 内部节点
    op_type = random.random()
    if op_type < 0.5:
        # 二元运算
        op = random.choice(BINARY_OPS)
        left = random_expr(depth + 1, max_depth)
        right = random_expr(depth + 1, max_depth)
        return f"({left} {op} {right})"
    elif op_type < 0.85:
        # 滚动算子
        op, params = random.choice(ROLL_OPS)
        n = random.choice(params)
        inner = random.choice(LEAVES)
        return f"{op}({inner}, {n})"
    else:
        # 数学算子
        op = random.choice(MATH_OPS)
        inner = random.choice(LEAVES)
        return f"{op}({inner})"


def mutate(expr: str) -> str:
    """变异: 替换某一部分"""
    # 简单策略: 50% 替换叶子, 30% 替换滚动算子的 n, 20% 替换算子
    r = random.random()
    if r < 0.5:
        # 替换一个叶子
        for leaf in LEAVES:
            if leaf in expr:
                new_leaf = random.choice([l for l in LEAVES if l != leaf])
                return expr.replace(leaf, new_leaf, 1)
    elif r < 0.8:
        # 替换一个数字
        import re
        nums = re.findall(r'\b(\d+)\b', expr)
        if nums:
            old = random.choice(nums)
            new = random.choice([3, 5, 10, 20, 60])
            return expr.replace(old, str(new), 1)
    # 替换 cs_rank
    if "cs_rank" in expr and random.random() < 0.3:
        return f"cs_rank({random_expr(2, 4)})"
    return random_expr(2, 4)


def crossover(expr_a: str, expr_b: str) -> tuple[str, str]:
    """交叉: 随机交换子串 (简化版)"""
    # 50% 交换一半内容
    if random.random() < 0.5:
        mid_a = len(expr_a) // 2
        mid_b = len(expr_b) // 2
        new_a = expr_a[:mid_a] + expr_b[mid_b:]
        new_b = expr_b[:mid_b] + expr_a[mid_a:]
        return new_a, new_b
    return mutate(expr_a), mutate(expr_b)


# ═══════════════════════════════════════════════════════════
#  GP 评估函数
# ═══════════════════════════════════════════════════════════

def evaluate_expr_on_pool(expr_text: str, panels: dict[str, pd.DataFrame],
                          start_date: str, end_date: str) -> dict:
    """在一组股票上评估表达式, 返回 IC 指标

    Returns:
        {
            'ic_mean': float,
            'ir': float,
            'win_rate': float,
            'valid_days': int,
            'tree_depth': int,
        } 或 None (如果评估失败)
    """
    try:
        # 计算所有股票的因子值 (每只股票一个 Series)
        factor_panels = {}  # code -> Series indexed by date
        for code, df in panels.items():
            if df.empty:
                continue
            try:
                values = _eval_single(expr_text, df)
                factor_panels[code] = values
            except Exception:
                continue

        if len(factor_panels) < 30:
            return None

        # 算 return panel (每日 pct_change)
        return_panel = pd.DataFrame({
            code: df["close"].pct_change() for code, df in panels.items()
        })

        # 算每日 IC = Pearson(factor_panel_t, return_panel_{t+1})
        # factor_panel: wide DataFrame (index=date, columns=code)
        factor_wide = pd.DataFrame(factor_panels)
        forward_returns = return_panel.shift(-1)

        # 取 80% 完整度的日期
        threshold = max(int(factor_wide.shape[1] * 0.8), 30)
        complete_days = factor_wide.notna().sum(axis=1)
        valid_days_idx = complete_days[complete_days >= threshold].index

        if len(valid_days_idx) < 30:
            return None

        ic_values = []
        for date in valid_days_idx:
            f = factor_wide.loc[date].dropna()
            r = forward_returns.loc[date].dropna() if date in forward_returns.index else pd.Series()
            common = f.index.intersection(r.index)
            if len(common) < 30:
                continue
            fv = f[common].values.astype(float)
            rv = r[common].values.astype(float)
            if np.std(fv) < 1e-9 or np.std(rv) < 1e-9:
                continue
            try:
                c = np.corrcoef(fv, rv)[0, 1]
                if not np.isnan(c):
                    ic_values.append(c)
            except Exception:
                continue

        if len(ic_values) < 30:
            return None

        ic_series = np.array(ic_values)
        ic_mean = float(np.mean(ic_series))
        ic_std = float(np.std(ic_series))
        ir = ic_mean / ic_std if ic_std > 1e-9 else 0.0
        win_rate = float((ic_series > 0).sum() / len(ic_series))

        # 估算深度 (括号层数)
        tree_depth = expr_text.count("(")

        return {
            "ic_mean": ic_mean,
            "ir": ir,
            "win_rate": win_rate,
            "valid_days": int(len(ic_values)),
            "tree_depth": tree_depth,
        }
    except Exception as e:
        logger.debug("evaluate_expr_on_pool failed: %s", str(e)[:120])
        return None


# ═══════════════════════════════════════════════════════════
#  GP 主循环
# ═══════════════════════════════════════════════════════════

def gp_mine(stock_pool: str = "csi800",
            start_date: str = "2025-10-01",
            end_date: str = "2026-07-13",
            population: int = 50,
            generations: int = 5,
            top_k: int = 20,
            seed: int = 42) -> dict:
    """GP 主循环: 随机 + 评估 + 选择 + 变异 + 交叉

    Returns:
        {
            'run_id': str,
            'best': [评估结果, ...],
            'stats': {candidates_evaluated, kept, ...},
            'history': [每代最佳 IR, ...],
        }
    """
    import time as _time
    import uuid

    random.seed(seed)
    run_id = f"gp-{uuid.uuid4().hex[:8]}"

    logger.info("GP mine start: run=%s pool=%s pop=%d gen=%d", run_id, stock_pool, population, generations)

    # 加载股票池
    from services.factor_lab import get_stock_pool, load_kline_panel
    stock_codes = get_stock_pool(stock_pool)
    panels = load_kline_panel(stock_codes, start_date, end_date)
    if not panels:
        return {"error": "股票池为空", "run_id": run_id}

    # 初始化种群
    population_set = set()
    while len(population_set) < population:
        population_set.add(random_expr(0, 4))
    population_list = list(population_set)

    history = []
    evaluated_count = 0
    best_overall = []

    start_time = _time.time()

    for gen in range(generations):
        gen_start = _time.time()
        # 评估当前种群
        scored = []
        for expr in population_list:
            result = evaluate_expr_on_pool(expr, panels, start_date, end_date)
            evaluated_count += 1
            if result is None:
                continue
            scored.append((expr, result["ir"], result))

        if not scored:
            break

        # 按 IR 降序
        scored.sort(key=lambda x: -x[1])

        # 保留 top_k
        kept = scored[:top_k]
        best_overall = kept[:top_k]
        best_ir = kept[0][1] if kept else 0.0

        history.append({
            "generation": gen,
            "best_ir": round(best_ir, 4),
            "best_expr": kept[0][0] if kept else "",
            "kept_count": len(kept),
            "duration_s": round(_time.time() - gen_start, 1),
        })

        logger.info("GP gen=%d best_ir=%.4f kept=%d", gen, best_ir, len(kept))

        # 生成下一代: top_k 变异 + 交叉
        next_population = [e for e, _, _ in kept]  # 保留父代
        while len(next_population) < population:
            if random.random() < 0.5 and len(kept) >= 2:
                # 交叉
                a, b = random.sample([e for e, _, _ in kept], 2)
                ca, cb = crossover(a, b)
                next_population.append(ca)
                if len(next_population) < population:
                    next_population.append(cb)
            else:
                # 变异
                parent = random.choice([e for e, _, _ in kept])
                next_population.append(mutate(parent))

        # 去重
        population_list = list(dict.fromkeys(next_population))[:population]

    # 保存候选到 DB
    from database import execute_many
    now = _time.strftime("%Y-%m-%d %H:%M:%S")
    statements = []
    for expr, ir, metrics in best_overall:
        statements.append((
            "INSERT INTO factor_candidates "
            "(run_id, expr_text, ic_mean, ir, win_rate, valid_days, tree_depth, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, expr,
             metrics["ic_mean"], metrics["ir"], metrics["win_rate"],
             metrics["valid_days"], metrics["tree_depth"], now)
        ))
    if statements:
        try:
            execute_many(statements)
        except Exception as e:
            logger.warning("save factor_candidates failed: %s", str(e)[:200])

    return {
        "run_id": run_id,
        "best": [
            {
                "expr": e,
                "ir": round(m["ir"], 4),
                "ic_mean": round(m["ic_mean"], 5),
                "win_rate": round(m["win_rate"], 3),
                "valid_days": m["valid_days"],
                "tree_depth": m["tree_depth"],
            }
            for e, _, m in best_overall
        ],
        "history": history,
        "stats": {
            "evaluated": evaluated_count,
            "duration_s": round(_time.time() - start_time, 1),
            "kept": len(best_overall),
        },
    }