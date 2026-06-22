"""选股系统 API：多因子筛选 / 策略回测 / AI盯盘

流程: 全市场扫描 → AI二次筛选 → 策略回测 → 加盯盘 → AI盯盘简报
"""

import json
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from database import query_all, query_one, execute
from services.rate_limit import limiter_ai

router = APIRouter(prefix="/api/screener", tags=["Screener"])


# ═══════════════════════════════════════════════════════════
# 请求体
# ═══════════════════════════════════════════════════════════

class ScreenerRequest(BaseModel):
    stock_count: int = 500          # 扫描股票数量：500=沪深300+中证500, 0=全A股
    max_workers: int = 3            # 并发线程数（不宜过高，Baostock 有全局锁）
    industry_neutral: bool = True   # 是否行业中性化


class BacktestSingleRequest(BaseModel):
    code: str
    strategy: str = "ma_cross"
    initial_cash: float = 100000
    days: int = 365
    params: dict = {}


class BacktestBatchRequest(BaseModel):
    codes: list[str]
    strategies: list[str] = ["ma_cross", "macd", "rsi"]
    initial_cash: float = 100000
    days: int = 365


class WatchlistAddRequest(BaseModel):
    code: str
    name: str = ""
    reason: str = ""
    score: Optional[float] = None
    backtest_strategy: str = ""
    backtest_sharpe: Optional[float] = None


class AIScreenRequest(BaseModel):
    candidates_json: str = ""       # 候选池 JSON
    provider: str = ""
    top_n: int = 10                 # AI 从候选池中再选几只


class BriefingRequest(BaseModel):
    provider: str = ""


# ═══════════════════════════════════════════════════════════
# 多因子筛选
# ═══════════════════════════════════════════════════════════

# 扫描状态（防止重复请求）
_screen_status = {"running": False, "progress": 0, "total": 0, "result": None}


@router.post("/run")
def run_screener(body: ScreenerRequest):
    """启动一次全市场多因子扫描（异步，状态通过 /status 查询）"""
    global _screen_status

    if _screen_status["running"]:
        return {"error": "扫描已在运行中", "progress": _screen_status["progress"], "total": _screen_status["total"]}

    _screen_status = {"running": True, "progress": 0, "total": 0, "result": None}

    def _run():
        from services.screener_service import run_screener as _run_screener, get_all_stock_list, industry_neutralize

        stock_list = get_all_stock_list()
        if body.stock_count > 0 and len(stock_list) > body.stock_count:
            stock_list = stock_list[:body.stock_count]

        _screen_status["total"] = len(stock_list)

        def progress_cb(current, total):
            _screen_status["progress"] = current
            _screen_status["total"] = total

        result = _run_screener(stock_list, max_workers=body.max_workers, progress_callback=progress_cb)

        if body.industry_neutral and "error" not in result:
            result["candidates"] = industry_neutralize(result["candidates"])

        # 保存结果到数据库
        try:
            execute(
                """INSERT INTO screener_results (user_id, total_stocks, scanned, candidates_json, factor_weights_json, market_state)
                   VALUES (1, ?, ?, ?, ?, ?)""",
                (result.get("total_stocks", 0), result.get("scanned", 0),
                 json.dumps(result.get("candidates", []), ensure_ascii=False),
                 json.dumps(result.get("factor_weights", {}), ensure_ascii=False),
                 result.get("market_state", "")),
            )
        except Exception:
            pass

        _screen_status["result"] = result
        _screen_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()

    return {"message": "扫描已启动", "total": _screen_status["total"]}


@router.get("/status")
def screener_status():
    """查询扫描进度"""
    return {
        "running": _screen_status["running"],
        "progress": _screen_status["progress"],
        "total": _screen_status["total"],
        "percent": round(_screen_status["progress"] / max(_screen_status["total"], 1) * 100, 1),
        "has_result": _screen_status["result"] is not None,
    }


