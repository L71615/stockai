"""Agent 工具调用注册表 — v4.0 A2

为多 Agent 提供工具调用能力,phase 1 起步 3 个核心工具:
  - get_quote:   实时报价(futu/akshare/sina fallback)
  - get_factor:  因子查询(从 FACTOR_REGISTRY)
  - run_backtest: 策略回测(turtle_s1 / ma_cross / momentum / value)

Schema 格式以 OpenAI 协议为标准,Anthropic 协议通过 `to_anthropic_tools()` 转换。

工具执行器是同步函数,封装了对现有 service 的调用;调用方(
`ai_chat_with_tools` in ai_service.py)负责工具调用循环和消息拼接。

用法:
  from services.agent_tools import TOOL_REGISTRY, to_anthropic_tools, execute_tool_call

  schemas = list(TOOL_REGISTRY.values())
  result = execute_tool_call("get_quote", {"code": "600519"})
"""

import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  工具定义 — OpenAI 协议格式(标准)
# ═══════════════════════════════════════════════════════════════

TOOL_GET_QUOTE = {
    "type": "function",
    "function": {
        "name": "get_quote",
        "description": (
            "获取股票实时报价(最新价、涨跌、成交量、换手率等)。"
            "数据来自 futu / akshare / sina 任一可用供应商,失败链路已自动 fallback。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码,6 位字符串,如 600519 / 000001",
                },
            },
            "required": ["code"],
        },
    },
}

TOOL_GET_FACTOR = {
    "type": "function",
    "function": {
        "name": "get_factor",
        "description": (
            "查询股票指定因子值,覆盖 29 个已完成因子(动量/波动/量价/技术/情绪等)。"
            "可用因子名见 factor_service.FACTOR_REGISTRY,例如 MA5 / RSI / MACD_SIGNAL / PE_INVERSE / OBV_DIVERGENCE。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码,6 位字符串",
                },
                "factor_name": {
                    "type": "string",
                    "description": "因子名,大小写不敏感,如 MA5、RSI、PE_INVERSE",
                },
            },
            "required": ["code", "factor_name"],
        },
    },
}

TOOL_RUN_BACKTEST = {
    "type": "function",
    "function": {
        "name": "run_backtest",
        "description": (
            "对单只股票运行策略回测,返回总收益、夏普比率、最大回撤、胜率、交易笔数等指标。"
            "支持策略:turtle_s1(海龟 S1 突破,默认)/ ma_cross / momentum / value / pullback 等。"
            "回测已包含手续费(佣金万三 + 印花税千一)+ 滑点(v4.0 B4,默认 10bps = 0.1%)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码",
                },
                "strategy_id": {
                    "type": "string",
                    "description": "策略 ID,默认 turtle_s1",
                    "default": "turtle_s1",
                },
                "days": {
                    "type": "integer",
                    "description": "回测历史天数,默认 120",
                    "default": 120,
                },
                "slippage_bps": {
                    "type": "number",
                    "description": "滑点(bps,1bp = 0.01%),默认 10bps = 0.1%。设为 0 可关闭滑点。",
                    "default": 10.0,
                },
                "impact_bps": {
                    "type": "number",
                    "description": "冲击成本系数(bps,v4.0 B5)。平方根模型:impact = impact_bps × sqrt(order_size / ADV)。默认 0 = 关闭。",
                    "default": 0.0,
                },
            },
            "required": ["code"],
        },
    },
}

TOOL_CALC_T1_COST = {
    "type": "function",
    "function": {
        "name": "calc_t1_cost",
        "description": (
            "计算 T+1/T+2 短线持仓成本:卖出手续费(佣金+印花税+过户费)+ 持仓风险溢价。"
            "用于评估前晚买入、次日卖出场景的真实净收益(扣滑点 + 费)。"
            "返回净收益率(net_return_pct)和详细成本分解。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entry_price": {
                    "type": "number",
                    "description": "买入价(元/股)",
                },
                "exit_price": {
                    "type": "number",
                    "description": "卖出价(元/股,通常是次日开盘价或预期价)",
                },
                "shares": {
                    "type": "integer",
                    "description": "持股数,默认 100(A 股最小单位)",
                    "default": 100,
                },
                "hold_days": {
                    "type": "integer",
                    "description": "持仓天数,T+1 = 1, T+2 = 2",
                    "default": 1,
                },
                "slippage_bps": {
                    "type": "number",
                    "description": "滑点(bps),默认 10bps",
                    "default": 10.0,
                },
                "daily_risk_premium_bps": {
                    "type": "number",
                    "description": "每日持仓风险溢价(bps,默认 5bps = 0.05%/天)",
                    "default": 5.0,
                },
            },
            "required": ["entry_price", "exit_price"],
        },
    },
}

