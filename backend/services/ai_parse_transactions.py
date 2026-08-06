"""v5.1 — AI 批量解析交易文本

从用户粘贴的自由文本/CSV 中抽取结构化交易记录。

设计:
  - 输入: 多行文本,每行一笔交易 (支持 CSV 模板 + 自然语言混排)
  - AI:   Claude Haiku 4.5 + function calling 强制结构化输出
  - 校验: 股票代码必须在 stocks 表 + 卖出 ≤ 当前持仓
  - 输出: {transactions: [...], errors: [...]}
         不直接写库, 用户确认后才入库 (两阶段流程)

模板:
  代码,方向,数量,价格,日期
  600519,买入,100,1680.00,2026-08-06
  000725,卖出,500,4.20,2026-08-06
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from database import query_all, query_one
from services.ai_exceptions import AIServiceError

logger = logging.getLogger(__name__)

# ── 限制 ──
MAX_INPUT_CHARS = 4000          # 单次粘贴上限
MAX_TRANSACTIONS = 50           # 单批上限
MAX_BATCH_CHARS_PER_LINE = 200  # 单行长度上限

# ── 模板(给前端展示用,实际解析靠 AI) ──
TEMPLATE = """代码,方向,数量,价格,日期
600519,买入,100,1680.00,2026-08-06
000725,卖出,500,4.20,2026-08-06"""


@dataclass
class ParsedTransaction:
    code: str
    direction: str       # "buy" / "sell"
    quantity: int
    price: float
    date: str            # YYYY-MM-DD
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "direction": self.direction,
            "quantity": self.quantity,
            "price": self.price,
            "date": self.date,
            "note": self.note,
        }


@dataclass
class ParseError:
    line: int             # 行号 (从 1 开始)
    raw: str              # 原始文本
    reason: str           # 错误原因

    def to_dict(self) -> dict:
        return {"line": self.line, "raw": self.raw, "reason": self.reason}


# ── 预校验(不调 AI, 快路径) ──


def _pre_clean_lines(text: str) -> list[str]:
    """过滤空行 / 注释行 / 模板表头"""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        # 跳过表头(第一列是"代码"或"code")
        lower = s.lower()
        if lower.startswith("代码,") or lower.startswith("code,"):
            continue
        lines.append(s)
    return lines


# ── AI 解析(主路径) ──


# OpenAI / Claude 通用 tools schema (JSON mode 可靠)
_PARSE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_transactions",
        "description": "Submit the parsed stock transactions extracted from user text.",
        "parameters": {
            "type": "object",
            "properties": {
                "transactions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "6-digit stock code"},
                            "direction": {"type": "string", "enum": ["buy", "sell"], "description": "买入→buy, 卖出→sell"},
                            "quantity": {"type": "integer", "description": "正整数股数"},
                            "price": {"type": "number", "description": "正数价格(元)"},
                            "date": {"type": "string", "description": "YYYY-MM-DD 格式日期"},
                        },
                        "required": ["code", "direction", "quantity", "price", "date"],
                    },
                },
            },
            "required": ["transactions"],
        },
    },
}


_PARSE_SYSTEM_PROMPT = """你是股票交易记录解析助手. 从用户粘贴的中文/英文文本中抽取每笔交易.

**核心原则**: 每行一笔交易, 一行都不漏. 宁可多解析也不要少解析.

输出格式: 调用 `submit_transactions` 工具, 参数 `transactions` 是数组.

规则:
1. **代码**: 6位数字股票代码. 可能前后有股票名(如 "北投科技 600936"), 取6位数字.
2. **方向**: 买入/buy/Buy/BUY/买了/买进 → "buy"; 卖出/sell/Sell/SOLD/卖了/卖 → "sell"
3. **数量**: 正整数, "100股" → 100, "1手" → 100 (A 股 1 手 = 100 股). 单位词前是数量.
4. **价格**: 正小数, "@6.030" "6.030元" "价格6.030" → 6.030. 单位词后或@前通常是价格.
5. **日期**: YYYY-MM-DD 格式; "今天"→{today}; "昨天"→{yesterday}; 默认今天
   - 含时间部分 ("2026-08-05 13:18:26") → 只取日期部分 "2026-08-05"
6. **跳过**: 空行 / `#` 注释行 / 模板表头(代码,方向,数量,价格,日期)
7. **不去重**: 每笔交易保留独立行(即便是同代码同日), 用户可在预览界面手动删除重复
8. **模糊时**: 只要能从一行识别出 [代码, 方向, 数量, 价格, 日期] 就解析. 不确定的才跳过.

常见格式 (顺序灵活):
- "北投科技 600936 买入 6.030 300股 2026-08-05 13:18:26" → buy, 600936, 6.03, 300, 2026-08-05
- "今天买了600519 100股 价格1680" → buy, 600519, 1680.0, 100, {today}
- "000725,卖出,500,4.20,2026-08-06" → sell, 000725, 4.20, 500, 2026-08-06
- "买了 1手 平安银行 @12.5" → buy, 000001(平安银行), 12.5, 100, {today}
- "600519 100@1680 buy" → buy, 600519, 1680.0, 100, {today}