@router.get("/results")
def screener_results(limit: int = 50):
    """获取最近一次扫描结果"""
    if _screen_status["result"]:
        candidates = _screen_status["result"].get("candidates", [])[:limit]
        return {
            "from_cache": True,
            "market_state": _screen_status["result"].get("market_state", ""),
            "total_stocks": _screen_status["result"].get("total_stocks", 0),
            "scanned": _screen_status["result"].get("scanned", 0),
            "factor_weights": _screen_status["result"].get("factor_weights", {}),
            "candidates": candidates,
        }

    # 从数据库取最近的结果
    row = query_one("SELECT * FROM screener_results ORDER BY id DESC LIMIT 1")
    if not row:
        return {"from_cache": False, "candidates": [], "message": "暂无扫描结果，请先运行 /api/screener/run"}

    return {
        "from_cache": True,
        "created_at": row["created_at"],
        "market_state": row["market_state"],
        "total_stocks": row["total_stocks"],
        "scanned": row["scanned"],
        "factor_weights": json.loads(row.get("factor_weights_json", "{}")),
        "candidates": json.loads(row.get("candidates_json", "[]"))[:limit],
    }


@router.get("/candidates")
def get_candidates(sort_by: str = "score", limit: int = 20):
    """获取候选池（可从数据库历史或内存结果读取）"""
    if _screen_status["result"]:
        candidates = _screen_status["result"].get("candidates", [])
        if sort_by == "score_neutral":
            candidates.sort(key=lambda x: x.get("score_neutral", x["score"]), reverse=True)
        return candidates[:limit]

    row = query_one("SELECT * FROM screener_results ORDER BY id DESC LIMIT 1")
    if not row:
        return []
    return json.loads(row.get("candidates_json", "[]"))[:limit]


# ═══════════════════════════════════════════════════════════
# AI 二次筛选
# ═══════════════════════════════════════════════════════════

@router.post("/ai-screen")
async def ai_screen(body: AIScreenRequest):
    """让 AI 从候选池中二次筛选，给出推荐理由"""
    from services.ai_service import ai_chat

    if body.candidates_json:
        candidates = json.loads(body.candidates_json)
    elif _screen_status["result"]:
        candidates = _screen_status["result"].get("candidates", [])[:30]
    else:
        row = query_one("SELECT * FROM screener_results ORDER BY id DESC LIMIT 1")
        if not row:
            raise HTTPException(400, "无候选池数据，请先运行多因子扫描")
        candidates = json.loads(row.get("candidates_json", "[]"))[:30]

    if not candidates:
        raise HTTPException(400, "候选池为空")

    # 构建候选摘要给AI
    candidate_text = ""
    for i, c in enumerate(candidates[:30]):
        tf = c.get("top_factors", [])
        top3 = ", ".join(f"{t['factor']}({t['contribution']:+.4f})" for t in tf[:3])
        candidate_text += (
            f"{i + 1}. {c['code']} {c.get('name', '')} | "
            f"行业: {c.get('industry', 'N/A')} | "
            f"得分: {c['score']:.4f} | "
            f"主要因子: {top3}\n"
        )

    prompt = f"""你是资深A股分析师。以下是多因子模型筛选出的候选股票（前30只），请从中选出 {body.top_n} 只最有投资价值的：

{candidate_text}

选股要求：
1. 综合考虑得分、行业分散度、当前市场环境
2. 避免集中在同一个行业
3. 优先选基本面扎实（得分中有 PE/ROE 等基本面因子正向贡献的）
4. 注意排除纯题材炒作的高波动标的

请严格按JSON输出：
{{"picks":[{{"code":"股票代码","name":"名称","reason":"推荐理由(30字内)","score":得分}}],"summary":"整体选股思路(80字内)"}}

不要包含任何markdown代码块标记。"""

    from services.ai_service import get_default_provider
    provider = body.provider or get_default_provider()
    try:
        raw = await ai_chat(
            prompt,
            provider=provider,
            system_prompt="你是专业A股基金经理。严格按JSON输出，不输出markdown。",
        )

        # 解析
        text = raw.strip()
        import re
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
            if text.rstrip().endswith("```"):
                text = text[:text.rfind("```")].strip()
        try:
            ai_result = json.loads(text)
        except Exception:
            m = re.search(r'\{.*\}', text, re.DOTALL)
            ai_result = json.loads(m.group(0)) if m else {"picks": [], "summary": "解析失败"}

        return {
            "picks": ai_result.get("picks", []),
            "summary": ai_result.get("summary", ""),
            "total_candidates": len(candidates),
        }

    except Exception as e:
        raise HTTPException(500, f"AI筛选失败: {e}")


