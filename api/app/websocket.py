from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass(eq=False)
class Client:
    socket: WebSocket
    subscriptions: set[str] = field(default_factory=lambda: {"market", "trades", "risk", "orders"})


class WebSocketHub:
    def __init__(self):
        self.clients: set[Client] = set()
        self.lock = asyncio.Lock()

    async def connect(self, socket: WebSocket) -> Client:
        await socket.accept()
        client = Client(socket)
        async with self.lock:
            self.clients.add(client)
        return client

    async def disconnect(self, client: Client):
        async with self.lock:
            self.clients.discard(client)

    async def broadcast(self, topic: str, payload: dict):
        async with self.lock:
            targets = [c for c in self.clients if topic in c.subscriptions or "*" in c.subscriptions]
        dead = []
        for client in targets:
            try:
                await client.socket.send_json({"topic": topic, "data": payload})
            except Exception:
                dead.append(client)
        for client in dead:
            await self.disconnect(client)

    @property
    def connection_count(self) -> int:
        return len(self.clients)
