"""Real PostgreSQL concurrency tests; requires DATABASE_URL."""
import asyncio
import os

import asyncpg
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_atomic_debits_prevent_lost_update():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(url)
    async with pool.acquire() as conn:
        account = await conn.fetchval("SELECT id FROM accounts ORDER BY id LIMIT 1")
        original = await conn.fetchrow(
            "SELECT available_balance_cents,reserved_balance_cents FROM accounts WHERE id=$1", account
        )
        await conn.execute(
            "UPDATE accounts SET available_balance_cents=1000, reserved_balance_cents=0 WHERE id=$1", account
        )

    async def debit():
        async with pool.acquire() as conn:
            async with conn.transaction():
                # A naive read-modify-write in application code loses updates. This
                # predicate and atomic expression make only affordable debits succeed.
                return await conn.execute(
                    """UPDATE accounts SET available_balance_cents=available_balance_cents-10
                       WHERE id=$1 AND available_balance_cents >= 10""", account
                )

    results = await asyncio.gather(*(debit() for _ in range(150)))
    async with pool.acquire() as conn:
        balance = await conn.fetchval("SELECT available_balance_cents FROM accounts WHERE id=$1", account)
    assert balance == 0
    assert results.count("UPDATE 1") == 100
    assert results.count("UPDATE 0") == 50
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET available_balance_cents=$2,reserved_balance_cents=$3 WHERE id=$1",
            account, original["available_balance_cents"], original["reserved_balance_cents"],
        )
    await pool.close()


@pytest.mark.asyncio
async def test_position_upsert_is_atomic():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(url)
    async with pool.acquire() as conn:
        account = await conn.fetchval("SELECT id FROM accounts ORDER BY id LIMIT 1")
        instrument = await conn.fetchval("SELECT id FROM instruments ORDER BY id LIMIT 1")
        original = await conn.fetchrow(
            "SELECT * FROM positions WHERE account_id=$1 AND instrument_id=$2", account, instrument
        )
        await conn.execute("DELETE FROM positions WHERE account_id=$1 AND instrument_id=$2", account, instrument)

    async def add():
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO positions(account_id,instrument_id,quantity,average_price_ticks)
                   VALUES($1,$2,1,100) ON CONFLICT(account_id,instrument_id) DO UPDATE
                   SET quantity=positions.quantity+EXCLUDED.quantity, updated_at=now()""",
                account, instrument,
            )
    await asyncio.gather(*(add() for _ in range(200)))
    async with pool.acquire() as conn:
        quantity = await conn.fetchval(
            "SELECT quantity FROM positions WHERE account_id=$1 AND instrument_id=$2", account, instrument
        )
    assert quantity == 200
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM positions WHERE account_id=$1 AND instrument_id=$2", account, instrument)
        if original:
            await conn.execute(
                """INSERT INTO positions(account_id,instrument_id,quantity,average_price_ticks,realized_pnl_cents,updated_at)
                   VALUES($1,$2,$3,$4,$5,$6)""", account, instrument, original["quantity"],
                original["average_price_ticks"], original["realized_pnl_cents"], original["updated_at"],
            )
    await pool.close()
