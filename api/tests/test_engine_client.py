import asyncio

import pytest

from api.app.engine import EngineClient


@pytest.mark.asyncio
async def test_engine_line_protocol_round_trip():
    async def handler(reader, writer):
        assert await reader.readline() == b"PING\n"
        writer.write(b'{"ok":true}\n')
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    client = EngineClient("127.0.0.1", server.sockets[0].getsockname()[1])
    assert await client.health()
    server.close()
    await server.wait_closed()
