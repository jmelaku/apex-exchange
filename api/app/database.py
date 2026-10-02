from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg

from .models import jsonable_record


class DomainError(RuntimeError):
    pass


ORDER_SELECT = """
SELECT o.*, i.symbol FROM orders o JOIN instruments i ON i.id=o.instrument_id
"""


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.url, min_size=2, max_size=20, command_timeout=10)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def healthy(self) -> bool:
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval("SELECT 1") == 1
        except Exception:
            return False

    async def create_pending(self, order) -> tuple[dict, bool]:
        async with self.pool.acquire() as conn, conn.transaction():
            prior = await conn.fetchrow(ORDER_SELECT + " WHERE o.client_order_id=$1", order.client_order_id)
            if prior:
                return jsonable_record(prior), False
            account = await conn.fetchrow(
                "SELECT * FROM accounts WHERE id=$1 AND status='ACTIVE' FOR UPDATE", order.account_id
            )
            if not account:
                raise DomainError("active account not found")
            instrument = await conn.fetchrow(
                "SELECT * FROM instruments WHERE symbol=$1 AND active=true", order.symbol
            )
            if not instrument:
                raise DomainError("active instrument not found")
            if order.side == "SELL":
                owned = await conn.fetchval(
                    """SELECT COALESCE(quantity, 0) FROM positions
                       WHERE account_id=$1 AND instrument_id=$2""",
                    order.account_id, instrument["id"],
                )
                owned = owned or 0
                reserved = await conn.fetchval(
                    """SELECT COALESCE(SUM(remaining_quantity), 0) FROM orders
                       WHERE account_id=$1 AND instrument_id=$2 AND side='SELL'
                         AND status IN ('PENDING','NEW','PARTIALLY_FILLED')""",
                    order.account_id, instrument["id"],
                )
                available = owned - (reserved or 0)
                if order.quantity > available:
                    raise DomainError(
                        f"Insufficient available shares: {available} {order.symbol} available to sell."
                    )
            reserve = order.quantity * order.price_ticks if order.side == "BUY" and order.order_type == "LIMIT" else 0
            if account["available_balance_cents"] < reserve:
                raise DomainError("insufficient available balance")
            if reserve:
                await conn.execute(
                    """UPDATE accounts SET available_balance_cents=available_balance_cents-$2,
                       reserved_balance_cents=reserved_balance_cents+$2, updated_at=now() WHERE id=$1""",
                    order.account_id, reserve,
                )
            row = await conn.fetchrow(
                """INSERT INTO orders(client_order_id,account_id,instrument_id,side,order_type,
                       quantity,remaining_quantity,price_ticks,status)
                   VALUES($1,$2,$3,$4,$5,$6,$6,$7,'PENDING') RETURNING *""",
                order.client_order_id, order.account_id, instrument["id"], order.side,
                order.order_type, order.quantity, order.price_ticks,
            )
            row = await conn.fetchrow(
                "UPDATE orders SET engine_order_id=id WHERE id=$1 RETURNING *", row["id"]
            )
            value = jsonable_record(row)
            value["symbol"] = order.symbol
            return value, True

    async def reject_pending(self, order_id: int, reason: str):
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not row or row["status"] != "PENDING":
                return
            release = row["remaining_quantity"] * row["price_ticks"] if row["side"] == "BUY" and row["price_ticks"] else 0
            if release:
                await conn.execute(
                    """UPDATE accounts SET available_balance_cents=available_balance_cents+$2,
                       reserved_balance_cents=reserved_balance_cents-$2,updated_at=now() WHERE id=$1""",
                    row["account_id"], release,
                )
            await conn.execute(
                "UPDATE orders SET status='REJECTED',rejection_reason=$2,updated_at=now() WHERE id=$1",
                order_id, reason[:500],
            )

    async def settle(self, database_order_id: int, result: dict) -> tuple[dict, list[dict]]:
        engine_order = result["order"]
        trades = result.get("trades", [])
        async with self.pool.acquire() as conn, conn.transaction():
            incoming = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", database_order_id)
            if not incoming or incoming["status"] != "PENDING":
                raise DomainError("order is no longer pending")
            account_ids = {incoming["account_id"]}
            for trade in trades:
                account_ids.update((trade["buyer_account_id"], trade["seller_account_id"]))
            # Every settlement uses the same lock order, preventing cross-symbol deadlocks.
            await conn.fetch(
                "SELECT id FROM accounts WHERE id=ANY($1::bigint[]) ORDER BY id FOR UPDATE", sorted(account_ids)
            )
            await conn.execute(
                """UPDATE orders SET engine_order_id=$2,remaining_quantity=$3,status=$4,
                   rejection_reason=$5,updated_at=now() WHERE id=$1""",
                database_order_id, engine_order["id"], engine_order["remaining_quantity"],
                engine_order["status"], result.get("error"),
            )
            persisted = []
            for trade in trades:
                buy = await conn.fetchrow("SELECT * FROM orders WHERE engine_order_id=$1", trade["buy_order_id"])
                sell = await conn.fetchrow("SELECT * FROM orders WHERE engine_order_id=$1", trade["sell_order_id"])
                if not buy or not sell:
                    raise DomainError("engine trade references an unknown durable order")
                for matched in (buy, sell):
                    if matched["id"] != database_order_id:
                        await conn.execute(
                            """UPDATE orders SET remaining_quantity=remaining_quantity-$2,
                               status=CASE WHEN remaining_quantity-$2=0 THEN 'FILLED' ELSE 'PARTIALLY_FILLED' END,
                               updated_at=now() WHERE id=$1 AND remaining_quantity >= $2""",
                            matched["id"], trade["quantity"],
                        )
                cost = trade["price_ticks"] * trade["quantity"]
                if buy["order_type"] == "LIMIT":
                    reserved = buy["price_ticks"] * trade["quantity"]
                    status = await conn.execute(
                        """UPDATE accounts SET reserved_balance_cents=reserved_balance_cents-$2,
                           available_balance_cents=available_balance_cents+($2-$3),updated_at=now()
                           WHERE id=$1 AND reserved_balance_cents >= $2""",
                        buy["account_id"], reserved, cost,
                    )
                else:
                    status = await conn.execute(
                        """UPDATE accounts SET available_balance_cents=available_balance_cents-$2,updated_at=now()
                           WHERE id=$1 AND available_balance_cents >= $2""", buy["account_id"], cost
                    )
                if status != "UPDATE 1":
                    raise DomainError("buyer has insufficient settled funds")
                await conn.execute(
                    "UPDATE accounts SET available_balance_cents=available_balance_cents+$2,updated_at=now() WHERE id=$1",
                    sell["account_id"], cost,
                )
                await conn.execute(
                    """INSERT INTO positions(account_id,instrument_id,quantity,average_price_ticks)
                       VALUES($1,$2,$3,$4) ON CONFLICT(account_id,instrument_id) DO UPDATE SET
                       average_price_ticks=CASE WHEN positions.quantity + EXCLUDED.quantity > 0
                         THEN ((GREATEST(positions.quantity,0)*positions.average_price_ticks)+
                              (EXCLUDED.quantity*EXCLUDED.average_price_ticks))/
                              (GREATEST(positions.quantity,0)+EXCLUDED.quantity)
                         ELSE positions.average_price_ticks END,
                       quantity=positions.quantity+EXCLUDED.quantity,updated_at=now()""",
                    buy["account_id"], incoming["instrument_id"], trade["quantity"], trade["price_ticks"],
                )
                seller_position = await conn.execute(
                    """UPDATE positions SET quantity=quantity-$3,updated_at=now()
                       WHERE account_id=$1 AND instrument_id=$2 AND quantity >= $3""",
                    sell["account_id"], incoming["instrument_id"], trade["quantity"],
                )
                if seller_position != "UPDATE 1":
                    raise DomainError("seller has insufficient settled shares")
                executed = datetime.fromtimestamp(trade["executed_at_ms"] / 1000, timezone.utc)
                row = await conn.fetchrow(
                    """INSERT INTO trades(engine_trade_id,instrument_id,buy_order_id,sell_order_id,
                       buyer_account_id,seller_account_id,price_ticks,quantity,executed_at)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
                    trade["id"], incoming["instrument_id"], buy["id"], sell["id"],
                    buy["account_id"], sell["account_id"], trade["price_ticks"], trade["quantity"], executed,
                )
                persisted.append(jsonable_record(row))
            if engine_order["status"] == "CANCELLED" and incoming["side"] == "BUY" and incoming["price_ticks"]:
                release = engine_order["remaining_quantity"] * incoming["price_ticks"]
                await conn.execute(
                    """UPDATE accounts SET reserved_balance_cents=reserved_balance_cents-$2,
                       available_balance_cents=available_balance_cents+$2,updated_at=now()
                       WHERE id=$1 AND reserved_balance_cents >= $2""",
                    incoming["account_id"], release,
                )
            event = {"order_id": database_order_id, "engine_order_id": engine_order["id"], "trades": persisted}
            await conn.execute(
                "INSERT INTO outbox_events(topic,aggregate_id,payload) VALUES('order.settled',$1,$2::jsonb)",
                str(database_order_id), json.dumps(event),
            )
            row = await conn.fetchrow(ORDER_SELECT + " WHERE o.id=$1", database_order_id)
            return jsonable_record(row), persisted

    async def cancel(self, order_id: int) -> dict:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(ORDER_SELECT + " WHERE o.id=$1 FOR UPDATE OF o", order_id)
            if not row:
                raise DomainError("order not found")
            if row["status"] not in ("NEW", "PARTIALLY_FILLED"):
                raise DomainError("order is not cancellable")
            release = row["remaining_quantity"] * row["price_ticks"] if row["side"] == "BUY" and row["price_ticks"] else 0
            if release:
                await conn.execute(
                    """UPDATE accounts SET reserved_balance_cents=reserved_balance_cents-$2,
                       available_balance_cents=available_balance_cents+$2,updated_at=now()
                       WHERE id=$1 AND reserved_balance_cents >= $2""", row["account_id"], release
                )
            updated = await conn.fetchrow(
                "UPDATE orders SET status='CANCELLED',updated_at=now() WHERE id=$1 RETURNING *", order_id
            )
            value = jsonable_record(updated); value["symbol"] = row["symbol"]
            return value

    async def get_order(self, order_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(ORDER_SELECT + " WHERE o.id=$1", order_id)
            return jsonable_record(row) if row else None

    async def list_orders(self, account_id: int | None = None, limit: int = 100):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                ORDER_SELECT + (" WHERE o.account_id=$1" if account_id else "") +
                " ORDER BY o.created_at DESC LIMIT $" + ("2" if account_id else "1"),
                *((account_id, limit) if account_id else (limit,)),
            )
            return [jsonable_record(r) for r in rows]

    async def list_trades(self, symbol: str | None, limit: int):
        async with self.pool.acquire() as conn:
            sql = """SELECT t.*,i.symbol FROM trades t JOIN instruments i ON i.id=t.instrument_id"""
            args = (limit,)
            if symbol:
                sql += " WHERE i.symbol=$1 ORDER BY t.executed_at DESC LIMIT $2"; args = (symbol, limit)
            else:
                sql += " ORDER BY t.executed_at DESC LIMIT $1"
            return [jsonable_record(r) for r in await conn.fetch(sql, *args)]

    async def list_simple(self, table: str, where_id: int | None = None, limit: int = 100):
        allowed = {"accounts", "instruments", "positions", "risk_events"}
        if table not in allowed:
            raise ValueError("invalid table")
        async with self.pool.acquire() as conn:
            if table == "positions":
                rows = await conn.fetch(
                    """WITH sell_reservations AS (
                           SELECT account_id,instrument_id,SUM(remaining_quantity)::bigint AS reserved_quantity
                           FROM orders
                           WHERE side='SELL' AND status IN ('PENDING','NEW','PARTIALLY_FILLED')
                           GROUP BY account_id,instrument_id
                       )
                       SELECT p.*,i.symbol,COALESCE(r.reserved_quantity,0)::bigint AS reserved_quantity,
                              (p.quantity-COALESCE(r.reserved_quantity,0))::bigint AS available_quantity
                       FROM positions p JOIN instruments i ON i.id=p.instrument_id
                       LEFT JOIN sell_reservations r
                         ON r.account_id=p.account_id AND r.instrument_id=p.instrument_id
                       WHERE p.account_id=$1 ORDER BY i.symbol""", where_id
                )
            elif table == "accounts":
                rows = await conn.fetch("SELECT * FROM accounts WHERE id=$1", where_id)
            else:
                rows = await conn.fetch(f"SELECT * FROM {table} ORDER BY id DESC LIMIT $1", limit)
            return [jsonable_record(r) for r in rows]