# ═══════════════════════════════════════════════════════════
# 策略回测
# ═══════════════════════════════════════════════════════════

@router.get("/strategies")
def list_strategies():
    """列出所有可用策略"""
    from services.backtest_service import AVAILABLE_STRATEGIES
    return {
        "strategies": [
            {"id": k, "name": v["name"], "default_params": v["params"]}
            for k, v in AVAILABLE_STRATEGIES.items()
        ]
    }


@router.post("/backtest/single")
def backtest_single(body: BacktestSingleRequest):
    """单只股票单策略回测"""
    from services.backtest_service import run_backtest

    params = body.params or {}
    result = run_backtest(body.code, body.strategy, body.initial_cash, body.days, **params)
    if "error" in result:
        raise HTTPException(400, result["error"])

    # 保存结果
    try:
        execute(
            """INSERT INTO backtest_results (user_id, stock_code, strategy, total_return, annual_return, sharpe,
               max_drawdown, win_rate, profit_factor, num_trades, initial_cash, final_value, params_json)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.code, body.strategy,
             result.get("total_return"), result.get("annual_return"), result.get("sharpe"),
             result.get("max_drawdown"), result.get("win_rate"), result.get("profit_factor"),
             result.get("num_trades"), result.get("initial_cash"), result.get("final_value"),
             json.dumps(body.params or {}, ensure_ascii=False)),
        )
    except Exception:
        pass

    return result


@router.post("/backtest/batch")
def backtest_batch(body: BacktestBatchRequest):
    """多只股票 × 多种策略 批量回测"""
    from services.backtest_service import run_backtest_batch
    return run_backtest_batch(body.codes, body.strategies, body.initial_cash, body.days)


@router.get("/backtest/history")
def backtest_history(code: str = "", limit: int = 50):
    """查询历史回测记录"""
    if code:
        return query_all(
            "SELECT * FROM backtest_results WHERE user_id = 1 AND stock_code = ? ORDER BY id DESC LIMIT ?",
            (code, limit),
        )
    return query_all(
        "SELECT * FROM backtest_results WHERE user_id = 1 ORDER BY id DESC LIMIT ?",
        (limit,),
    )


# ═══════════════════════════════════════════════════════════
# 盯盘管理
# ═══════════════════════════════════════════════════════════

@router.post("/watchlist/add")
def watchlist_add(body: WatchlistAddRequest):
    """添加股票到盯盘列表"""
    from services.watchdog_service import add_to_watchlist
    return add_to_watchlist(
        code=body.code,
        name=body.name,
        reason=body.reason,
        score=body.score,
        backtest_strategy=body.backtest_strategy,
        backtest_sharpe=body.backtest_sharpe,
    )


@router.delete("/watchlist/{code}")
def watchlist_remove(code: str):
    """从盯盘列表中移除"""
    from services.watchdog_service import remove_from_watchlist
    return remove_from_watchlist(code)


@router.get("/watchlist")
def watchlist_list():
    """获取盯盘列表"""
    from services.watchdog_service import get_watchlist
    return get_watchlist()


@router.get("/watchlist/history")
def watchlist_history(limit: int = 50):
    """获取盯盘历史"""
    from services.watchdog_service import get_watch_history
    return get_watch_history(limit=limit)


@router.post("/watchlist/check")
def watchlist_check():
    """立即检查盯盘列表中的所有股票"""
    from services.watchdog_service import check_watchlist
    return check_watchlist()


@router.post("/watchlist/briefing")
async def watchlist_briefing(body: BriefingRequest):
    """AI 生成盯盘简报"""
    from services.watchdog_service import generate_daily_briefing
    briefing = await generate_daily_briefing(provider=body.provider)
    return {"briefing": briefing, "generated_at": datetime.now().isoformat()}


@router.get("/alerts")
def get_alerts(limit: int = 30, severity: str = ""):
    """获取历史预警记录"""
    if severity:
        return query_all(
            "SELECT * FROM screener_alerts WHERE user_id = 1 AND severity = ? ORDER BY id DESC LIMIT ?",
            (severity, limit),
        )
    return query_all(
        "SELECT * FROM screener_alerts WHERE user_id = 1 ORDER BY id DESC LIMIT ?",
        (limit,),
    )


# ═══════════════════════════════════════════════════════════
# 通知推送
# ═══════════════════════════════════════════════════════════

class NotifyConfigBody(BaseModel):
    wechat_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    email_sender: str = ""
    email_password: str = ""
    email_receiver: str = ""
    notify_enabled: bool = False


@router.get("/notify/config")
def get_notify_config():
    """获取通知配置"""
    from services.notify_service import _get_config, is_configured
    cfg = _get_config()
    return {
        "wechat_webhook_url": cfg.get("wechat_webhook_url", ""),
        "telegram_bot_token": cfg.get("telegram_bot_token", ""),
        "telegram_chat_id": cfg.get("telegram_chat_id", ""),
        "email_sender": cfg.get("email_sender", ""),
        "email_password": "***" if cfg.get("email_password") else "",
        "email_receiver": cfg.get("email_receiver", ""),
        "notify_enabled": cfg.get("notify_enabled") or False,
        "is_configured": is_configured(),
    }


@router.post("/notify/config")
def save_notify_config(body: NotifyConfigBody):
    """保存通知配置到 settings 表"""
    cfg = {
        "wechat_webhook_url": body.wechat_webhook_url,
        "telegram_bot_token": body.telegram_bot_token,
        "telegram_chat_id": body.telegram_chat_id,
        "email_sender": body.email_sender,
        "email_receiver": body.email_receiver,
        "notify_enabled": body.notify_enabled,
    }
    # 密码不覆盖旧的（如果传入 ***）
    if body.email_password and body.email_password != "***":
        cfg["email_password"] = body.email_password
    else:
        # 保留旧密码
        try:
            old = json.loads(query_one("SELECT value FROM settings WHERE key = 'notify_config'").get("value", "{}") or "{}")
            cfg["email_password"] = old.get("email_password", "")
        except Exception:
            cfg["email_password"] = ""

    execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('notify_config', ?)",
        (json.dumps(cfg, ensure_ascii=False),),
    )
    return {"message": "通知配置已保存"}


@router.post("/notify/test")
def test_notify():
    """发送测试通知"""
    from services.notify_service import send_notification, is_configured
    if not is_configured():
        raise HTTPException(400, "未配置任何通知渠道，请先配置")
    result = send_notification("✅ 这是一条来自 StockAI 的测试消息，通知配置正确！", title="StockAI 通知测试")
    return result


# ═══════════════════════════════════════════════════════════
# 多 Agent 交叉验证
# ═══════════════════════════════════════════════════════════

class MultiAgentRequest(BaseModel):
    candidates_json: str = ""       # 候选池 JSON（为空则用最近一次扫描结果）
    provider: str = ""              # AI 供应商（为空则用默认）
    agent_keys: list[str] = []      # 要使用的 Agent，默认全部 5 个


@router.post("/multi-agent-screen")
@limiter_ai.limit("10/minute")
async def multi_agent_screen(body: MultiAgentRequest, request: Request):
    """5 Agent 交叉验证选股

    从候选池中选取 Top 30，5 个 AI 投资人格并行分析，投票聚合后输出综合排名。
    每个 Agent 从不同维度（价值/技术/风险/情绪/宏观）独立评估。
    """
    from services.multi_agent_service import run_multi_agent_screen

    # 获取候选池
    if body.candidates_json:
        candidates = json.loads(body.candidates_json)
    elif _screen_status["result"]:
        candidates = _screen_status["result"].get("candidates", [])[:30]
    else:
        row = query_one("SELECT * FROM screener_results ORDER BY id DESC LIMIT 1")
        if not row:
            raise HTTPException(400, "无候选池数据，请先运行 /api/screener/run")
        candidates = json.loads(row.get("candidates_json", "[]"))[:30]

    if not candidates:
        raise HTTPException(400, "候选池为空")

    from services.ai_service import get_default_provider
    provider = body.provider or get_default_provider()

    result = await run_multi_agent_screen(
        candidates=candidates,
        provider=provider,
        agent_keys=body.agent_keys if body.agent_keys else None,
    )

    if "error" in result:
        raise HTTPException(400, result["error"])

    return result


# ═══════════════════════════════════════════════════════════
# 全流程快捷接口 (选股 → 回测 → 盯盘)
# ═══════════════════════════════════════════════════════════

@router.post("/pipeline")
async def full_pipeline(body: AIScreenRequest):
    """一条龙：已有扫描结果 → AI筛选 → 回测 → 加入盯盘

    这是最常用的快捷操作：上次扫描的候选池直接走全流程。
    """
    results = {
        "step1_ai_screen": None,
        "step2_backtest": None,
        "step3_watchlist": [],
        "briefing": None,
    }

    # Step 1: AI 二次筛选
    ai_result = await ai_screen(body)
    results["step1_ai_screen"] = ai_result

    picks = ai_result.get("picks", [])
    if not picks:
        return {"error": "AI 未选出任何股票", "details": results}

    # Step 2: 对 AI 选出的股票跑回测
    codes = [p["code"] for p in picks]
    from services.backtest_service import run_backtest_batch
    bt_result = run_backtest_batch(codes, ["ma_cross", "macd", "rsi"], initial_cash=100000, days=365)
    results["step2_backtest"] = bt_result

    # Step 3: 回测结果可以的加入盯盘（Sharpe > 0.3 或 总收益 > 5%）
    from services.watchdog_service import add_to_watchlist

    best_per_stock = bt_result.get("summary", {}).get("best_strategy_per_stock", {})
    for r in bt_result.get("results", []):
        if "error" in r:
            continue
        code = r["code"]
        sharpe = r.get("sharpe", -999)
        total_ret = r.get("total_return", 0)

        if sharpe > 0.3 or total_ret > 0.05:
            # 找到对应 pick 的理由
            reason = ""
            score = None
            for p in picks:
                if p["code"] == code:
                    reason = p.get("reason", "")
                    score = p.get("score")
                    break

            wl_result = add_to_watchlist(
                code=code,
                name=r.get("name", ""),
                reason=reason,
                score=score,
                backtest_strategy=r["strategy"],
                backtest_sharpe=sharpe,
            )
            results["step3_watchlist"].append(wl_result)

    # Step 4: 生成盯盘简报（如果已有盯盘列表）
    if results["step3_watchlist"]:
        from services.watchdog_service import generate_daily_briefing
        try:
            results["briefing"] = await generate_daily_briefing(provider=body.provider)
        except Exception:
            results["briefing"] = "简报生成失败"

    return results


# ═══════════════════════════════════════════════════════════════
#  因子注册表 & 自定义因子 — 源自 qlib_factor_platform
# ═══════════════════════════════════════════════════════════════

@router.get("/factor-registry")
def get_factor_registry(category: str = ""):
    """
    获取因子注册表

    可选查询参数:
      category: 按分类筛选 (价格因子/成交量因子/技术指标因子/动量因子/
                波动率因子/量价因子/基本面因子/情绪因子/资金因子/社交因子)
    """
    from services.factor_service import FACTOR_REGISTRY

    items = []
    for name, info in FACTOR_REGISTRY.items():
        if category and info["category"] != category:
            continue
        items.append({"name": name, **info})

    return {
        "factors": items,
        "total": len(items),
        "categories": sorted(set(info["category"] for info in FACTOR_REGISTRY.values())),
    }


# ── 因子模板 (来自 qlib_factor_platform custom.py) ──
FACTOR_TEMPLATES = [
    {
        "id": "momentum",
        "name": "N日动量因子",
        "description": "计算N日前的价格相对于当前价格的变化率",
        "params": [{"key": "n", "type": "int", "default": 5, "min": 1, "max": 60,
                     "label": "回看天数"}],
    },
    {
        "id": "mean_reversion",
        "name": "均值回归因子",
        "description": "当前价格相对于N日均值的标准差倍数 (Z-Score)",
        "params": [{"key": "n", "type": "int", "default": 20, "min": 5, "max": 120,
                     "label": "均值窗口"}],
    },
    {
        "id": "volatility",
        "name": "N日波动率因子",
        "description": "N日收益率的标准差",
        "params": [{"key": "n", "type": "int", "default": 20, "min": 5, "max": 60,
                     "label": "波动率窗口"}],
    },
    {
        "id": "amount_ratio",
        "name": "成交额均值比因子",
        "description": "短期成交额均值与长期成交额均值的比值",
        "params": [
            {"key": "n", "type": "int", "default": 5, "min": 1, "max": 30, "label": "短期窗口"},
            {"key": "m", "type": "int", "default": 20, "min": 10, "max": 60, "label": "长期窗口"},
        ],
    },
    {
        "id": "price_position",
        "name": "价格位置因子",
        "description": "收盘价在N日高低点区间的相对位置 (0~1)",
        "params": [{"key": "n", "type": "int", "default": 20, "min": 5, "max": 120,
                     "label": "区间天数"}],
    },
]


@router.get("/factor-templates")
def get_factor_templates():
    """获取可用的因子模板列表 (用于前端因子编辑器)"""
    return {"templates": FACTOR_TEMPLATES}


# ── 因子表达式校验 (来自 qlib_factor_platform custom.py validate方法) ──
_VALID_FIELDS = {"$open", "$high", "$low", "$close", "$volume", "$amount",
                 "$vwap", "$market_cap", "$returns", "$pe", "$pb"}
_VALID_FUNCTIONS = {"Ref", "Mean", "Std", "Var", "Max", "Min", "Sum", "Count",
                    "Rank", "Quantile", "Corr", "Cov", "Slope", "Rsquare",
                    "IdxMax", "IdxMin", "Greater", "Less", "Abs", "Sign",
                    "Log", "Power", "Sqrt"}


@router.post("/factor-validate")
def validate_factor_expression(body: dict):
    """
    校验自定义因子表达式

    请求体: {"expression": "$close/Mean($close, 20) - 1"}

    返回:
      - valid: bool
      - error: 错误描述 (if any)
      - fields: 检测到的字段
      - functions: 检测到的函数
      - complexity: "简单" | "中等" | "复杂"
    """
    expr = (body.get("expression") or "").strip()
    if not expr:
        return {"valid": False, "error": "表达式不能为空"}

    import re

    # 1. 检查字段
    field_pattern = r'\$[a-zA-Z_]+'
    found_fields = set(re.findall(field_pattern, expr))
    invalid_fields = found_fields - _VALID_FIELDS
    if invalid_fields:
        return {"valid": False, "error": f"无效字段: {', '.join(invalid_fields)}",
                "error_type": "field"}

    # 2. 检查函数
    func_pattern = r'\b([A-Z][a-zA-Z]*)\s*\('
    found_funcs = re.findall(func_pattern, expr)
    invalid_funcs = [f for f in found_funcs if f not in _VALID_FUNCTIONS]
    if invalid_funcs:
        return {"valid": False, "error": f"无效函数: {', '.join(invalid_funcs)}",
                "error_type": "function"}

    # 3. 检查除零保护
    if "/" in expr:
        div_parts = expr.split("/")
        for part in div_parts[1:]:
            part = part.strip()
            if part.startswith("("):
                continue
            if "1e-12" not in part and not any(part.startswith(f + "(") for f in _VALID_FUNCTIONS):
                return {"valid": False,
                        "error": "除法运算缺少除零保护，建议分母添加 +1e-12",
                        "error_type": "math"}

    # 4. 复杂度
    func_count = len(found_funcs)
    nesting = max((expr[:i].count("(") - expr[:i].count(")") for i in range(len(expr))), default=0)
    if func_count <= 2 and nesting <= 1:
        complexity = "简单"
    elif func_count <= 5 and nesting <= 2:
        complexity = "中等"
    else:
        complexity = "复杂"

    return {"valid": True, "fields": sorted(found_fields),
            "functions": found_funcs, "complexity": complexity}


# ═══════════════════════════════════════════════════════════════
#  因子退场评估 — 源自 multi-factor-stock-selection
# ═══════════════════════════════════════════════════════════════

@router.post("/factor-retirement")
def check_factor_retirement(body: dict):
    """
    因子退场评估

    请求体:
      {"factors": {"PE": [0.5, 0.4, 0.1, 0.05, 0.02], "ROE": [0.6, 0.2, 0.5, ...]}}

    返回:
      - retired: 退场因子 (连续3月ICIR<0.3)
      - warned: 警告因子 (连续1-2月不达标)
      - healthy: 健康因子
      - registry_updated: 更新后的注册表统计
    """
    from services.factor_service import apply_factor_retirement

    factors = body.get("factors", {})
    if not factors:
        return {"error": "请提供因子ICIR历史数据: {\"factors\": {\"factor_name\": [icir_values...]}}"}

    result = apply_factor_retirement(factors)
    return result
