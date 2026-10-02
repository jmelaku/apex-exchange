import asyncio
import os
import uuid

import httpx
import pytest
import websockets

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_order_trade_position_and_websocket():
    api = os.getenv("API_TEST_URL", "http://localhost:8000")
    ws_url = api.replace("http", "ws", 1) + "/ws"
    async with websockets.connect(ws_url) as socket, httpx.AsyncClient(base_url=api, timeout=10) as client:
        await socket.recv()
        await socket.send('{"subscribe":["trades"]}')
        await socket.recv()
        price = 31415
        seller_positions = (await client.get("/positions/2")).json()
        assert any(p["symbol"] == "NVDA" and p["available_quantity"] >= 3 for p in seller_positions)
        sell = await client.post("/orders", json={"client_order_id": str(uuid.uuid4()), "account_id": 2,
            "symbol": "NVDA", "side": "SELL", "order_type": "LIMIT", "quantity": 3, "price_ticks": price})
        assert sell.status_code == 201, sell.text
        buy = await client.post("/orders", json={"client_order_id": str(uuid.uuid4()), "account_id": 1,
            "symbol": "NVDA", "side": "BUY", "order_type": "LIMIT", "quantity": 3, "price_ticks": price})
        assert buy.status_code == 201, buy.text
        assert len(buy.json()["trades"]) == 1
        event = await asyncio.wait_for(socket.recv(), 3)
        assert '"topic":"trades"' in event.replace(" ", "")
        positions = (await client.get("/positions/1")).json()
        assert any(p["symbol"] == "NVDA" and p["quantity"] >= 3 for p in positions)
