"""交易记忆系统 — 决策→验证→反思→注入 自动闭环

源自 TradingAgents TradingMemoryLog，适配 StockAI A 股场景。

工作流:
  Phase A（买入/卖出时）:
    store_decision() → 写 pending 条目到 trading_memory.md
    格式: [2025-06-03 | 600519 | 买入 | pending]

  Phase B（下次运行时）:
    resolve_pending() → 查询实际收益 → AI 反思 → 写回
    格式: [2025-06-03 | 600519 | 买入 | +3.2% | +1.5% | 5d]
          REFLECTION: 买点偏晚，应等突破确认后再入场...

  Phase C（Prompt 注入）:
    get_past_context(code) → 提取历史反思，注入新一轮 AI 分析

用法:
  from services.trading_memory import TradingMemoryLog
  mem = TradingMemoryLog()
  mem.store_decision(code="600519", direction="买入", date="2025-06-03", decision_text="...")
  mem.resolve_pending()   # 定时调用，更新实际收益
  ctx = mem.get_past_context("600519")  # 注入 AI prompt
"""

import logging
import os
import re
from pathlib import Path

from database import query_all

logger = logging.getLogger(__name__)

_SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"
_DECISION_RE = re.compile(r"DECISION:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
_REFLECTION_RE = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trading_memory.md")


class TradingMemoryLog:
    """追加式 Markdown 交易记忆日志，支持闭环反思"""

    def __init__(self, log_path: str = ""):
        self._log_path = Path(log_path) if log_path else Path(_DEFAULT_PATH)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Phase A: 写入决策 ──

    def store_decision(
        self,
        code: str,
        direction: str,
        date: str,
        decision_text: str = "",
        entry_price: float = 0,
        quantity: int = 0,
        strategy_id: str = "",
    ) -> None:
        """在交易发生后写入 pending 条目

        Args:
            code: 股票代码
            direction: 买入/卖出
            date: 交易日期
            decision_text: 决策理由
            entry_price: 买入价
            quantity: 数量
            strategy_id: 触发策略 ID（如 turtle_s1），用于策略维度复盘
        """
        # 幂等检查：同一天同一只股票同一策略不重复写
        if self._log_path.exists():
            raw = self._log_path.read_text(encoding="utf-8")
            prefix = f"[{date} | {code} | "
            sid_suffix = f" | {strategy_id}]" if strategy_id else "]"
            if prefix in raw:
                # 简单检查：已存在同日期同代码的 pending 条目
                idx = raw.index(prefix)
                snippet = raw[idx:idx+200]
                if "| pending]" in snippet:
                    return

        tag = f"[{date} | {code} | {direction}"
        if strategy_id:
            tag += f" | {strategy_id}"
        tag += " | pending]"

        body = (
            f"买入价: {entry_price}, 数量: {quantity}\n\n"
            if entry_price and quantity
            else ""
        )
        body += f"DECISION:\n{decision_text}" if decision_text else "DECISION:\n(无额外备注)"
        entry = f"{tag}\n\n{body}{_SEPARATOR}"

        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    # ── Phase B: 解析与更新 ──

    def load_entries(self) -> list[dict]:
        """解析所有日志条目"""
        if not self._log_path.exists():
            return []
        text = self._log_path.read_text(encoding="utf-8")
        raw_entries = [e.strip() for e in text.split(_SEPARATOR) if e.strip()]
        entries = []
        for raw in raw_entries:
            parsed = self._parse_entry(raw)
            if parsed:
                entries.append(parsed)
        return entries

    def get_pending_entries(self) -> list[dict]:
        """获取所有未结清的条目"""
        return [e for e in self.load_entries() if e.get("pending")]

    def resolve_pending(self) -> list[dict]:
        """尝试解决所有 pending 条目——从数据库查实际盈亏并生成 AI 反思

        Returns:
            [{code, date, direction, raw_return, alpha_return, reflection}, ...]
        """
        pending = self.get_pending_entries()
        if not pending:
            return []

        results = []
        for entry in pending:
            code = entry["code"]
            date = entry["date"]
            # 从 trade_journal 查实际盈亏
            row = query_all(
                """SELECT pnl, pnl_pct, entry_price, exit_price, exit_date
                   FROM trade_journal
                   WHERE stock_code = ? AND entry_date = ?
                   ORDER BY id DESC LIMIT 1""",
                (code, date),
            )
            if not row or row[0]["pnl"] is None:
                continue

            r = dict(row[0])
            reflection = self._generate_reflection(entry, r)
            self.update_with_outcome(
                code=code,
                trade_date=date,
                raw_return=r["pnl"],
                pnl_pct=r.get("pnl_pct") or 0,
                exit_date=r.get("exit_date", ""),
                reflection=reflection,
            )
            results.append({**entry, "pnl": r["pnl"], "reflection": reflection})

        return results

    def update_with_outcome(
        self,
        code: str,
        trade_date: str,
        raw_return: float,
        pnl_pct: float = 0,
        exit_date: str = "",
        reflection: str = "",
    ) -> None:
        """用实际收益和 AI 反思更新 pending 条目"""
        if not self._log_path.exists():
            return

        text = self._log_path.read_text(encoding="utf-8")
        blocks = text.split(_SEPARATOR)

        pending_prefix = f"[{trade_date} | {code} |"
        updated = False
        new_blocks = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                new_blocks.append(block)
                continue
            lines = stripped.splitlines()
            tag_line = lines[0].strip()
            if not updated and tag_line.startswith(pending_prefix) and tag_line.endswith("| pending]"):
                fields = [f.strip() for f in tag_line[1:-1].split("|")]
                direction = fields[2]
                pnl_str = f"{raw_return:+.2f}"
                new_tag = f"[{fields[0]} | {fields[1]} | {direction} | {pnl_str} | {pnl_pct:+.1%} | {exit_date}]"
                rest = "\n".join(lines[1:])
                refl = f"\n\nREFLECTION:\n{reflection}" if reflection else ""
                new_blocks.append(f"{new_tag}\n\n{rest}{refl}")
                updated = True
            else:
                new_blocks.append(block)

        if updated:
            tmp_path = self._log_path.with_suffix(".tmp")
            tmp_path.write_text(_SEPARATOR.join(new_blocks), encoding="utf-8")
            tmp_path.replace(self._log_path)

    def _generate_reflection(self, entry: dict, outcome: dict) -> str:
        """用 AI 根据决策和实际结果生成反思"""
        try:
            from services.ai_service import ai_chat
            import asyncio

            prompt = f"""你是专业的 A 股投资教练。请根据以下交易记录，做简短反思（不超过 150 字）。

股票: {entry['code']}
日期: {entry['date']}，方向: {entry.get('direction', '未知')}
实际盈亏: {outcome['pnl']:.2f} 元 ({outcome.get('pnl_pct', 0):.1%})，出场日: {outcome.get('exit_date', '未知')}
原始决策: {entry.get('decision', '')[:300]}

请分析: ①这笔交易做对了什么/做错了什么 ②下次该如何改进。用中文回答。"""

            raw = asyncio.new_event_loop().run_until_complete(
                ai_chat(prompt, function="review", system_prompt="你是专业的 A 股投资教练。请简洁有力地给出反思。")
            )
            return raw.strip() if raw else ""
        except Exception:
            logger.warning("trading_memory: AI reflection failed", exc_info=True)
            return ""

    # ── Phase C: 上下文注入 ──

    def get_past_context(self, code: str, n_same: int = 5, n_cross: int = 3) -> str:
        """获取历史交易上下文，用于注入 AI prompt

        Args:
            code: 当前分析标的
            n_same: 最多取同股票历史反思条数
            n_cross: 最多取跨股票通用教训条数

        Returns:
            格式化的历史上下文字符串，可直接拼接到 AI prompt 中
        """
        entries = [e for e in self.load_entries() if not e.get("pending") and e.get("reflection")]
        if not entries:
            return ""

        same, cross = [], []
        for e in reversed(entries):
            if len(same) >= n_same and len(cross) >= n_cross:
                break
            if e["code"] == code and len(same) < n_same:
                same.append(e)
            elif e["code"] != code and len(cross) < n_cross:
                cross.append(e)

        if not same and not cross:
            return ""

        parts = []
        if same:
            parts.append(f"## 你过去对 {code} 的交易记录（最近优先）")
            for e in same:
                pnl = e.get("raw", "?")
                refl = e.get("reflection", "")
                parts.append(f"- [{e['date']}] {e.get('direction','?')}，盈亏 {pnl}元: {refl}")
        if cross:
            parts.append("## 你最近其他股票的交易教训")
            for e in cross:
                pnl = e.get("raw", "?")
                refl = e.get("reflection", "")
                parts.append(f"- [{e['date']}] {e['code']} {e.get('direction','?')}，盈亏 {pnl}元: {refl}")

        return "\n\n".join(parts)

    # ── Phase D: 策略维度上下文 ──

    def get_strategy_context(self, strategy_id: str, code: str = "", n: int = 5) -> str:
        """获取指定策略的历史表现上下文，用于注入 AI 选股 prompt

        Args:
            strategy_id: 策略 ID（如 turtle_s1）
            code: 可选，指定股票代码时可获得该策略在这只股票上的历史
            n: 最多返回条数

        Returns:
            格式化的策略历史上下文字符串
        """
        entries = [
            e for e in self.load_entries()
            if not e.get("pending") and e.get("strategy_id") == strategy_id
        ]
        if not entries:
            return ""

        # 按日期排序
        entries.sort(key=lambda e: e["date"], reverse=True)

        # 过滤
        if code:
            same_code = [e for e in entries if e["code"] == code][:n]
            entries = same_code
        else:
            entries = entries[:n]

        if not entries:
            return ""

        # 统计
        wins = []
        losses = []
        for e in entries:
            try:
                raw = float(e.get("raw", 0) or 0)
                (wins if raw > 0 else losses).append(raw)
            except (ValueError, TypeError):
                pass

        total = len(wins) + len(losses)
        win_rate = round(len(wins) / total * 100, 1) if total > 0 else 0
        avg_win = round(sum(wins) / len(wins), 2) if wins else 0
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0

        lines = [
            f"## 策略 {strategy_id} 历史表现",
            f"- 最近 {total} 笔: 胜率 {win_rate}%, "
            f"均盈 ¥{avg_win:.0f}, 均亏 ¥{avg_loss:.0f}",
        ]

        if code:
            lines[0] += f" 在 {code} 上"
            lines.append(f"- {code} 的交易记录:")
            for e in entries:
                raw = e.get("raw", "?")
                refl = e.get("reflection", "")
                lines.append(f"  [{e['date']}] 盈亏 {raw}: {refl[:80]}")
        else:
            lines.append("- 最近交易:")
            for e in entries[:n]:
                raw = e.get("raw", "?")
                lines.append(f"  [{e['date']}] {e['code']} 盈亏 {raw}")

        return "\n".join(lines)

    # ── 解析辅助 ──

    def _parse_entry(self, raw: str) -> dict | None:
        lines = raw.strip().splitlines()
        if not lines:
            return None
        tag_line = lines[0].strip()
        if not (tag_line.startswith("[") and tag_line.endswith("]")):
            return None
        fields = [f.strip() for f in tag_line[1:-1].split("|")]
        # 格式:
        #   旧: [date | code | direction | pending]               — 4 fields
        #   旧已结算: [date | code | direction | pnl | pnl_pct | exit_date] — 5-6 fields
        #   新: [date | code | direction | strategy_id | pending]  — 5 fields (strategy)
        #   新已结算: [date | code | direction | strategy_id | pnl | pnl_pct | exit_date] — 6-7 fields
        if len(fields) < 4:
            return None

        has_strategy = len(fields) >= 5 and fields[4] == "pending" and fields[3] not in ("pending",)

        entry = {
            "date": fields[0],
            "code": fields[1],
            "direction": fields[2],
        }

        if has_strategy:
            # [date | code | direction | strategy_id | pending] 或 [date | code | direction | strategy_id | pnl | pnl_pct | exit_date]
            entry["strategy_id"] = fields[3]
            pending_field = fields[4]
            entry["pending"] = pending_field == "pending"
            entry["raw"] = pending_field if pending_field != "pending" else None
            entry["pnl_pct"] = fields[5] if len(fields) > 5 else None
            entry["exit_date"] = fields[6] if len(fields) > 6 else None
        else:
            # [date | code | direction | pending] 或 [date | code | direction | pnl | pnl_pct | exit_date]
            entry["strategy_id"] = ""
            pending_field = fields[3]
            entry["pending"] = pending_field == "pending"
            entry["raw"] = pending_field if pending_field != "pending" else None
            entry["pnl_pct"] = fields[4] if len(fields) > 4 else None
            entry["exit_date"] = fields[5] if len(fields) > 5 else None

        body = "\n".join(lines[1:]).strip()
        dm = _DECISION_RE.search(body)
        rm = _REFLECTION_RE.search(body)
        entry["decision"] = dm.group(1).strip() if dm else ""
        entry["reflection"] = rm.group(1).strip() if rm else ""
        return entry
