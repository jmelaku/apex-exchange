from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import httpx
import pytest


pytestmark = pytest.mark.integration


def order(account: int, symbol: str, side: str, quantity: int, price: int | None, order_type="LIMIT"):
    payload = {
        "client_order_id": str(uuid.uuid4()),
        "account_id": account,
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
    }
    if price is not None:
        payload["price_ticks"] = price
    return payload


async def snapshot_position(conn, account: int, symbol: str):
    return await conn.fetchrow(
        """SELECT p.* FROM positions p JOIN instruments i ON i.id=p.instrument_id
           WHERE p.account_id=$1 AND i.symbol=$2""",
        account,
        symbol,
    )


async def set_position(conn, account: int, symbol: str, quantity: int, average_price: int):
    await conn.execute(
        """INSERT INTO positions(account_id,instrument_id,quantity,average_price_ticks)
           SELECT $1,id,$3,$4 FROM instruments WHERE symbol=$2
           ON CONFLICT(account_id,instrument_id) DO UPDATE SET
             quantity=EXCLUDED.quantity,average_price_ticks=EXCLUDED.average_price_ticks,
             updated_at=now()""",
        account,
        symbol,
        quantity,
        average_price,
    )


async def restore_position(conn, account: int, symbol: str, original):
    instrument = await conn.fetchval("SELECT id FROM instruments WHERE symbol=$1", symbol)
    await conn.execute("DELETE FROM positions WHERE account_id=$1 AND instrument_id=$2", account, instrument)
    if original:
        await conn.execute(
            """INSERT INTO positions(id,account_id,instrument_id,quantity,average_price_ticks,
                                      realized_pnl_cents,updated_at)
               OVERRIDING SYSTEM VALUE VALUES($1,$2,$3,$4,$5,$6,$7)""",
            original["id"], original["account_id"], original["instrument_id"], original["quantity"],
            original["average_price_ticks"], original["realized_pnl_cents"], original["updated_at"],
        )


async def api_position(client, account: int, symbol: str):
    response = await client.get(f"/positions/{account}")
    assert response.status_code == 200
    return next(item for item in response.json() if item["symbol"] == symbol)


