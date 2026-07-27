"""v4.0 A4 个性化 prompt 单元测试

覆盖:
  - build_user_style_context: 从交易历史提取风格
  - 空交易数据返回 None
  - 胜率/持仓天数/风险偏好计算
  - 与 multi_agent 集成(personalize=True 注入,False 不注入)
"""

from datetime import datetime, timedelta

import pytest

from services.user_style import (
    _analyze_trades,
    build_user_style_context,
)


# ═══════════════════════════════════════════════════════════════
#  build_user_style_context
# ═══════════════════════════════════════════════════════════════


class TestBuildUserStyleContext:
    def test_no_trades_returns_none(self, db):
        """无交易历史 → 返回 None"""
        from database import query_one
        admin = query_one("SELECT id FROM users LIMIT 1")
        result = build_user_style_context(user_id=admin["id"])
        assert result is None

    def test_only_buys_no_sells_returns_context(self, db):
        """只有 buy 没有 sell(用户刚开仓,还没卖)→ 仍有 context(只是无胜率)"""
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execute(
            """INSERT INTO transactions
               (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000001", "测试", "buy", 100.0, 100, 10000.0, 5.0, now),
        )
        result = build_user_style_context(user_id=user_id)
        assert result is not None
        # 包含必要字段
        assert "总交易笔数" in result
        assert "风险偏好" in result

    def test_full_trading_history(self, db):
        """完整交易历史(buy + sell, 有胜有负)→ 完整 context"""
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]

        now = datetime.now()
        # 1 笔买, 1 笔卖(盈利)
        execute(
            """INSERT INTO transactions
               (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000001", "测试A", "buy", 100.0, 100, 10000.0, 5.0,
             (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        execute(
            """INSERT INTO transactions
               (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000001", "测试A", "sell", 110.0, 100, 11000.0, 5.0,
             now.strftime("%Y-%m-%d %H:%M:%S")),
        )
        result = build_user_style_context(user_id=user_id)
        assert result is not None
        # 应包含胜率信息
        assert "历史胜率" in result
        # 应包含平均持仓天数
        assert "平均持仓天数" in result
        # 应包含风险偏好
        assert "风险偏好" in result


class TestAnalyzeTrades:
    def test_win_rate_calculation(self, db):
        """胜率 = 盈利笔数 / 总笔数"""
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]
        now = datetime.now()

        # 2 笔 round-trip:1 盈 1 亏
        for code, buy_price, sell_price in [("000001", 100, 110), ("000002", 100, 90)]:
            execute(
                """INSERT INTO transactions
                   (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, code, f"测试{code}", "buy", buy_price, 100, buy_price * 100, 5.0,
                 (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")),
            )
            execute(
                """INSERT INTO transactions
                   (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, code, f"测试{code}", "sell", sell_price, 100, sell_price * 100, 5.0,
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )

        result = _analyze_trades(user_id=user_id, lookback_days=30)
        assert result["win_count"] == 1
        assert result["loss_count"] == 1
        assert result["win_rate"] == 0.5

    def test_risk_tolerance_short_hold_high(self, db):
        """短持仓(短线)→ 高风险偏好"""
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]
        now = datetime.now()

        # 1 天持仓
        execute(
            """INSERT INTO transactions
               (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000001", "短线", "buy", 100.0, 100, 10000.0, 5.0,
             (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        execute(
            """INSERT INTO transactions
               (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "000001", "短线", "sell", 105.0, 100, 10500.0, 5.0,
             now.strftime("%Y-%m-%d %H:%M:%S")),
        )
        result = _analyze_trades(user_id=user_id, lookback_days=30)
        assert result["risk_tolerance"] == "high"

    def test_risk_tolerance_long_hold_low(self, db):
        """长持仓(长线)→ 低风险偏好"""
        from database import query_one, execute
        admin = query_one("SELECT id FROM users LIMIT 1")
        user_id = admin["id"]
        now = datetime.now()
        # 用唯一 stock_code 避免与本 session 其他测试数据冲突
        unique_code = f"9999{datetime.now().strftime('%H%M%S%f')[:10]}"

        # 90 天持仓
        execute(
            """INSERT INTO transactions
               (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, unique_code, "长线", "buy", 100.0, 100, 10000.0, 5.0,
             (now - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        execute(
            """INSERT INTO transactions
               (user_id, stock_code, stock_name, direction, price, quantity, amount, fee, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, unique_code, "长线", "sell", 110.0, 100, 11000.0, 5.0,
             now.strftime("%Y-%m-%d %H:%M:%S")),
        )
        result = _analyze_trades(user_id=user_id, lookback_days=180)
        assert result["risk_tolerance"] == "low"


# ═══════════════════════════════════════════════════════════════
#  multi_agent 集成
# ═══════════════════════════════════════════════════════════════


class TestPersonalizeIntegration:
    @pytest.mark.asyncio
    async def test_personalize_true_injects_context(self, monkeypatch):
        """personalize=True + user_id → user_style 注入 system prompt"""
        from services import multi_agent_service as mas
        from services.trading_memory import TradingMemoryLog

        used_prompts: list[str] = []

        async def tracking_chat(message, **kwargs):
            used_prompts.append(kwargs.get("system_prompt", ""))
            return '{"verdict": "持有", "confidence": 0.5, "key_reasons": [], "risk_warning": "", "reasoning_chain": {}}'

        monkeypatch.setattr(mas, "ai_chat", tracking_chat)
        monkeypatch.setattr(TradingMemoryLog, "get_past_context", lambda *a, **k: "")
        monkeypatch.setattr(TradingMemoryLog, "get_strategy_context", lambda *a, **k: "")
        monkeypatch.setattr(mas, "_gather_stock_data", lambda code: {"name": "x", "price": 1.0})

        # Mock build_user_style_context 返回已知字符串
        monkeypatch.setattr(
            "services.user_style.build_user_style_context",
            lambda user_id: "## 用户风格\n- 平均持仓 5 天",
        )

        result = await mas.analyze_stock("000001", personalize=True, user_id=1)

        # 至少有一个 system prompt 应包含用户风格
        assert any("用户风格" in p for p in used_prompts)
        assert result["user_style"] != ""
        assert result["personalize"] is True

    @pytest.mark.asyncio
    async def test_personalize_false_no_injection(self, monkeypatch):
        """personalize=False → 不注入 user_style"""
        from services import multi_agent_service as mas
        from services.trading_memory import TradingMemoryLog

        used_prompts: list[str] = []

        async def tracking_chat(message, **kwargs):
            used_prompts.append(kwargs.get("system_prompt", ""))
            return '{"verdict": "持有", "confidence": 0.5, "key_reasons": [], "risk_warning": "", "reasoning_chain": {}}'

        monkeypatch.setattr(mas, "ai_chat", tracking_chat)
        monkeypatch.setattr(TradingMemoryLog, "get_past_context", lambda *a, **k: "")
        monkeypatch.setattr(TradingMemoryLog, "get_strategy_context", lambda *a, **k: "")
        monkeypatch.setattr(mas, "_gather_stock_data", lambda code: {"name": "x", "price": 1.0})

        result = await mas.analyze_stock("000001", personalize=False)
        assert result["user_style"] == ""
        assert result["personalize"] is False
