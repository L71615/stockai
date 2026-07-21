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
