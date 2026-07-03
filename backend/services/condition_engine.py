"""条件表达式引擎 — 将 JSON 条件树编译为可执行函数

支持的操作符:
  比较: >, <, >=, <=, ==, !=
  范围: between (含边界)
  交叉: cross_above, cross_below (需要序列数据)
  集合: in_list, not_in_list (行业筛选等)
  字段比较: field vs compare_field (如 close > ma20)

条件树格式:
  {"logic": "AND", "conditions": [...]}
  {"logic": "OR", "conditions": [...]}
  嵌套支持: {"logic": "AND", "conditions": [condition, {"logic": "OR", ...}]}
"""

import logging
from typing import Any, Callable, Optional, Union

logger = logging.getLogger(__name__)


# ── 操作符实现 ──

def _op_gt(a, b): return a is not None and b is not None and a > b
def _op_lt(a, b): return a is not None and b is not None and a < b
def _op_gte(a, b): return a is not None and b is not None and a >= b
def _op_lte(a, b): return a is not None and b is not None and a <= b
def _op_eq(a, b): return a is not None and b is not None and a == b
def _op_neq(a, b): return a is not None and b is not None and a != b
def _op_between(a, b):
    if a is None or b is None:
        return False
    if not isinstance(b, (list, tuple)) or len(b) != 2:
        return False
    return b[0] <= a <= b[1]
def _op_in_list(a, b):
    """检查 a 是否匹配 b 中的任一项（b 支持逗号分隔的字符串或列表）
    e.g. _op_in_list('半导体', '科技,白酒') → '科技' in '半导体'? False
         _op_in_list('半导体', '科技,半导体') → '科技' in '半导体' OR '半导体' in '半导体' → True
    """
    if a is None or b is None or a == "": return False
    if isinstance(b, (list, tuple)):
        items = [str(x).strip() for x in b]
    else:
        items = [x.strip() for x in str(b).split(",") if x.strip()]
    return any(item in a for item in items)

def _op_not_in_list(a, b):
    """排除匹配：a 不匹配 b 中的任一项"""
    if a is None or b is None: return True
    if a == "": return True  # 无行业信息的不排除
    if isinstance(b, (list, tuple)):
        items = [str(x).strip() for x in b]
    else:
        items = [x.strip() for x in str(b).split(",") if x.strip()]
    return not any(item in a for item in items)

def _op_cross_above(seq_a, threshold, window: int = 2):
    """检测序列 A 是否在最近 window 天内上穿阈值 (或上穿 compare_field 序列)"""
    if seq_a is None or not hasattr(seq_a, '__len__') or len(seq_a) < window + 1:
        return False
    # seq_a 是序列 (list), 检查 latest 是否 > threshold 且 prev 是否 <= threshold
    val = seq_a[-1]
    prev_val = seq_a[-window] if len(seq_a) >= window else seq_a[-2]
    if isinstance(threshold, list):
        # compare_field 的情况: 两个序列交叉
        t_val = threshold[-1]
        t_prev = threshold[-window] if len(threshold) >= window else threshold[-2]
        return val is not None and t_val is not None and val > t_val and (prev_val is None or t_prev is None or prev_val <= t_prev)
    return val is not None and val > threshold and (prev_val is None or prev_val <= threshold)

def _op_cross_below(seq_a, threshold, window: int = 2):
    """检测序列 A 是否在最近 window 天内下穿阈值"""
    if seq_a is None or not hasattr(seq_a, '__len__') or len(seq_a) < window + 1:
        return False
    val = seq_a[-1]
    prev_val = seq_a[-window] if len(seq_a) >= window else seq_a[-2]
    if isinstance(threshold, list):
        t_val = threshold[-1]
        t_prev = threshold[-window] if len(threshold) >= window else threshold[-2]
        return val is not None and t_val is not None and val < t_val and (prev_val is None or t_prev is None or prev_val >= t_prev)
    return val is not None and val < threshold and (prev_val is None or prev_val >= threshold)


# ── 操作符注册表 ──

SIMPLE_OPS = {
    ">": _op_gt, "<": _op_lt,
    ">=": _op_gte, "<=": _op_lte,
    "==": _op_eq, "!=": _op_neq,
    "between": _op_between,
    "in_list": _op_in_list, "not_in_list": _op_not_in_list,
}

CROSS_OPS = {
    "cross_above": _op_cross_above,
    "cross_below": _op_cross_below,
}


# ── 主要 API ──