# 工具名 → schema 映射(规范注册表)
TOOL_REGISTRY: dict[str, dict] = {
    "get_quote": TOOL_GET_QUOTE,
    "get_factor": TOOL_GET_FACTOR,
    "run_backtest": TOOL_RUN_BACKTEST,
    "calc_t1_cost": TOOL_CALC_T1_COST,
}


def list_tool_names() -> list[str]:
    """返回所有可用工具名"""
    return list(TOOL_REGISTRY.keys())


def get_tool_schema(name: str) -> dict | None:
    """获取单个工具 schema,不存在返回 None"""
    return TOOL_REGISTRY.get(name)


def to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """OpenAI 格式 → Anthropic 格式

    OpenAI:   {"type": "function", "function": {"name", "description", "parameters"}}
    Anthropic: {"name", "description", "input_schema"}

    对于非 function 类型的 input(扩展场景),原样保留。
    """
    out: list[dict] = []
    for t in tools or []:
        if isinstance(t, dict) and t.get("type") == "function" and "function" in t:
            f = t["function"]
            out.append({
                "name": f.get("name", ""),
                "description": f.get("description", ""),
                "input_schema": f.get("parameters", {"type": "object", "properties": {}}),
            })
        else:
            # 防御性: 已经是 Anthropic 格式或其他,原样保留
            out.append(t)
    return out


# ═══════════════════════════════════════════════════════════════
#  工具执行器 — 同步函数(直接调同步服务)
# ═══════════════════════════════════════════════════════════════

def _get_quote_tool(code: str) -> dict:
    """获取实时报价 — 调 vendor_router.get_realtime_quote"""
    try:
        from services.vendor_router import route

        data = route("get_realtime_quote", code=code)
        if not isinstance(data, dict):
            return {"error": "供应商返回非 dict", "code": code}
        if "error" in data:
            return {"error": data.get("error", "unknown"), "code": code, "source": data.get("source")}
        # 截取关键字段,避免返回过大
        return {
            "code": code,
            "price": data.get("price"),
            "change_pct": data.get("change_pct"),
            "open": data.get("open"),
            "high": data.get("high"),
            "low": data.get("low"),
            "close": data.get("close"),
            "volume": data.get("volume"),
            "amount": data.get("amount"),
            "turnover_rate": data.get("turnover_rate"),
            "source": data.get("source"),
        }
    except Exception as e:
        logger.warning("get_quote_tool(%s) failed: %s", code, e)
        return {"error": str(e), "code": code}


def _get_factor_tool(code: str, factor_name: str) -> dict:
    """查询指定因子值 — 加载 K 线后调 compute_all_factors"""
    try:
        from database import query_all
        from services.factor_service import compute_all_factors, FACTOR_REGISTRY

        # 因子名兼容(大小写)
        canonical = factor_name.upper()
        if canonical not in FACTOR_REGISTRY:
            return {
                "error": f"未知因子: {factor_name}",
                "code": code,
                "available": sorted(FACTOR_REGISTRY.keys())[:20],
            }

        # 加载 K 线
        rows = query_all(
            """SELECT trade_date, open, high, low, close, volume
               FROM historical_kline
               WHERE stock_code = ? AND trade_date >= date('now','-180 days')
               ORDER BY trade_date ASC""",
            (code,),
        )
        if not rows or len(rows) < 60:
            return {"error": "K 线数据不足 60 天", "code": code, "factor": factor_name}

        closes = [float(r["close"]) for r in rows if r["close"] is not None]
        highs = [float(r["high"]) for r in rows if r["high"] is not None]
        lows = [float(r["low"]) for r in rows if r["low"] is not None]
        volumes = [float(r["volume"]) for r in rows if r["volume"] is not None]

        # 计算所有因子 + 取指定
        all_factors = compute_all_factors(code, closes, highs, lows, volumes)
        value = all_factors.get(canonical)
        return {
            "code": code,
            "factor": factor_name,
            "value": value,
            "close": closes[-1],
            "as_of": rows[-1].get("trade_date"),
        }
    except Exception as e:
        logger.warning("get_factor_tool(%s, %s) failed: %s", code, factor_name, e)
        return {"error": str(e), "code": code, "factor": factor_name}


