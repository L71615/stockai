import pytest


class TestReviewStructuredEndpoint:
    def test_post_success(self, client):
        response = client.post("/api/stocks/review/structured", json={
            "report_type": "daily",
        })
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "dimensions" in data
        assert "suggestions" in data
        assert "transactions_count" in data

    def test_post_cold_start(self, client):
        response = client.post("/api/stocks/review/structured", json={
            "report_type": "daily",
            "user_id": 99999,
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("cold_start") is True

    def test_post_custom_params(self, client):
        response = client.post("/api/stocks/review/structured", json={
            "report_type": "weekly",
            "provider": "minimax",
        })
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data


class TestReviewsListEndpoint:
    def test_get_empty_list(self, client):
        response = client.get("/api/stocks/reviews")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_with_reports(self, client):
        # Generate a report first
        client.post("/api/stocks/review/structured", json={"report_type": "daily"})
        response = client.get("/api/stocks/reviews")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            assert "summary" in data[0]
            assert "created_at" in data[0]
