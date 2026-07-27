"""多 Agent 聚合逻辑测试 — _aggregate_results 投票/共识/否决

纯函数测试，不依赖 AI 调用。
"""
import pytest
from services.multi_agent_service import _aggregate_results, _build_candidate_text


class TestBuildCandidateText:
    def test_normal_candidates(self):
        candidates = [
            {"code": "000001", "name": "平安银行", "industry": "银行", "score": 0.85, "price": 12.5, "hit_count": 22,
             "top_factors": [{"factor": "roe", "contribution": 0.12}, {"factor": "pe_inverse", "contribution": 0.08}]},
            {"code": "600000", "name": "浦发银行", "industry": "银行", "score": 0.72, "price": 9.8, "hit_count": 18,
             "top_factors": [{"factor": "pb_inverse", "contribution": 0.10}]},
        ]
        text = _build_candidate_text(candidates)
        assert "000001" in text
        assert "平安银行" in text
        assert "roe" in text

    def test_sanitize_special_chars(self):
        candidates = [
            {"code": "000001", "name": "测试{股}票[名]\"称'`", "industry": "银行", "score": 0.5, "price": 10, "hit_count": 5,
             "top_factors": []},
        ]
        text = _build_candidate_text(candidates)
        # 特殊字符应被过滤
        assert "{" not in text
        assert "}" not in text
        assert "[" not in text

    def test_max_candidates_limit(self):
        candidates = [{"code": f"{i:06d}", "name": f"股票{i}", "industry": "", "score": 0.5, "price": 10, "hit_count": 1,
                       "top_factors": []} for i in range(50)]
        text = _build_candidate_text(candidates, max_candidates=5)
        lines = text.strip().split("\n")
        # 每只股票 2 行（主行 + 因子贡献行）
        assert len(lines) <= 10  # 5 candidates * 2 lines each