@pytest.mark.asyncio
async def test_long_only_sell_reservation_lifecycle():
    api = os.getenv("API_TEST_URL", "http://localhost:8000")
    database = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(database)
    open_orders: list[int] = []
    async with pool.acquire() as conn:
        seller_original = await snapshot_position(conn, 1, "AAPL")
        buyer_original = await snapshot_position(conn, 2, "AAPL")
        account_rows = await conn.fetch(
            "SELECT id,available_balance_cents,reserved_balance_cents FROM accounts WHERE id=ANY($1::bigint[])",
            [1, 2],
        )
        await set_position(conn, 1, "AAPL", 100, 20000)

    try:
        async with httpx.AsyncClient(base_url=api, timeout=10) as client:
            too_large = await client.post("/orders", json=order(1, "AAPL", "SELL", 101, 900000))
            assert too_large.status_code == 409
            assert too_large.json()["detail"] == "Insufficient available shares: 100 AAPL available to sell."

            resting = await client.post("/orders", json=order(1, "AAPL", "SELL", 100, 900000))
            assert resting.status_code == 201 and resting.json()["status"] == "NEW"
            open_orders.append(resting.json()["id"])
            position = await api_position(client, 1, "AAPL")
            assert (position["quantity"], position["reserved_quantity"], position["available_quantity"]) == (100, 100, 0)

            double_commit = await client.post("/orders", json=order(1, "AAPL", "SELL", 1, 900100))
            assert double_commit.status_code == 409
            assert "0 AAPL available to sell" in double_commit.json()["detail"]

            cancelled = await client.delete(f"/orders/{resting.json()['id']}")
            assert cancelled.status_code == 200
            open_orders.remove(resting.json()["id"])
            position = await api_position(client, 1, "AAPL")
            assert (position["quantity"], position["reserved_quantity"], position["available_quantity"]) == (100, 0, 100)

            partial_sell = await client.post("/orders", json=order(1, "AAPL", "SELL", 80, 76543))
            assert partial_sell.status_code == 201
            open_orders.append(partial_sell.json()["id"])
            partial_buy = await client.post("/orders", json=order(2, "AAPL", "BUY", 30, 76543))
            assert partial_buy.status_code == 201 and len(partial_buy.json()["trades"]) == 1
            position = await api_position(client, 1, "AAPL")
            assert (position["quantity"], position["reserved_quantity"], position["available_quantity"]) == (70, 50, 20)

            cancelled = await client.delete(f"/orders/{partial_sell.json()['id']}")
            assert cancelled.status_code == 200
            open_orders.remove(partial_sell.json()["id"])
            position = await api_position(client, 1, "AAPL")
            assert (position["quantity"], position["reserved_quantity"], position["available_quantity"]) == (70, 0, 70)

            full_sell = await client.post("/orders", json=order(1, "AAPL", "SELL", 70, 76544))
            assert full_sell.status_code == 201
            full_buy = await client.post("/orders", json=order(2, "AAPL", "BUY", 70, 76544))
            assert full_buy.status_code == 201 and len(full_buy.json()["trades"]) == 1
            position = await api_position(client, 1, "AAPL")
            assert (position["quantity"], position["reserved_quantity"], position["available_quantity"]) == (0, 0, 0)

            no_inventory = await client.post("/orders", json=order(1, "AAPL", "SELL", 1, 900000))
            assert no_inventory.status_code == 409
            market_oversell = await client.post("/orders", json=order(1, "AAPL", "SELL", 1, None, "MARKET"))
            assert market_oversell.status_code == 409

        async with pool.acquire() as conn:
            with pytest.raises(asyncpg.CheckViolationError):
                async with conn.transaction():
                    await conn.execute(
                        """UPDATE positions SET quantity=-1 WHERE account_id=1
                           AND instrument_id=(SELECT id FROM instruments WHERE symbol='AAPL')"""
                    )
    finally:
        async with httpx.AsyncClient(base_url=api, timeout=10) as client:
            for order_id in open_orders:
                await client.delete(f"/orders/{order_id}")
        async with pool.acquire() as conn:
            await restore_position(conn, 1, "AAPL", seller_original)
            await restore_position(conn, 2, "AAPL", buyer_original)
            for account in account_rows:
                await conn.execute(
                    """UPDATE accounts SET available_balance_cents=$2,reserved_balance_cents=$3
                       WHERE id=$1""",
                    account["id"], account["available_balance_cents"], account["reserved_balance_cents"],
                )
        await pool.close()


@pytest.mark.asyncio
async def test_concurrent_sell_requests_cannot_double_reserve_inventory():
    api = os.getenv("API_TEST_URL", "http://localhost:8000")
    database = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(database)
    async with pool.acquire() as conn:
        original = await snapshot_position(conn, 1, "MSFT")
        await set_position(conn, 1, "MSFT", 100, 18500)

    accepted_id = None
    try:
        async with httpx.AsyncClient(base_url=api, timeout=10) as client:
            first, second = await asyncio.gather(
                client.post("/orders", json=order(1, "MSFT", "SELL", 100, 900000)),
                client.post("/orders", json=order(1, "MSFT", "SELL", 100, 900100)),
            )
            assert sorted((first.status_code, second.status_code)) == [201, 409]
            accepted = first if first.status_code == 201 else second
            rejected = second if first.status_code == 201 else first
            accepted_id = accepted.json()["id"]
            assert "0 MSFT available to sell" in rejected.json()["detail"]
            position = await api_position(client, 1, "MSFT")
            assert (position["quantity"], position["reserved_quantity"], position["available_quantity"]) == (100, 100, 0)
            cancelled = await client.delete(f"/orders/{accepted_id}")
            assert cancelled.status_code == 200
            accepted_id = None
            position = await api_position(client, 1, "MSFT")
            assert (position["quantity"], position["reserved_quantity"], position["available_quantity"]) == (100, 0, 100)
    finally:
        if accepted_id:
            async with httpx.AsyncClient(base_url=api, timeout=10) as client:
                await client.delete(f"/orders/{accepted_id}")
        async with pool.acquire() as conn:
            await restore_position(conn, 1, "MSFT", original)
        await pool.close()