def compile_condition(cond: dict) -> Callable[[dict], bool]:
    """将单个条件 JSON 编译为 (stock_data: dict) -> bool 函数

    stock_data 是一个字典，包含该股票的所有已计算字段。例如:
      {"close": 15.23, "ma20": 14.98, "rsi_14": 45.2, "pe": 12.5, ...}

    对于交叉操作符，序列字段以 `_seq` 后缀存储:
      {"ma5_seq": [13.1, 13.3, ...], "ma10_seq": [13.5, 13.4, ...]}
    """
    field = cond.get("field", "")
    operator = cond.get("operator", "")
    value = cond.get("value")
    compare_field = cond.get("compare_field")  # 用于字段间比较

    if operator in SIMPLE_OPS:
        op_fn = SIMPLE_OPS[operator]

        if compare_field is not None:
            # 字段 vs 字段 比较: field > compare_field (取各自序列的最新值)
            # 支持序列比较 (如 MA5 vs MA10)
            f_seq_key = f"{field}_seq"
            c_seq_key = f"{compare_field}_seq"

            def _field_vs_field(data: dict, _op=op_fn, _f=field, _cf=compare_field,
                                _f_seq=f_seq_key, _c_seq=c_seq_key) -> bool:
                # 优先使用序列的最新值，回退到标量值
                a = data.get(_f)
                b = data.get(_cf)
                # 支持 "close_vs_ma20" 等 _vs_ 字段：提取基础字段名
                if a is None and "_vs_" in _f:
                    base_field = _f.split("_vs_")[0]
                    a = data.get(base_field)
                # 尝试用序列的最后值
                seq_a = data.get(_f_seq)
                seq_b = data.get(_c_seq)
                if seq_a is not None and hasattr(seq_a, '__len__') and len(seq_a) > 0:
                    a = seq_a[-1]
                if seq_b is not None and hasattr(seq_b, '__len__') and len(seq_b) > 0:
                    b = seq_b[-1]
                if a is None:
                    logger.debug("condition_engine: field '%s' is None in comparison", _f)
                if b is None:
                    logger.debug("condition_engine: compare_field '%s' is None in comparison", _cf)
                return _op(a, b)
            return _field_vs_field
        else:
            def _simple(data: dict, _op=op_fn, _f=field, _v=value) -> bool:
                val = data.get(_f)
                if val is None:
                    logger.debug("condition_engine: field '%s' is None, treating as False", _f)
                return _op(val, _v)
            return _simple

    elif operator in CROSS_OPS:
        op_fn = CROSS_OPS[operator]
        f_seq = f"{field}_seq"
        c_seq = f"{compare_field}_seq" if compare_field else None

        if compare_field:
            def _cross_field(data: dict, _op=op_fn, _fs=f_seq, _cs=c_seq) -> bool:
                seq_a = data.get(_fs)
                seq_b = data.get(_cs) if _cs else None
                threshold = seq_b if seq_b is not None else value
                return _op(seq_a, threshold)
            return _cross_field
        else:
            def _cross_val(data: dict, _op=op_fn, _fs=f_seq, _v=value) -> bool:
                return _op(data.get(_fs), _v)
            return _cross_val

    raise ValueError(f"未知操作符: {operator} for field {field}")


def evaluate(stock_data: dict, condition_tree: dict) -> bool:
    """递归评估 AND/OR 条件树"""
    logic = condition_tree.get("logic", "AND").upper()
    conditions = condition_tree.get("conditions", [])

    if not conditions:
        return True

    results = []
    for cond in conditions:
        if "conditions" in cond:
            # 嵌套条件树
            results.append(evaluate(stock_data, cond))
        else:
            fn = compile_condition(cond)
            try:
                results.append(fn(stock_data))
            except Exception as e:
                logger.warning("condition_engine: eval error for field '%s': %s",
                               cond.get("field", "?"), e)
                results.append(False)

    if logic == "AND":
        return all(results)
    elif logic == "OR":
        return any(results)
    elif logic == "NOT":
        return not all(results) if results else True

    return False


def get_required_fields(condition_tree: dict) -> dict:
    """分析条件树，返回需要的字段分类

    返回格式:
      {
        "scalar_fields": set(),     # 需要计算的标量字段 (如 price, pe, rsi_14)
        "sequence_fields": set(),   # 需要计算的序列字段 (如 ma5, ma20 — 带 _seq 后缀)
        "cross_fields": dict(),     # 交叉操作符字段 {field_key: window}
      }
    """
    scalar = set()
    sequences = set()
    crosses = {}

    def _walk(tree):
        for cond in tree.get("conditions", []):
            if "conditions" in cond:
                _walk(cond)
            else:
                field = cond.get("field", "")
                operator = cond.get("operator", "")
                compare = cond.get("compare_field")

                if operator in CROSS_OPS:
                    sequences.add(field)
                    crosses[field] = cond.get("value", 2)  # window
                    if compare:
                        sequences.add(compare)
                elif compare:
                    scalar.add(field)
                    scalar.add(compare)
                    # 用于字段比较的序列
                    sequences.add(field)
                    sequences.add(compare)
                else:
                    scalar.add(field)
                    # 交叉字段需要序列数据
                    if operator in ("cross_above", "cross_below"):
                        sequences.add(field)

    _walk(condition_tree)

    return {
        "scalar_fields": scalar - sequences,  # 纯标量（不需要序列）
        "sequence_fields": sequences,
        "cross_fields": crosses,
    }