class TestAggregateResults:
    def test_unanimous_consensus(self):
        """全票通过：4 agents 推荐同一只股票"""
        agent_results = [
            {"agent_key": "value", "agent_name": "价值分析师", "picks": [
                {"code": "000001", "score": 9.0, "confidence": "high", "reason": "低估值"}]},
            {"agent_key": "technical", "agent_name": "技术分析师", "picks": [
                {"code": "000001", "score": 8.0, "confidence": "high", "reason": "趋势向上"}]},
            {"agent_key": "risk", "agent_name": "风险控制官", "picks": [
                {"code": "000001", "score": 7.0, "confidence": "medium", "reason": "低波动"}]},
            {"agent_key": "sentiment", "agent_name": "情绪捕手", "picks": [
                {"code": "000001", "score": 8.5, "confidence": "high", "reason": "资金流入"}]},
        ]
        result = _aggregate_results(agent_results, [{"code": "000001", "name": "平安银行"}])
        assert result["agent_count"] == 4
        assert len(result["aggregated"]) == 1
        assert result["aggregated"][0]["votes"] == 4
        assert result["aggregated"][0]["consensus"] == "全票通过"

    def test_majority_consensus(self):
        """多数通过：3/5 agents 推荐"""
        agent_results = [
            {"agent_key": "value", "agent_name": "价值分析师", "picks": [
                {"code": "000001", "score": 8.0, "confidence": "high", "reason": "低估"}]},
            {"agent_key": "technical", "agent_name": "技术分析师", "picks": [
                {"code": "000001", "score": 7.0, "confidence": "medium", "reason": "趋势"}]},
            {"agent_key": "risk", "agent_name": "风险控制官", "picks": [
                {"code": "000001", "score": 6.0, "confidence": "medium", "reason": "可接受"}]},
            {"agent_key": "sentiment", "agent_name": "情绪捕手", "picks": []},
            {"agent_key": "macro", "agent_name": "宏观策略师", "picks": []},
        ]
        result = _aggregate_results(agent_results, [{"code": "000001", "name": "平安银行"}])
        assert result["aggregated"][0]["consensus"] == "多数通过"
        assert result["aggregated"][0]["votes"] == 3

    def test_divided_consensus(self):
        """分歧较大：2/5 agents 推荐"""
        agent_results = [
            {"agent_key": "value", "agent_name": "价值分析师", "picks": [
                {"code": "000001", "score": 7.0, "confidence": "low", "reason": "一般"}]},
            {"agent_key": "technical", "agent_name": "技术分析师", "picks": [
                {"code": "000001", "score": 6.0, "confidence": "low", "reason": "弱"}]},
            {"agent_key": "risk", "agent_name": "风险控制官", "picks": []},
            {"agent_key": "sentiment", "agent_name": "情绪捕手", "picks": []},
            {"agent_key": "macro", "agent_name": "宏观策略师", "picks": []},
        ]
        result = _aggregate_results(agent_results, [{"code": "000001", "name": "平安银行"}])
        assert result["aggregated"][0]["consensus"] == "分歧较大"

    def test_minority_consensus(self):
        """少数推荐：1/5 agents"""
        agent_results = [
            {"agent_key": "value", "agent_name": "价值分析师", "picks": [
                {"code": "000001", "score": 7.0, "confidence": "low", "reason": "尝试"}]},
            {"agent_key": "technical", "agent_name": "技术分析师", "picks": []},
            {"agent_key": "risk", "agent_name": "风险控制官", "picks": []},
            {"agent_key": "sentiment", "agent_name": "情绪捕手", "picks": []},
            {"agent_key": "macro", "agent_name": "宏观策略师", "picks": []},
        ]
        result = _aggregate_results(agent_results, [{"code": "000001", "name": "平安银行"}])
        assert result["aggregated"][0]["consensus"] == "少数推荐"

    def test_risk_veto(self):
        """风险否决：risk agent 评分 < 3 且 confidence=low"""
        agent_results = [
            {"agent_key": "value", "agent_name": "价值分析师", "picks": [
                {"code": "000001", "score": 8.0, "confidence": "high", "reason": "好"}]},
            {"agent_key": "risk", "agent_name": "风险控制官", "picks": [
                {"code": "000001", "score": 2.0, "confidence": "low", "reason": "高风险", "risk_flag": "高杠杆"}]},
        ]
        result = _aggregate_results(agent_results, [{"code": "000001", "name": "平安银行"}])
        assert result["aggregated"][0]["risk_veto"] is True
        assert result["aggregated"][0]["consensus"] == "⚠️ 风险否决"

    def test_agent_error_handling(self):
        """部分 Agent 返回 error 不影响聚合"""
        agent_results = [
            {"agent_key": "value", "agent_name": "价值分析师", "error": "timeout", "picks": []},
            {"agent_key": "technical", "agent_name": "技术分析师", "picks": [
                {"code": "000001", "score": 8.0, "confidence": "high", "reason": "好"}]},
        ]
        result = _aggregate_results(agent_results, [{"code": "000001", "name": "平安银行"}])
        assert result["agent_count"] == 1  # only technical counted
        assert result["aggregated"][0]["votes"] == 1

    def test_empty_agent_results(self):
        result = _aggregate_results([], [])
        assert result["agent_count"] == 0
        assert result["aggregated"] == []

    def test_agent_score_average(self):
        """Agent 评分取均值"""
        agent_results = [
            {"agent_key": "value", "agent_name": "价值分析师", "picks": [
                {"code": "000001", "score": 8.0, "confidence": "high", "reason": "好"}]},
            {"agent_key": "technical", "agent_name": "技术分析师", "picks": [
                {"code": "000001", "score": 6.0, "confidence": "medium", "reason": "可"}]},
        ]
        result = _aggregate_results(agent_results, [{"code": "000001", "name": "平安银行"}])
        assert result["aggregated"][0]["agent_score"] == 7.0  # (8.0 + 6.0) / 2


# ═══════════════════════════════════════════════════════════════
#  v4.0 A1 — 8 角色验证
# ═══════════════════════════════════════════════════════════════

