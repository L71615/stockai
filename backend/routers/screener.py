"""选股系统 API：多因子筛选 / 策略回测 / AI盯盘

流程: 全市场扫描 → AI二次筛选 → 策略回测 → 加盯盘 → AI盯盘简报
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from database import query_all, query_one, execute
from dependencies import get_current_user_id
from services.rate_limit import limiter_ai

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screener", tags=["Screener"])


# ═══════════════════════════════════════════════════════════
# 请求体
# ═══════════════════════════════════════════════════════════

class ScreenerRequest(BaseModel):
    stock_count: int = 500          # 扫描股票数量：500=沪深300+中证500, 0=全A股
    max_workers: int = 3            # 并发线程数（不宜过高，Baostock 有全局锁）
    industry_neutral: bool = True   # 是否行业中性化
    allowed_boards: list[str] = []  # 允许的板块，空=默认沪深主板。可选: main_sh, main_sz, gem, star, bse


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

        boards = set(body.allowed_boards) if body.allowed_boards else None
        result = _run_screener(stock_list, max_workers=body.max_workers, progress_callback=progress_cb, allowed_boards=boards)

        if body.industry_neutral and "error" not in result:
            result["candidates"] = industry_neutralize(result["candidates"])

        # 保存结果到数据库
        try:
            execute(
                """INSERT INTO screener_results (user_id, total_stocks, scanned, candidates_json, factor_weights_json, market_state)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (get_current_user_id(), result.get("total_stocks", 0), result.get("scanned", 0),
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
        candidates = _attach_factor_warnings(candidates)
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

    candidates = json.loads(row.get("candidates_json", "[]"))[:limit]
    candidates = _attach_factor_warnings(candidates)
    return {
        "from_cache": True,
        "created_at": row["created_at"],
        "market_state": row["market_state"],
        "total_stocks": row["total_stocks"],
        "scanned": row["scanned"],
        "factor_weights": json.loads(row.get("factor_weights_json", "{}")),
        "candidates": candidates,
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
    from services.ai_exceptions import AIServiceError

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
            function="screener",
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

    except AIServiceError as e:
        raise HTTPException(503, f"AI筛选失败: {e}")
    except Exception as e:
        raise HTTPException(500, f"AI筛选失败: {e}")


# ═══════════════════════════════════════════════════════════
# 策略回测
# ═══════════════════════════════════════════════════════════

@router.get("/strategies")
def list_strategies():
    """列出所有可用策略（仅 YAML 策略模板）"""
    yaml_strategies = _list_strategies()
    for s in yaml_strategies:
        s["type"] = "condition"
    return {"strategies": yaml_strategies}


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
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (get_current_user_id(), body.code, body.strategy,
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
            "SELECT * FROM backtest_results WHERE user_id = ? AND stock_code = ? ORDER BY id DESC LIMIT ?",
            (get_current_user_id(), code, limit),
        )
    return query_all(
        "SELECT * FROM backtest_results WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (get_current_user_id(), limit),
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
            "SELECT * FROM screener_alerts WHERE user_id = ? AND severity = ? ORDER BY id DESC LIMIT ?",
            (get_current_user_id(), severity, limit),
        )
    return query_all(
        "SELECT * FROM screener_alerts WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (get_current_user_id(), limit),
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
                波动率因子/量价因子/基本面因子/情绪因子/资金因子)
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


# ══════════════════════════════════════════════════════════════════
# 条件选股 & 策略系统
# ══════════════════════════════════════════════════════════════════

_STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"


def _load_strategy_yaml(strategy_id: str) -> dict | None:
    """从 YAML 文件加载策略定义

    YAML 中 conditions 存储为列表，需要包装为 condition_engine 期望的
    {"logic": "AND", "conditions": [...]} 格式。
    """
    try:
        import yaml
    except ImportError:
        return None
    fpath = _STRATEGIES_DIR / f"{strategy_id}.yaml"
    if not fpath.exists():
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # YAML conditions 是裸列表 → 包装为条件树字典
    if isinstance(data.get("conditions"), list):
        data["conditions"] = {"logic": "AND", "conditions": data["conditions"]}
    return data


def _list_strategies() -> list[dict]:
    """列出所有可用策略模板"""
    if not _STRATEGIES_DIR.exists():
        return []
    strategies = []
    for fpath in sorted(_STRATEGIES_DIR.glob("*.yaml")):
        try:
            import yaml
            with open(fpath, "r", encoding="utf-8") as f:
                s = yaml.safe_load(f)
                strategies.append({
                    "id": s.get("id", fpath.stem),
                    "name": s.get("name", fpath.stem),
                    "description": s.get("description", ""),
                    "market_state": s.get("market_state", []),
                    "recommended_position": s.get("recommended_position", ""),
                    "condition_count": len(s.get("conditions", [])),
                })
        except Exception:
            pass
    return strategies


@router.get("/strategies/{strategy_id}")
def get_strategy_detail(strategy_id: str):
    """获取单个策略的完整定义（含条件列表）"""
    data = _load_strategy_yaml(strategy_id)
    if data:
        return {"found": True, "strategy": data}
    # 旧格式回退
    return {"found": False, "error": f"策略 {strategy_id} 不存在"}


# ── 条件 Schema ──

CONDITION_SCHEMA = [
    # L1: 股票列表（零成本）
    {"key": "industry", "label": "行业", "type": "select", "category": "layer1_stocklist",
     "operators": ["in_list", "not_in_list"]},
    # L2: 实时行情（批量HTTP，极低成本）
    {"key": "price", "label": "股价", "type": "range", "category": "layer2_quote",
     "operators": ["between"], "unit": "元"},
    # L3: 基本面（逐个HTTP + Baostock兜底）
    {"key": "pe", "label": "PE (TTM)", "type": "range", "category": "layer3_fundamental",
     "operators": ["between", "<", ">"]},
    {"key": "pb", "label": "PB", "type": "range", "category": "layer3_fundamental",
     "operators": ["between", "<", ">"]},
    {"key": "roe", "label": "ROE (%)", "type": "number", "category": "layer3_fundamental",
     "operators": [">=", "<="]},
    {"key": "dividend_yield", "label": "股息率 (%)", "type": "number", "category": "layer3_fundamental",
     "operators": [">=", "<="]},
    {"key": "debt_ratio", "label": "资产负债率 (%)", "type": "number", "category": "layer3_fundamental",
     "operators": ["<=", ">="]},
    {"key": "market_cap", "label": "市值", "type": "range", "category": "layer3_fundamental",
     "operators": ["between"], "unit": "亿"},
    # L4: K线+技术指标（逐个HTTP+本地计算）
    {"key": "ma5_vs_ma10", "label": "MA5 vs MA10", "type": "cross", "category": "layer4_kline",
     "operators": ["cross_above", "cross_below", ">", "<"],
     "compare_field": "ma10"},
    {"key": "close_vs_ma20", "label": "收盘价 vs MA20", "type": "compare", "category": "layer4_kline",
     "operators": [">", "<"],
     "compare_field": "ma20"},
    {"key": "close_vs_ma60", "label": "收盘价 vs MA60", "type": "compare", "category": "layer4_kline",
     "operators": [">", "<"],
     "compare_field": "ma60"},
    {"key": "close_vs_high_20d", "label": "收盘价 vs 20日高点", "type": "cross", "category": "layer4_kline",
     "operators": [">", "cross_above"],
     "compare_field": "high_20d"},
    {"key": "close_vs_high_55d", "label": "收盘价 vs 55日高点", "type": "cross", "category": "layer4_kline",
     "operators": [">", "cross_above"],
     "compare_field": "high_55d"},
    {"key": "close_vs_low_5d", "label": "收盘价 vs 5日低点", "type": "compare", "category": "layer4_kline",
     "operators": [">="],
     "compare_field": "low_5d"},
    {"key": "rsi_14", "label": "RSI (14)", "type": "range", "category": "layer4_kline",
     "operators": ["between"]},
    {"key": "macd_dif_dea", "label": "MACD DIF vs DEA", "type": "cross", "category": "layer4_kline",
     "operators": ["cross_above", "cross_below"],
     "compare_field": "dea"},
    {"key": "vol_ratio", "label": "量比", "type": "number", "category": "layer4_kline",
     "operators": [">=", "<="]},
    {"key": "boll_position", "label": "布林带位置", "type": "range", "category": "layer4_kline",
     "operators": ["between"], "unit": "0=下轨 1=上轨"},
    {"key": "ret_5d", "label": "5日涨幅 (%)", "type": "range", "category": "layer4_kline",
     "operators": ["between", ">=", "<="]},
    {"key": "ret_20d", "label": "20日涨幅 (%)", "type": "range", "category": "layer4_kline",
     "operators": ["between", ">=", "<="]},
    {"key": "atr_pct", "label": "ATR/收盘价 (%)", "type": "range", "category": "layer4_kline",
     "operators": ["between"], "unit": "%"},
    {"key": "strength_20d", "label": "20日相对强度", "type": "number", "category": "layer4_kline",
     "operators": [">=", "<="]},
    {"key": "avg_amount_20d", "label": "日均成交额", "type": "number", "category": "layer4_kline",
     "operators": [">=", "<="], "unit": "元"},
]


@router.get("/conditions/schema")
def get_condition_schema():
    """获取可用条件字段清单 + 操作符"""
    return {"fields": CONDITION_SCHEMA}


# ── 市场状态 ──

def _calc_market_state() -> dict:
    """计算当前 A 股市场状态（从本地 historical_kline，零外部调用）"""
    try:
        from database import query_all

        # 从本地日线获取上证指数数据
        rows = query_all(
            "SELECT close FROM historical_kline WHERE stock_code='000001' ORDER BY trade_date DESC LIMIT 120"
        )
        closes = [float(r["close"]) for r in reversed(rows) if r["close"]]

        if len(closes) < 60:
            return {"state": "unknown", "label": "数据不足", "position": "--"}

        # MA60
        ma60 = sum(closes[-60:]) / 60
        price = closes[-1]
        ma60_distance_pct = round((price / ma60 - 1) * 100, 2)

        # 涨跌比 — 从本地数据获取三大指数最近一天涨跌
        up_count, down_count = 0, 0
        for idx_code in ["000001", "399001", "399006"]:
            try:
                rows = query_all(
                    "SELECT close FROM historical_kline WHERE stock_code=? ORDER BY trade_date DESC LIMIT 2",
                    (idx_code,),
                )
                if len(rows) >= 2:
                    today = float(rows[0]["close"])
                    prev = float(rows[1]["close"])
                    if prev > 0:
                        chg = (today - prev) / prev * 100
                        if chg > 0: up_count += 1
                        elif chg < 0: down_count += 1
            except Exception:
                pass

        # 成交量判断（从本地数据）
        from database import query_all
        vol_rows = query_all(
            "SELECT volume FROM historical_kline WHERE stock_code='000001' ORDER BY trade_date DESC LIMIT 20"
        )
        volumes = [float(r["volume"]) for r in vol_rows if r["volume"]]
        vol_ratio = 1.0
        if len(volumes) >= 20:
            vol_ma = sum(volumes[1:]) / (len(volumes) - 1)
            vol_ratio = round(volumes[0] / vol_ma, 2) if vol_ma > 0 else 1.0

        # 状态判定
        bull_ratio = up_count / max(up_count + down_count, 1)
        if price > ma60 and bull_ratio > 0.55 and vol_ratio > 0.8:
            state, label, pos = "bull", "牛市", "60-90%"
        elif price > ma60 and bull_ratio >= 0.4:
            state, label, pos = "bull", "偏强", "50-70%"
        elif abs(ma60_distance_pct) <= 3:
            state, label, pos = "range", "震荡", "30-50%"
        elif price < ma60 and bull_ratio < 0.4:
            state, label, pos = "bear", "熊市", "10-30%"
        else:
            state, label, pos = "range", "震荡偏弱", "20-40%"

        # 推荐策略
        rec_strategies = {
            "bull": ["turtle_s1", "ma_bullish", "momentum_leader"],
            "range": ["boll_mean", "high_div", "turtle_s1"],
            "bear": ["high_div", "oversold_bounce", "deep_value"],
        }

        return {
            "state": state,
            "label": label,
            "position": pos,
            "ma60_distance_pct": ma60_distance_pct,
            "vol_ratio": vol_ratio,
            "recommended_strategies": rec_strategies.get(state, []),
            "price": price,
            "ma60": round(ma60, 2),
        }
    except Exception:
        return {"state": "unknown", "label": "计算失败", "position": "--"}


@router.get("/market-state")
def get_market_state():
    """获取当前市场状态 + 推荐策略"""
    return _calc_market_state()


# ── 条件扫描 ──

class ConditionScanRequest(BaseModel):
    conditions: dict       # 条件树 {"logic": "AND", "conditions": [...]}
    sort_by: str = ""      # 排序字段
    sort_order: str = "desc"
    stock_pool: str = "all"  # "all" | "hs300" | "zz500" | "custom"
    stock_codes: list[str] = []
    max_results: int = 50


def _attach_factor_warnings(candidates: list[dict]) -> list[dict]:
    """给候选股票附加因子健康警告

    从 factor_lifecycle_status 读取因子状态 (active / warning / retired),
    把候选 top_factors 里的 retired/warning 因子作为警告附加到 candidate。
    用途: 让用户在选股页面看到"该候选涉及的关键因子是否在衰减"。
    """
    # 一次性查所有 lifecycle 状态
    try:
        rows = query_all("SELECT factor_name, status, warning_days, ir_current FROM factor_lifecycle_status")
        lifecycle = {r["factor_name"]: dict(r) for r in rows}
    except Exception:
        lifecycle = {}

    if not lifecycle:
        return candidates

    STATUS_LABELS = {
        "retired": ("已退役", "red"),
        "warning": ("信号弱", "yellow"),
        "active": ("活跃", "green"),
    }

    for cand in candidates:
        warnings = []
        for tf in cand.get("top_factors") or []:
            fn = tf.get("factor") if isinstance(tf, dict) else tf
            if not fn or fn not in lifecycle:
                continue
            st = lifecycle[fn].get("status", "active")
            if st in ("retired", "warning"):
                label, _color = STATUS_LABELS.get(st, (st, ""))
                warnings.append({
                    "factor": fn,
                    "status": st,
                    "label": label,
                    "warning_days": lifecycle[fn].get("warning_days", 0),
                    "ir_current": lifecycle[fn].get("ir_current"),
                })
        cand["factor_warnings"] = warnings
        cand["has_critical_warnings"] = any(w["status"] == "retired" for w in warnings)

    return candidates


def _lookup_stock_name(code: str) -> str:
    """从本地数据源查找股票名称"""
    row = query_one(
        "SELECT raw_payload FROM futu_raw_quote WHERE code = ? ORDER BY quote_time DESC LIMIT 1",
        (code,),
    )
    if row:
        try:
            payload = json.loads(row["raw_payload"])
            name = payload.get("name", "")
            if name:
                return name
        except Exception:
            pass
    return ""


@router.post("/conditions/scan")
def condition_scan(body: ConditionScanRequest):
    """两阶段条件扫描：Phase1 行情快筛(全市场) - Phase2 K线精筛(候选集)"""
    conditions = body.conditions

    # ── 四层字段分类（按数据获取成本从低到高）──
    LAYER1_FIELDS = {"industry"}                           # 股票列表缓存（零成本）
    LAYER2_FIELDS = {"price"}                              # 实时行情（批量HTTP，极低）
    LAYER3_FIELDS = {"pe", "pb", "roe", "dividend_yield",  # 基本面（逐个HTTP，中等）
                     "debt_ratio", "market_cap"}
    LAYER4_FIELDS = {                                      # K线+技术指标（逐个HTTP+计算，最重）
        "close", "open", "high", "low",
        "ma5", "ma10", "ma20", "ma60",
        "ma5_vs_ma10", "close_vs_ma20", "close_vs_ma60",
        "close_vs_high_20d", "close_vs_high_55d", "close_vs_low_5d",
        "rsi_14", "macd_dif_dea", "vol_ratio", "boll_position",
        "ret_5d", "ret_20d", "atr_pct", "strength_20d",
        "avg_amount_20d",
        "high_20d", "high_55d", "low_5d", "dea", "dif",
    }

    def _layer_of(field: str) -> int:
        """返回字段所属层 (1-4)，未知字段默认 L4（安全）"""
        if field in LAYER1_FIELDS: return 1
        if field in LAYER2_FIELDS: return 2
        if field in LAYER3_FIELDS: return 3
        if field in LAYER4_FIELDS: return 4
        return 4  # 未知字段默认L4

    def classify_conditions(tree: dict) -> dict:
        """将条件树按层级拆分为四棵子树，同时检查 field 和 compare_field"""
        layers: dict[int, list] = {1: [], 2: [], 3: [], 4: []}

        def _walk(subtree: dict):
            for cond in subtree.get("conditions", []):
                if "conditions" in cond:
                    _walk(cond)
                else:
                    field = cond.get("field", "")
                    cf = cond.get("compare_field", "")
                    max_l = max(_layer_of(field), _layer_of(cf) if cf else 0)
                    layers[max_l].append(cond)

        _walk(tree)
        return {lid: {"logic": "AND", "conditions": layers[lid]} for lid in (1, 2, 3, 4)}

    layer_trees = classify_conditions(conditions)

    # 构建流水线：跳过空层
    pipeline = [(lid, layer_trees[lid]) for lid in (1, 2, 3, 4)
                if layer_trees[lid]["conditions"]]
    if not pipeline:
        return {"total_scanned": 0, "matched_count": 0,
                "conditions": conditions, "results": []}

    from services.condition_engine import evaluate
    from services.screener_service import get_all_stock_list
    from services.technical import calc_ma, calc_rsi, calc_macd
    from services.factor_service import factor_ret_5d, factor_ret_20d, factor_atr
    from services.akshare_adapter import get_stock_factors_http, get_batch_quotes
    from services.technical import fetch_kline as fetch_kline_fast
    from services.utils import detect_asset_type
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # ═══════════════════════════════════════════════════════════
    # L1: 股票列表过滤（内存缓存，零成本）
    # ═══════════════════════════════════════════════════════════
    stock_list = get_all_stock_list(force_refresh=False)
    if body.stock_codes:
        code_set = set(body.stock_codes)
        stock_list = [s for s in stock_list if s["code"] in code_set]

    total_full = len(stock_list)
    MAX_SCAN = 1000
    if len(stock_list) > MAX_SCAN:
        stock_list = stock_list[:MAX_SCAN]

    survivors = []
    for s in stock_list:
        at = detect_asset_type(s["code"])
        if at not in ("stock", "etf"):
            continue
        sd = {"industry": s.get("industry", "")}
        if layer_trees[1]["conditions"] and not evaluate(sd, layer_trees[1]):
            continue
        survivors.append((s, sd))

    l1_passed = len(survivors)
    if not survivors:
        return {"total_scanned": total_full, "l1_passed": l1_passed,
                "matched_count": 0, "conditions": conditions, "results": []}

    # ═══════════════════════════════════════════════════════════
    # L2: 实时行情过滤（腾讯批量HTTP，极低成本）
    # ═══════════════════════════════════════════════════════════
    codes = [s[0]["code"] for s in survivors]
    quotes = get_batch_quotes(codes)
    filtered = []
    for s, sd in survivors:
        code = s["code"]
        quote = quotes.get(code)
        if not quote or not quote.get("price"):
            continue
        price = quote.get("price", 0)
        sd["price"] = price
        sd["close"] = price  # alias，兼容 L4 条件
        if layer_trees[2]["conditions"] and not evaluate(sd, layer_trees[2]):
            continue
        filtered.append((s, quote, sd))
    survivors = filtered

    l2_passed = len(survivors)
    if not survivors:
        return {"total_scanned": total_full, "l1_passed": l1_passed,
                "l2_passed": l2_passed, "matched_count": 0,
                "conditions": conditions, "results": []}

    l3_passed = len(survivors)  # 默认值，L3 block 内可能被覆盖
    l3_warning = ""             # L3 截断警告

    # ═══════════════════════════════════════════════════════════
    # L3: 基本面过滤（两阶段：AKShare 快筛 → Baostock 精筛）
    # ═══════════════════════════════════════════════════════════
    if layer_trees[3]["conditions"]:
        # ── 拆分为 L3a (AKShare) 和 L3b (Baostock) ──
        _BS_FIELDS = {"dividend_yield", "debt_ratio", "market_cap"}
        l3a_conds = [c for c in layer_trees[3]["conditions"]
                     if c.get("field") not in _BS_FIELDS and c.get("compare_field", "") not in _BS_FIELDS]
        l3b_conds = [c for c in layer_trees[3]["conditions"]
                     if c.get("field") in _BS_FIELDS or c.get("compare_field", "") in _BS_FIELDS]

        l3_tree = layer_trees[3]
        l3a_tree = {"logic": l3_tree["logic"], "conditions": l3a_conds}

        # 候选上限保护，避免扫描超时（5并发≈60s/300只）
        _L3_MAX_CANDIDATES = 2000
        l3_warning = ""
        if l3a_conds and len(survivors) > _L3_MAX_CANDIDATES:
            l3_warning = f"L3候选过多 ({len(survivors)} 只)，已自动截取前 {_L3_MAX_CANDIDATES} 只。建议添加行业或价格条件缩小范围。"
            logger.warning("L3 auto-cap: %d survivors > %d, truncating", len(survivors), _L3_MAX_CANDIDATES)
            survivors = survivors[:_L3_MAX_CANDIDATES]

        # ── L3a: AKShare HTTP（PE/PB/ROE），并发快速缩池 ──
        if l3a_conds:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _process_l3a(item):
                s, quote, sd = item
                code = s["code"]
                price = sd["price"]
                try:
                    fin = get_stock_factors_http(code)
                    if fin:
                        eps = fin.get("eps")
                        bvps = fin.get("bvps")
                        sd["eps"] = eps
                        sd["roe"] = fin.get("roe")
                        if price and eps and eps > 0:
                            sd["pe"] = round(price / eps, 2)
                        if price and bvps and bvps > 0:
                            sd["pb"] = round(price / bvps, 4)
                except Exception:
                    pass
                if not evaluate(sd, l3a_tree):
                    return None
                return (s, quote, sd)

            filtered = []
            with ThreadPoolExecutor(max_workers=5) as _l3a_pool:
                _futures = {_l3a_pool.submit(_process_l3a, item): item for item in survivors}
                for _f in as_completed(_futures):
                    try:
                        result = _f.result()
                        if result is not None:
                            filtered.append(result)
                    except Exception:
                        pass
            survivors = filtered

        l3a_passed = len(survivors)

        # ── L3b: Baostock（dividend_yield / debt_ratio / market_cap），仅缩池后启用 ──
        if l3b_conds and survivors:
            _BS_MAX = 200
            if len(survivors) < _BS_MAX:
                from services.baostock_adapter import get_stock_factors as _bs
                filtered = []
                for s, quote, sd in survivors:
                    code = s["code"]
                    price = sd["price"]
                    try:
                        bs = _bs(code)
                        if bs and "error" not in bs:
                            if "dividend" in bs and price and price > 0:
                                sd["dividend_yield"] = round(bs["dividend"] / price * 100, 4)
                            if "debt_ratio" in bs:
                                sd["debt_ratio"] = bs["debt_ratio"]
                            if "market_cap" in bs:
                                sd["market_cap"] = round(bs.get("market_cap", 0) / 1e8, 2)
                    except Exception:
                        pass
                    if not evaluate(sd, {"logic": "AND", "conditions": l3b_conds}):
                        continue
                    filtered.append((s, quote, sd))
                survivors = filtered
            else:
                logger.warning(
                    "L3b Baostock skipped: %d candidates > %d. "
                    "Add PE/price conditions first to use dividend_yield/debt_ratio/market_cap.",
                    len(survivors), _BS_MAX
                )
                # Baostock 字段留为 None → evaluate 中全部淘汰
                filtered = []
                for s, quote, sd in survivors:
                    if not evaluate(sd, {"logic": "AND", "conditions": l3b_conds}):
                        continue
                    filtered.append((s, quote, sd))
                survivors = filtered

    l3_passed = len(survivors)
    if not survivors and layer_trees[3]["conditions"]:
        return {"total_scanned": total_full, "l1_passed": l1_passed,
                "l2_passed": l2_passed, "l3_passed": l3_passed,
                "matched_count": 0, "conditions": conditions, "results": []}

    l4_warning = ""  # L4 截断警告

    # ═══════════════════════════════════════════════════════════
    # L4: K线+技术指标（逐个HTTP+并行计算，最重）
    # ═══════════════════════════════════════════════════════════
    def _process_l4(item):
        s, quote, sd = item
        code = s["code"]
        price = sd.get("price", 0)
        try:
            kline = fetch_kline_fast(code, days=60)
            if "error" in kline:
                return None
        except Exception:
            return None

        closes = kline.get("closes", [])
        highs = kline.get("highs", [])
        lows = kline.get("lows", [])
        volumes = kline.get("volumes", [])
        opens_list = kline.get("opens", [])
        if len(closes) < 60:
            return None

        # MA 均线
        ma = calc_ma(closes, [5, 10, 20, 60])
        for k in ["MA5", "MA10", "MA20", "MA60"]:
            seq = ma.get(k, [])
            key = k.lower()
            sd[key + "_seq"] = seq
            sd[key] = ([v for v in seq if v is not None] or [None])[-1]

        # Close / Open / High / Low
        if closes:
            sd["close"] = closes[-1]
        if opens_list:
            sd["open"] = opens_list[-1]
        if highs:
            sd["high"] = highs[-1]
        if lows:
            sd["low"] = lows[-1]

        # 高/低点参考
        if len(highs) >= 21:
            sd["high_20d"] = max(highs[-21:-1])
        if len(highs) >= 56:
            sd["high_55d"] = max(highs[-56:-1])
        if len(lows) >= 6:
            sd["low_5d"] = min(lows[-6:-1])

        # RSI
        sd["rsi_14_seq"] = calc_rsi(closes, 14)
        sd["rsi_14"] = ([v for v in sd["rsi_14_seq"] if v is not None] or [None])[-1]

        # MACD
        macd_data = calc_macd(closes)
        sd["dif_seq"] = macd_data.get("DIF", [])
        sd["dea_seq"] = macd_data.get("DEA", [])

        # 量比 + 日均成交额
        if volumes and len(volumes) >= 20:
            valid_v = [v for v in volumes[-21:-1] if v is not None]
            vm = sum(valid_v) / len(valid_v) if valid_v else 0
            sd["vol_ratio"] = round(volumes[-1] / vm, 2) if vm > 0 and volumes[-1] is not None else 1.0
            amounts = []
            for i in range(min(len(volumes), len(closes))):
                v = volumes[i]
                c = closes[i]
                if v is not None and c is not None:
                    amounts.append(v * c)
            sd["avg_amount_20d"] = sum(amounts[-20:]) / min(len(amounts), 20) if amounts else 0
        else:
            sd["vol_ratio"] = 1.0
            sd["avg_amount_20d"] = 0

        # 布林带
        if len(closes) >= 20:
            bb_ma = sum(closes[-20:]) / 20
            bb_std = (sum((c - bb_ma) ** 2 for c in closes[-20:]) / 20) ** 0.5
            bb_upper, bb_lower = bb_ma + 2 * bb_std, bb_ma - 2 * bb_std
            sd["boll_position"] = round((price - bb_lower) / (bb_upper - bb_lower), 3) if bb_upper != bb_lower else 0.5
        else:
            sd["boll_position"] = 0.5

        # 动量因子（转为百分比，匹配YAML策略）
        r5 = factor_ret_5d(closes)
        r20 = factor_ret_20d(closes)
        sd["ret_5d"] = round(r5 * 100, 2) if r5 is not None else None
        sd["ret_20d"] = round(r20 * 100, 2) if r20 is not None else None

        # ATR / 相对强度
        atr_val = factor_atr(highs, lows, closes, 20)
        sd["atr_pct"] = round(atr_val / price * 100, 2) if atr_val and price > 0 else None
        sd["strength_20d"] = round((price / closes[-20] - 1) * 100, 2) if len(closes) >= 20 and closes[-20] > 0 else None

        if evaluate(sd, layer_trees[4]):
            return {
                "code": code, "name": s.get("name") or quote.get("name") or _lookup_stock_name(code),
                "industry": s.get("industry", ""),
                "price": round(price, 2), "change_pct": round(quote.get("change_pct", 0) or 0, 2),
                "pe": sd.get("pe"), "pb": sd.get("pb"), "roe": sd.get("roe"),
                "rsi_14": sd.get("rsi_14"), "vol_ratio": sd.get("vol_ratio"),
                "avg_amount": sd.get("avg_amount_20d"),
                "boll_position": sd.get("boll_position"),
                "ret_5d": sd.get("ret_5d"), "ret_20d": sd.get("ret_20d"),
                "atr_pct": sd.get("atr_pct"),
            }
        return None

    if layer_trees[4]["conditions"] and survivors:
        _L4_MAX = 500
        l4_warning = ""
        if len(survivors) > _L4_MAX:
            l4_warning = f"候选股过多 ({len(survivors)} 只)，已自动截取前 {_L4_MAX} 只。建议添加行业或价格条件缩小范围。"
            logger.warning("L4 auto-cap: %d survivors > %d, truncating", len(survivors), _L4_MAX)
            survivors = survivors[:_L4_MAX]
        results = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_process_l4, item): item for item in survivors}
            for fut in as_completed(futures):
                res = fut.result()
                if res:
                    results.append(res)
    else:
        # 无 L4 条件：直接返回 survivor 数据
        results = [{
            "code": s["code"], "name": s.get("name", quote.get("name", "")),
            "industry": s.get("industry", ""),
            "price": round(sd["price"], 2),
            "change_pct": round(quote.get("change_pct", 0) or 0, 2),
            "pe": sd.get("pe"), "pb": sd.get("pb"), "roe": sd.get("roe"),
        } for s, quote, sd in survivors]

    sort_key = body.sort_by or "price"
    reverse = body.sort_order != "asc"
    try:
        results.sort(key=lambda r: r.get(sort_key) or 0, reverse=reverse)
    except Exception:
        pass

    warning = " ".join(filter(None, [l3_warning, l4_warning])).strip()

    return {
        "total_scanned": total_full,
        "l1_passed": l1_passed,
        "l2_passed": l2_passed,
        "l3_passed": l3_passed,
        "matched_count": len(results),
        "conditions": conditions,
        "results": results[:body.max_results],
        "warning": warning or None,
    }


