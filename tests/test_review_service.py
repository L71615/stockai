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