class TestEightRoleSetup:
    """验证 v4.0 8 角色的常量 + 提示词 + 工具调用编排"""

    def test_role_systems_has_eight_roles(self):
        from services.multi_agent_service import ROLE_SYSTEMS
        assert len(ROLE_SYSTEMS) == 8
        expected = {"technical", "fundamentals", "capital_flow", "policy",
                    "bull", "bear", "short_researcher", "judge"}
        assert set(ROLE_SYSTEMS.keys()) == expected

    def test_new_role_prompts_are_non_empty(self):
        from services.multi_agent_service import (
            CAPITAL_FLOW_SYSTEM, POLICY_INTERPRETER_SYSTEM, SHORT_RESEARCHER_SYSTEM,
        )
        for prompt in (CAPITAL_FLOW_SYSTEM, POLICY_INTERPRETER_SYSTEM, SHORT_RESEARCHER_SYSTEM):
            assert isinstance(prompt, str)
            assert len(prompt) > 100  # 不应是占位符

    def test_new_prompts_have_framework(self):
        """3 个新角色 prompt 都有分析框架(数字编号)"""
        from services.multi_agent_service import (
            CAPITAL_FLOW_SYSTEM, POLICY_INTERPRETER_SYSTEM, SHORT_RESEARCHER_SYSTEM,
        )
        for prompt in (CAPITAL_FLOW_SYSTEM, POLICY_INTERPRETER_SYSTEM, SHORT_RESEARCHER_SYSTEM):
            # 应至少有 3 个编号项
            numbered = sum(1 for line in prompt.split("\n") if line.strip() and line.strip()[0].isdigit() and "." in line[:4])
            assert numbered >= 3, f"Prompt 缺少分析框架编号:\n{prompt[:200]}"

    def test_report_labels_map_all_seven(self):
        """_REPORT_LABELS 覆盖 7 个报告字段(不含 judge)"""
        from services.multi_agent_service import _REPORT_LABELS
        assert len(_REPORT_LABELS) == 7
        assert "capital_flow_report" in _REPORT_LABELS
        assert "policy_report" in _REPORT_LABELS
        assert "short_researcher_case" in _REPORT_LABELS