# ── 用户保存的策略 ──

class SaveScreenRequest(BaseModel):
    name: str
    description: str = ""
    conditions: dict
    sort_by: str = ""
    sort_order: str = "desc"


@router.get("/screens")
def list_screens():
    """列出用户保存的条件选股策略"""
    rows = query_all(
        "SELECT id, name, description, sort_by, sort_order, created_at, updated_at FROM condition_screens WHERE user_id = ? ORDER BY updated_at DESC",
        (get_current_user_id(),),
    )
    return [dict(r) for r in rows]


@router.post("/screens")
def save_screen(body: SaveScreenRequest):
    """保存新的条件选股策略"""
    import json as _json
    result = execute(
        "INSERT INTO condition_screens (user_id, name, description, conditions_json, sort_by, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
        (get_current_user_id(), body.name, body.description, _json.dumps(body.conditions, ensure_ascii=False), body.sort_by, body.sort_order),
    )
    return {"id": result["lastrowid"], "message": "保存成功"}


@router.put("/screens/{screen_id}")
def update_screen(screen_id: int, body: SaveScreenRequest):
    """更新保存的策略"""
    import json as _json
    row = query_one("SELECT id FROM condition_screens WHERE id = ? AND user_id = ?", (screen_id, get_current_user_id()))
    if not row:
        raise HTTPException(404, "策略不存在")
    execute(
        "UPDATE condition_screens SET name=?, description=?, conditions_json=?, sort_by=?, sort_order=?, updated_at=datetime('now','localtime') WHERE id=?",
        (body.name, body.description, _json.dumps(body.conditions, ensure_ascii=False), body.sort_by, body.sort_order, screen_id),
    )
    return {"message": "更新成功"}


@router.delete("/screens/{screen_id}")
def delete_screen(screen_id: int):
    """删除保存的策略"""
    execute("DELETE FROM condition_screens WHERE id = ? AND user_id = ?", (screen_id, get_current_user_id()))
    return {"message": "已删除"}