示例输出 → submit_transactions(transactions=[
  {{code:"600936", direction:"buy", quantity:300, price:6.030, date:"2026-08-05"}},
  {{code:"600936", direction:"buy", quantity:200, price:6.000, date:"2026-08-05"}},
  {{code:"600936", direction:"sell", quantity:200, price:5.900, date:"2026-08-06"}},
])"""


async def parse_transactions_with_ai(text: str, user_id: int) -> dict:
    """主入口 — AI 批量解析交易文本

    Returns:
        {
            "transactions": [ParsedTransaction, ...],
            "errors": [ParseError, ...],
            "summary": {"input_lines": int, "parsed_ok": int, "parse_failed": int, "validation_failed": int},
        }
    """
    # 1. 输入长度校验
    if not text or not text.strip():
        return _empty_result("空文本")

    if len(text) > MAX_INPUT_CHARS:
        return _empty_result(f"输入超过 {MAX_INPUT_CHARS} 字符上限 (实际 {len(text)})")

    # 2. 清理(只过滤,不解析)
    cleaned_lines = _pre_clean_lines(text)
    if not cleaned_lines:
        return _empty_result("没有有效行 (空行/注释/只有表头)")

    if len(cleaned_lines) > MAX_TRANSACTIONS:
        return _empty_result(f"行数超过 {MAX_TRANSACTIONS} 上限 (实际 {len(cleaned_lines)} 行)")

    # 3. AI 解析
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                 .fromtimestamp(datetime.now().timestamp() - 86400)).strftime("%Y-%m-%d")
    system = _PARSE_SYSTEM_PROMPT.format(today=today, yesterday=yesterday)

    try:
        ai_transactions = await _call_ai_parse(text, system)
    except AIServiceError as e:
        logger.warning("AI 解析失败: %s", e)
        # 失败: 把所有行都标为错误
        return {
            "transactions": [],
            "errors": [
                ParseError(line=i + 1, raw=line, reason=f"AI 解析失败: {e}").to_dict()
                for i, line in enumerate(cleaned_lines)
            ],
            "summary": {
                "input_lines": len(cleaned_lines),
                "parsed_ok": 0,
                "parse_failed": len(cleaned_lines),
                "validation_failed": 0,
            },
        }

    # 4. 后置校验 — 股票代码 + 卖出持仓量(本批买入也算)
    # DEBUG: 打印 AI 实际返回(排查用)
    logger.info(
        "AI parse: input_lines=%d, ai_returned=%d, txs=%s",
        len(cleaned_lines), len(ai_transactions), ai_transactions,
    )

    validation_errors = _validate_ai_results(ai_transactions, user_id)

    # 按行号/索引精确剔除失败的(不能用 code 聚合, 否则一笔错会带掉该代码全部)
    failed_indices = {e.get("index") for e in validation_errors if "index" in e}
    final_transactions = [
        tx for i, tx in enumerate(ai_transactions)
        if i not in failed_indices
    ]
    # 错误信息里去掉 index 字段(给前端)
    final_errors = [
        {"line": e.get("line", 0), "raw": e.get("raw", ""), "reason": e["reason"]}
        for e in validation_errors
    ]

    return {
        "transactions": final_transactions,
        "errors": final_errors,
        "summary": {
            "input_lines": len(cleaned_lines),
            "parsed_ok": len(final_transactions),
            "parse_failed": 0,
            "validation_failed": len(final_errors),
        },
    }


def _empty_result(reason: str) -> dict:
    return {
        "transactions": [],
        "errors": [{"line": 0, "raw": "", "reason": reason}],
        "summary": {"input_lines": 0, "parsed_ok": 0, "parse_failed": 0, "validation_failed": 0},
    }


async def _call_ai_parse(text: str, system: str) -> list[dict]:
    """调 AI 服务, 返回 [{code, direction, quantity, price, date}, ...]"""
    from services.ai_service import ai_chat_with_tools

    messages = [{"role": "user", "content": f"请解析以下交易文本:\n\n```\n{text}\n```"}]

    # 用 chat function key, 走用户配置的默认供应商 (或 Claude Haiku)
    result = await ai_chat_with_tools(
        message=f"请解析以下交易文本:\n\n```\n{text}\n```",
        tools=[_PARSE_TOOL],
        function="chat",  # 复用 chat 配置
        system_prompt=system,
        max_iterations=1,  # 单轮工具调用即可
    )

    # 提取 submit_transactions 的工具调用结果
    for tc in result.get("tool_calls", []):
        if tc.get("name") == "submit_transactions":
            args = tc.get("arguments", {})
            return args.get("transactions", [])

    # 退化路径: AI 没调工具, 尝试从文本里 JSON.parse
    text_reply = result.get("text", "")
    if text_reply:
        # 找 ```json ... ``` 块
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text_reply, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # 找裸 JSON
        m = re.search(r"\[.*?\]", text_reply, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

    return []


# ── 后置校验 ──


def _validate_ai_results(transactions: list[dict], user_id: int) -> list[dict]:
    """校验 AI 返回的交易: 股票代码存在 + 卖出 ≤ (当前持仓 + 本批总买入)

    顺序无关 — AI 可能把卖出放在买入前面, 我们用 batch 总和判断

    Returns:
        errors: [{"index": int, "line": 0, "raw": <code>, "reason": "..."}]
        index 是 ai_transactions 列表里的位置(0-based), 用于精确剔除
    """
    if not transactions:
        return []

    codes = list({t["code"] for t in transactions})

    # 1. 股票代码是否存在
    valid_codes = _check_codes_exist(codes)

    # 2. 当前持仓(用户级, 卖出校验用基线)
    holdings = query_all(
        "SELECT stock_code, quantity FROM holdings WHERE user_id = ? AND quantity > 0",
        (user_id,),
    )
    holding_map = {h["stock_code"]: h["quantity"] for h in holdings}

    # 3. 预计算本批每只代码的总买入/总卖出(顺序无关)
    batch_buys: dict[str, int] = {}
    batch_sells: dict[str, int] = {}
    for tx in transactions:
        c = tx.get("code", "")
        d = tx.get("direction", "")
        q = tx.get("quantity", 0)
        if d == "buy":
            batch_buys[c] = batch_buys.get(c, 0) + q
        elif d == "sell":
            batch_sells[c] = batch_sells.get(c, 0) + q

    errors = []
    for i, tx in enumerate(transactions):
        code = tx.get("code", "")

        # ── 基础格式校验(任一失败都直接跳过后续校验) ──
        if code not in valid_codes:
            errors.append({
                "index": i,
                "line": 0,
                "raw": code,
                "reason": f"股票代码 {code} 不存在或本地无数据",
            })
            continue

        price = tx.get("price", 0)
        if price <= 0:
            errors.append({
                "index": i,
                "line": 0,
                "raw": code,
                "reason": f"价格 {price} 无效 (必须 > 0)",
            })
            continue

        qty = tx.get("quantity", 0)
        if qty <= 0:
            errors.append({
                "index": i,
                "line": 0,
                "raw": code,
                "reason": f"数量 {qty} 无效 (必须 > 0)",
            })
            continue

        # 日期格式校验 — 兼容 "2026-08-05 13:18:26" (带时间)
        date_str = tx.get("date", "").strip()
        # 截取前 10 字符作为日期(去掉时间部分)
        if len(date_str) >= 10:
            date_str = date_str[:10]
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            errors.append({
                "index": i,
                "line": 0,
                "raw": code,
                "reason": f"日期 {date_str} 格式错误 (应为 YYYY-MM-DD)",
            })
            continue
        # 回写归一化日期(去掉时间)
        tx["date"] = date_str

        direction = tx.get("direction", "")
        if direction == "sell":
            # 顺序无关: 用本批总买入 + 当前持仓判断
            available = holding_map.get(code, 0) + batch_buys.get(code, 0)
            if qty > available:
                errors.append({
                    "index": i,
                    "line": 0,
                    "raw": code,
                    "reason": (
                        f"卖出 {qty} 股超过可用持仓 {available} 股"
                        f" (当前 {holding_map.get(code, 0)} + 本批买入 {batch_buys.get(code, 0)})"
                    ),
                })
                continue

    return errors


def _check_codes_exist(codes: list[str]) -> set[str]:
    """校验股票代码 — 查本地 stock_info 表 (Futu sync 写入)

    Returns: 存在的代码集合
    """
    if not codes:
        return set()

    placeholders = ",".join("?" * len(codes))

    try:
        rows = query_all(
            f"SELECT stock_code FROM stock_info WHERE stock_code IN ({placeholders})",
            tuple(codes),
        )
        return {r["stock_code"] for r in rows}
    except Exception as e:
        # stock_info 表可能不存在(老 DB / 极简部署)
        logger.warning("_check_codes_exist: 查询失败, 当作全部不存在: %s", e)
        return set()


# ── 股票代码到名称(批量落库时用) ──


def lookup_stock_names(codes: list[str]) -> dict[str, str]:
    """批量查股票名称, 返 {code: name}; 找不到返 code 自己"""
    if not codes:
        return {}

    placeholders = ",".join("?" * len(codes))

    result: dict[str, str] = {}
    try:
        rows = query_all(
            f"SELECT stock_code, name FROM stock_info WHERE stock_code IN ({placeholders})",
            tuple(codes),
        )
        for r in rows:
            if r.get("name"):
                result[r["stock_code"]] = r["name"]
    except Exception as e:
        logger.warning("lookup_stock_names: 查询失败, 用代码兜底: %s", e)

    # 最终兜底: 用 code 自己
    for c in codes:
        result.setdefault(c, c)

    return result