class TestAnalyzeStockEightRoles:
    """analyze_stock() 8 角色调用编排 — 用 monkeypatch 模拟 ai_chat"""

    @pytest.fixture
    def mock_ai_chat(self, monkeypatch):
        """把所有 ai_chat 调用都返回 mock 文本(不调真实 LLM)"""
        from services import multi_agent_service as mas

        def fake_chat(message, **kwargs):
            # 8 个不同的 mock 响应
            return "fake response"

        async def fake_async_chat(message, **kwargs):
            return "fake response"

        monkeypatch.setattr(mas, "ai_chat", fake_async_chat)
        return fake_async_chat

    @pytest.mark.asyncio
    async def test_default_8_roles_called(self, mock_ai_chat, monkeypatch):
        """默认 enabled_roles=None → 8 角色全部启用"""
        from services import multi_agent_service as mas
        from services.trading_memory import TradingMemoryLog

        # 屏蔽 trading memory(避免依赖)
        monkeypatch.setattr(TradingMemoryLog, "get_past_context", lambda *a, **k: "")
        monkeypatch.setattr(TradingMemoryLog, "get_strategy_context", lambda *a, **k: "")

        # 屏蔽 _gather_stock_data(避免依赖历史数据)
        monkeypatch.setattr(mas, "_gather_stock_data", lambda code: {
            "name": "测试", "price": 100.0, "change_pct": 1.5,
        })

        # 屏蔽 _parse_judge_response(默认即可)
        result = await mas.analyze_stock("600519")

        assert "error" not in result
        # 5 角色字段
        assert "technical_report" in result
        assert "fundamentals_report" in result
        assert "bull_case" in result
        assert "bear_case" in result
        # 3 新角色字段
        assert "capital_flow_report" in result
        assert "policy_report" in result
        assert "short_researcher_case" in result
        # 元数据
        assert result["agent_count"] == 8
        assert "judge" in result["enabled_roles"]
        assert "capital_flow" in result["enabled_roles"]

    @pytest.mark.asyncio
    async def test_backward_compat_5_roles(self, mock_ai_chat, monkeypatch):
        """显式传 enabled_roles → 只启用指定角色"""
        from services import multi_agent_service as mas
        from services.trading_memory import TradingMemoryLog

        monkeypatch.setattr(TradingMemoryLog, "get_past_context", lambda *a, **k: "")
        monkeypatch.setattr(TradingMemoryLog, "get_strategy_context", lambda *a, **k: "")
        monkeypatch.setattr(mas, "_gather_stock_data", lambda code: {
            "name": "测试", "price": 100.0, "change_pct": 1.5,
        })

        result = await mas.analyze_stock(
            "600519",
            enabled_roles=["technical", "fundamentals", "bull", "bear", "judge"],
        )
        assert "error" not in result
        assert result["agent_count"] == 5
        # 5 角色字段都有
        assert "technical_report" in result
        assert "fundamentals_report" in result
        # 3 新角色字段为空(没启用)
        assert result["capital_flow_report"] == ""
        assert result["policy_report"] == ""
        assert result["short_researcher_case"] == ""

    @pytest.mark.asyncio
    async def test_judge_always_included(self, mock_ai_chat, monkeypatch):
        """即使 enabled_roles 显式不包含 judge,也会自动加入"""
        from services import multi_agent_service as mas
        from services.trading_memory import TradingMemoryLog

        monkeypatch.setattr(TradingMemoryLog, "get_past_context", lambda *a, **k: "")
        monkeypatch.setattr(TradingMemoryLog, "get_strategy_context", lambda *a, **k: "")
        monkeypatch.setattr(mas, "_gather_stock_data", lambda code: {
            "name": "测试", "price": 100.0, "change_pct": 1.5,
        })

        result = await mas.analyze_stock(
            "600519",
            enabled_roles=["technical", "fundamentals"],
        )
        assert "judge" in result["enabled_roles"]
        # 2 round1 + 0 round2 + 1 judge = 3 agents
        assert result["agent_count"] == 3

    @pytest.mark.asyncio
    async def test_round1_round2_ordering(self, mock_ai_chat, monkeypatch):
        """验证 round1 → round2 顺序(round1 必须先调用,后才 round2)"""
        from services import multi_agent_service as mas
        from services.trading_memory import TradingMemoryLog

        call_order: list[str] = []

        async def tracking_chat(message, **kwargs):
            sys_prompt = kwargs.get("system_prompt", "")
            if sys_prompt == mas.TECHNICAL_SYSTEM:
                call_order.append("round1_technical")
            elif sys_prompt == mas.FUNDAMENTALS_SYSTEM:
                call_order.append("round1_fundamentals")
            elif sys_prompt == mas.CAPITAL_FLOW_SYSTEM:
                call_order.append("round1_capital_flow")
            elif sys_prompt == mas.POLICY_INTERPRETER_SYSTEM:
                call_order.append("round1_policy")
            elif sys_prompt == mas.BULL_SYSTEM:
                call_order.append("round2_bull")
            elif sys_prompt == mas.BEAR_SYSTEM:
                call_order.append("round2_bear")
            elif sys_prompt == mas.SHORT_RESEARCHER_SYSTEM:
                call_order.append("round2_short")
            elif sys_prompt == mas.JUDGE_SYSTEM:
                call_order.append("round3_judge")
            return "ok"

        monkeypatch.setattr(mas, "ai_chat", tracking_chat)
        monkeypatch.setattr(TradingMemoryLog, "get_past_context", lambda *a, **k: "")
        monkeypatch.setattr(TradingMemoryLog, "get_strategy_context", lambda *a, **k: "")
        monkeypatch.setattr(mas, "_gather_stock_data", lambda code: {
            "name": "测试", "price": 100.0, "change_pct": 1.5,
        })

        await mas.analyze_stock("600519")

        # 验证 round 顺序
        r1 = [c for c in call_order if c.startswith("round1_")]
        r2 = [c for c in call_order if c.startswith("round2_")]
        r3 = [c for c in call_order if c.startswith("round3_")]

        assert len(r1) == 4  # 4 个 round1 角色
        assert len(r2) == 3  # 3 个 round2 角色
        assert len(r3) == 1  # 1 个 judge

        # 验证 round3 在 round2 之后
        if call_order:
            last_r2_idx = max(i for i, c in enumerate(call_order) if c.startswith("round2_"))
            judge_idx = next(i for i, c in enumerate(call_order) if c.startswith("round3_"))
            assert judge_idx > last_r2_idx
