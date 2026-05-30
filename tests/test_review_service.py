from services.review_service import aggregate_transactions


class TestAggregateTransactions:
    def test_returns_empty_for_no_transactions(self):
        result = aggregate_transactions(user_id=99999)
        assert result == {
            "transactions": [],
            "total_trades": 0,
            "win_count": 0,
            "lose_count": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_hold_days": 0,
            "top_gainers": [],
            "top_losers": [],
            "holdings_summary": [],
        }

    def test_aggregates_real_data(self):
        from database import query_all

        # Check we have seed data
        count = query_all("SELECT count(*) as c FROM transactions WHERE user_id = 1")
        if count[0]["c"] == 0:
            import subprocess
            subprocess.run(["python", "backend/seed_demo_data.py"], check=True)

        result = aggregate_transactions(user_id=1)
        assert result["total_trades"] >= 4
        assert result["total_pnl"] != 0
        assert len(result["top_gainers"]) > 0
        assert len(result["top_losers"]) > 0
        assert len(result["holdings_summary"]) > 0
        assert "stock_code" in result["transactions"][0]
        assert "pnl" in result["transactions"][0]

    def test_win_rate_calculation(self):
        result = aggregate_transactions(user_id=1)
        total = result["win_count"] + result["lose_count"]
        if total > 0:
            expected_rate = round(result["win_count"] / total * 100, 1)
            assert result["win_rate"] == expected_rate


class TestBuildReviewPrompt:
    def test_includes_dimension_schema(self):
        from services.review_service import build_review_prompt
        data = {
            "total_trades": 15,
            "total_pnl": 50000,
            "win_rate": 62.5,
            "holdings_summary": [{"stock_code": "600519", "stock_name": "贵州茅台", "cost_price": 1720.50, "quantity": 200, "asset_type": "stock"}],
            "top_gainers": [{"stock_code": "600519", "stock_name": "贵州茅台", "pnl": 26000, "hold_days": 35}],
            "top_losers": [{"stock_code": "300750", "stock_name": "宁德时代", "pnl": -13250, "hold_days": 25}],
            "transactions": [],
            "avg_hold_days": 30.5,
            "win_count": 9,
            "lose_count": 5,
        }
        prompt = build_review_prompt(data)
        assert "dimensions" in prompt
        assert "盈亏归因" in prompt
        assert "行为模式" in prompt
        assert "风险提示" in prompt
        assert "JSON" in prompt
        assert '"summary"' in prompt
        assert '"suggestions"' in prompt
        assert '"reasoning"' in prompt
        assert "贵州茅台" in prompt
        assert "宁德时代" in prompt

    def test_handles_empty_data(self):
        from services.review_service import build_review_prompt
        data = {
            "total_trades": 0,
            "total_pnl": 0,
            "win_rate": 0,
            "holdings_summary": [],
            "top_gainers": [],
            "top_losers": [],
            "transactions": [],
            "avg_hold_days": 0,
            "win_count": 0,
            "lose_count": 0,
        }
        prompt = build_review_prompt(data)
        assert len(prompt) > 0
        assert "暂无" in prompt


class TestParseReviewResponse:
    def test_parses_valid_json(self):
        from services.review_service import parse_review_response
        raw = '{"summary":"总体评估","dimensions":[{"id":"a","title":"T","summary":"S","detail":"D","score":80}],"suggestions":[{"text":"建议","reasoning":"理由"}]}'
        result = parse_review_response(raw)
        assert result["summary"] == "总体评估"
        assert len(result["dimensions"]) == 1
        assert result["dimensions"][0]["score"] == 80
        assert result["raw"] == raw

    def test_strips_markdown_code_block(self):
        from services.review_service import parse_review_response
        raw = '```json\n{"summary":"test","dimensions":[],"suggestions":[]}\n```'
        result = parse_review_response(raw)
        assert result["summary"] == "test"

    def test_extracts_json_from_mixed_text(self):
        from services.review_service import parse_review_response
        raw = 'Here is the report: {"summary":"mixed","dimensions":[],"suggestions":[]} end'
        result = parse_review_response(raw)
        assert result["summary"] == "mixed"

    def test_fallback_on_invalid_json(self):
        from services.review_service import parse_review_response
        raw = '这是一段无法解析的中文文本，没有 JSON 结构'
        result = parse_review_response(raw)
        assert result["summary"] == "AI 返回格式异常，以下为原始内容"
        assert result["raw"] == raw
        assert result["dimensions"] == []
        assert result["suggestions"] == []

    def test_fallback_on_empty_response(self):
        from services.review_service import parse_review_response
        result = parse_review_response("")
        assert result["summary"] == "AI 分析暂不可用，请稍后重试"
        assert result["error"] is True

    def test_repairs_common_json_errors(self):
        from services.review_service import parse_review_response
        # Missing comma between array elements
        raw = '{"summary":"test","dimensions":[{"id":"a" "title":"T" "summary":"S" "detail":"D" "score":80}] "suggestions":[]}'
        result = parse_review_response(raw)
        assert result["summary"] == "test"
