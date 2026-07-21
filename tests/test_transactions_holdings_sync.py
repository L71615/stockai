from database import execute


def test_add_buy_transaction_creates_holding_when_missing(client):
    execute("DELETE FROM transactions WHERE user_id = 1 AND stock_code = ?", ("600519",))
    execute("DELETE FROM holdings WHERE user_id = 1 AND stock_code = ?", ("600519",))

    response = client.post(
        "/api/stocks/transactions",
        json={
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "asset_type": "stock",
            "direction": "buy",
            "price": 100.0,
            "quantity": 10,
            "traded_at": "2026-06-17",
            "note": "test buy",
        },
    )

    assert response.status_code == 200

    holdings = client.get("/api/stocks/holdings").json()
    created = [h for h in holdings if h["stock_code"] == "600519"]

    assert len(created) == 1
    assert created[0]["quantity"] == 10
    assert created[0]["stock_name"] == "贵州茅台"
