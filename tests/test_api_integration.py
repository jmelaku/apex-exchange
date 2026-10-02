import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_validation_health_idempotency_cancel_and_market_expiry():
    api = os.getenv("API_TEST_URL", "http://localhost:8000")
    async with httpx.AsyncClient(base_url=api, timeout=10) as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["database"] == health.json()["matching_engine"] == "up"

        invalid = await client.post("/orders", json={"account_id": 1, "symbol": "bad symbol",
            "side": "BUY", "order_type": "LIMIT", "quantity": 0})
        assert invalid.status_code == 422

        client_id = str(uuid.uuid4())
        payload = {"client_order_id": client_id, "account_id": 1, "symbol": "BTCUSD",
                   "side": "BUY", "order_type": "LIMIT", "quantity": 2, "price_ticks": 1}
        first = await client.post("/orders", json=payload)
        second = await client.post("/orders", json=payload)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        cancelled = await client.delete(f"/orders/{first.json()['id']}")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"

        market = await client.post("/orders", json={"account_id": 1, "symbol": "BTCUSD",
            "side": "BUY", "order_type": "MARKET", "quantity": 1})
        assert market.status_code == 201
        assert market.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_risk_service_generates_durable_rate_alert():
    risk_url = os.getenv("RISK_TEST_URL", "http://localhost:8001")
    api_url = os.getenv("API_TEST_URL", "http://localhost:8000")
    account = 2
    alerts = []
    async with httpx.AsyncClient(base_url=risk_url, timeout=10) as client:
        for _ in range(30):
            response = await client.post("/events", json={"event_type": "ORDER", "account_id": account,
                "symbol": "MSFT", "side": "SELL", "quantity": 1})
            assert response.status_code == 200
            alerts.extend(response.json()["risk_events"])
    if not alerts:  # repeat runs may be inside the analyzer's alert cooldown
        async with httpx.AsyncClient(base_url=api_url, timeout=10) as client:
            alerts = (await client.get("/risk-events")).json()
    assert any(alert["category"] == "ORDER_RATE" and isinstance(alert["metrics"], dict) for alert in alerts)
