from __future__ import annotations

import asyncio
import json


class EngineUnavailable(RuntimeError):
    pass


class EngineClient:
    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.host, self.port, self.timeout = host, port, timeout

    async def command(self, command: str) -> dict:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
            writer.write((command + "\n").encode())
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), self.timeout)
            writer.close()
            await writer.wait_closed()
            if not raw:
                raise EngineUnavailable("matching engine closed the connection")
            return json.loads(raw)
        except (OSError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
            raise EngineUnavailable(str(exc)) from exc

    async def submit(self, order, engine_order_id: int) -> dict:
        price = "" if order.price_ticks is None else str(order.price_ticks)
        return await self.command(
            f"NEW|{engine_order_id}|{order.client_order_id}|{order.account_id}|{order.symbol}|{order.side}|"
            f"{order.order_type}|{order.quantity}|{price}"
        )

    async def cancel(self, symbol: str, engine_id: int) -> dict:
        return await self.command(f"CANCEL|{symbol}|{engine_id}")

    async def book(self, symbol: str, depth: int = 20) -> dict:
        return await self.command(f"BOOK|{symbol}|{depth}")

    async def health(self) -> bool:
        try:
            return (await self.command("PING")).get("ok", False)
        except EngineUnavailable:
            return False

    async def stats(self) -> dict:
        return await self.command("STATS")