def _run_backtest_tool(code: str, strategy_id: str = "turtle_s1", days: int = 120, slippage_bps: float = 10.0, impact_bps: float = 0.0) -> dict:
    """单股策略回测 — 调 strategy_backtest_service.run_strategy_backtest

    Args:
        slippage_bps: 滑点(bps),默认 10bps = 0.1%。v4.0 B4 引入。
        impact_bps: 冲击成本系数(v4.0 B5),默认 0 = 关闭。
    """
    try:
        from services.strategy_backtest_service import run_strategy_backtest
        from datetime import datetime, timedelta

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")

        result = run_strategy_backtest(
            strategy_ids=[strategy_id],
            stock_codes=[code],
            start_date=start_date,
            end_date=end_date,
            initial_cash=100000,
            hold_days=5,
            max_positions=1,
            position_size_pct=1.0,
            slippage_bps=slippage_bps,
            impact_bps=impact_bps,
        )
        if not isinstance(result, dict):
            return {"error": "回测结果非 dict", "code": code, "strategy": strategy_id}
        if "error" in result:
            return {"error": result["error"], "code": code, "strategy": strategy_id}

        metrics = result.get("metrics", {}) or {}
        trades = result.get("trades", []) or []
        return {
            "code": code,
            "strategy": strategy_id,
            "slippage_bps": slippage_bps,
            "impact_bps": impact_bps,
            "total_return": metrics.get("total_return"),
            "sharpe": metrics.get("sharpe"),
            "max_drawdown": metrics.get("max_drawdown"),
            "win_rate": metrics.get("win_rate"),
            "num_trades": metrics.get("num_trades"),
            "trades": trades[:5],  # 只返回前 5 笔,避免消息过长
        }
    except Exception as e:
        logger.warning("run_backtest_tool(%s, %s) failed: %s", code, strategy_id, e)
        return {"error": str(e), "code": code, "strategy": strategy_id}


def _calc_t1_cost_tool(
    entry_price: float,
    exit_price: float,
    shares: int = 100,
    hold_days: int = 1,
    slippage_bps: float = 10.0,
    daily_risk_premium_bps: float = 5.0,
) -> dict:
    """T+1/T+2 持仓成本计算 — 调 services.t1_cost"""
    try:
        from services.t1_cost import calc_t1_holding_cost
        return calc_t1_holding_cost(
            entry_price=entry_price,
            exit_price=exit_price,
            shares=shares,
            hold_days=hold_days,
            slippage_bps=slippage_bps,
            daily_risk_premium_bps=daily_risk_premium_bps,
        )
    except Exception as e:
        logger.warning("calc_t1_cost_tool failed: %s", e)
        return {"error": str(e)}


# 工具执行器映射
TOOL_EXECUTORS: dict[str, Callable[..., dict]] = {
    "get_quote": _get_quote_tool,
    "get_factor": _get_factor_tool,
    "run_backtest": _run_backtest_tool,
    "calc_t1_cost": _calc_t1_cost_tool,
}


def execute_tool_call(name: str, arguments: dict | str) -> dict:
    """同步执行工具调用

    Args:
        name: 工具名(get_quote / get_factor / run_backtest)
        arguments: 参数 dict 或 JSON 字符串

    Returns:
        工具执行结果 dict,出错时 {"error": "..."}
    """
    if name not in TOOL_EXECUTORS:
        return {"error": f"未知工具: {name}", "available": list_tool_names()}

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as e:
            return {"error": f"参数 JSON 解析失败: {e}", "raw": arguments[:200]}

    if not isinstance(arguments, dict):
        return {"error": f"参数必须是 dict, 收到 {type(arguments).__name__}"}

    try:
        return TOOL_EXECUTORS[name](**arguments)
    except TypeError as e:
        # 函数签名不匹配(参数错误)
        return {"error": f"参数错误: {e}", "tool": name, "arguments": arguments}
    except Exception as e:
        logger.warning("execute_tool_call(%s, %s) failed: %s", name, arguments, e)
        return {"error": str(e), "tool": name}
