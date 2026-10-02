from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pythonjsonlogger.json import JsonFormatter

from .config import get_settings
from .database import Database, DomainError
from .engine import EngineClient, EngineUnavailable
from .models import Health, OrderCreate
from .websocket import WebSocketHub

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=get_settings().log_level, handlers=[handler], force=True)
log = logging.getLogger("apex.api")

ORDERS = Counter("apex_orders_total", "Orders submitted", ["status"])
TRADES = Counter("apex_trades_total", "Trades committed")
LATENCY = Histogram("apex_order_latency_seconds", "End-to-end order latency")
WS_CONNECTIONS = Gauge("apex_websocket_connections", "Open WebSocket clients")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.db = Database(settings.database_url)
    await app.state.db.connect()
    app.state.engine = EngineClient(settings.engine_host, settings.engine_port)
    app.state.hub = WebSocketHub()
    # Engine and durable settlement are sequenced together per symbol. Independent
    # symbols still progress concurrently, matching the engine's own shard model.
    app.state.symbol_locks = defaultdict(asyncio.Lock)
    app.state.http = httpx.AsyncClient(timeout=1.5)
    log.info("service_started")
    yield
    await app.state.http.aclose()
    await app.state.db.close()
    log.info("service_stopped")


app = FastAPI(title="APEX Exchange API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def notify_risk(request: Request, event: dict):
    try:
        response = await request.app.state.http.post(get_settings().risk_url + "/events", json=event)
        response.raise_for_status()
        for risk_event in response.json().get("risk_events", []):
            await request.app.state.hub.broadcast("risk", risk_event)
    except Exception as exc:
        log.warning("risk_service_unavailable", extra={"error": str(exc)})


@app.post("/orders", status_code=201)
async def create_order(order: OrderCreate, request: Request):
    started = time.perf_counter()
    db, engine, hub = request.app.state.db, request.app.state.engine, request.app.state.hub
    try:
        pending, created = await db.create_pending(order)
        if not created:
            # client_order_id is an idempotency key; never submit it twice to the engine.
            return pending
        async with request.app.state.symbol_locks[order.symbol]:
            try:
                result = await engine.submit(order, pending["id"])
            except EngineUnavailable as exc:
                await db.reject_pending(pending["id"], "matching engine unavailable")
                ORDERS.labels("engine_unavailable").inc()
                raise HTTPException(503, "matching engine unavailable") from exc
            if not result.get("ok"):
                await db.reject_pending(pending["id"], result.get("error", "engine rejected order"))
                ORDERS.labels("rejected").inc()
                raise HTTPException(422, result.get("error", "engine rejected order"))
            durable, trades = await db.settle(pending["id"], result)
        ORDERS.labels(durable["status"].lower()).inc()
        TRADES.inc(len(trades))
        await hub.broadcast("orders", durable)
        for trade in trades:
            await hub.broadcast("trades", trade)
        book = await engine.book(order.symbol)
        await hub.broadcast("market", book)
        asyncio.create_task(notify_risk(request, {
            "event_type": "ORDER", "account_id": order.account_id, "symbol": order.symbol,
            "side": order.side, "quantity": order.quantity, "trades": len(trades),
            "cancelled": durable["status"] == "CANCELLED",
        }))
        log.info("order_committed", extra={"order_id": durable["id"], "trades": len(trades)})
        return {**durable, "trades": trades}
    except DomainError as exc:
        ORDERS.labels("rejected").inc()
        raise HTTPException(409, str(exc)) from exc
    finally:
        LATENCY.observe(time.perf_counter() - started)


@app.delete("/orders/{order_id}")
async def cancel_order(order_id: int, request: Request):
    db, engine = request.app.state.db, request.app.state.engine
    order = await db.get_order(order_id)
    if not order:
        raise HTTPException(404, "order not found")
    if not order.get("engine_order_id"):
        raise HTTPException(409, "order has not reached the engine")
    try:
        async with request.app.state.symbol_locks[order["symbol"]]:
            result = await engine.cancel(order["symbol"], order["engine_order_id"])
            if not result.get("ok"):
                raise HTTPException(409, result.get("error", "engine rejected cancellation"))
            cancelled = await db.cancel(order_id)
    except EngineUnavailable as exc:
        raise HTTPException(503, "matching engine unavailable") from exc
    except DomainError as exc:
        raise HTTPException(409, str(exc)) from exc
    await request.app.state.hub.broadcast("orders", cancelled)
    asyncio.create_task(notify_risk(request, {
        "event_type": "CANCEL", "account_id": cancelled["account_id"],
        "symbol": cancelled["symbol"], "quantity": cancelled["remaining_quantity"], "cancelled": True,
    }))
    return cancelled


@app.get("/orders")
async def orders(request: Request, account_id: int | None = None, limit: int = Query(100, ge=1, le=500)):
    return await request.app.state.db.list_orders(account_id, limit)


@app.get("/orders/{order_id}")
async def order(order_id: int, request: Request):
    value = await request.app.state.db.get_order(order_id)
    if not value:
        raise HTTPException(404, "order not found")
    return value


@app.get("/orderbook/{symbol}")
async def orderbook(symbol: str, request: Request, depth: int = Query(20, ge=1, le=100)):
    try:
        result = await request.app.state.engine.book(symbol.upper(), depth)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error"))
        return result
    except EngineUnavailable as exc:
        raise HTTPException(503, "matching engine unavailable") from exc


@app.get("/trades")
async def trades(request: Request, limit: int = Query(100, ge=1, le=500)):
    return await request.app.state.db.list_trades(None, limit)


@app.get("/trades/{symbol}")
async def symbol_trades(symbol: str, request: Request, limit: int = Query(100, ge=1, le=500)):
    return await request.app.state.db.list_trades(symbol.upper(), limit)


@app.get("/positions/{account_id}")
async def positions(account_id: int, request: Request):
    return await request.app.state.db.list_simple("positions", account_id)


@app.get("/accounts/{account_id}")
async def account(account_id: int, request: Request):
    rows = await request.app.state.db.list_simple("accounts", account_id)
    if not rows:
        raise HTTPException(404, "account not found")
    return rows[0]


@app.get("/instruments")
async def instruments(request: Request):
    return await request.app.state.db.list_simple("instruments")


@app.get("/risk-events")
async def risk_events(request: Request, limit: int = Query(100, ge=1, le=500)):
    return await request.app.state.db.list_simple("risk_events", limit=limit)


@app.get("/health", response_model=Health)
async def health(request: Request):
    database, engine = await asyncio.gather(
        request.app.state.db.healthy(), request.app.state.engine.health()
    )
    risk = False
    try:
        risk = (await request.app.state.http.get(get_settings().risk_url + "/health")).is_success
    except Exception:
        pass
    return Health(
        status="healthy" if database and engine else "degraded",
        database="up" if database else "down",
        matching_engine="up" if engine else "down",
        risk_service="up" if risk else "down",
    )


@app.get("/metrics")
async def metrics(request: Request):
    WS_CONNECTIONS.set(request.app.state.hub.connection_count)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.websocket("/ws")
async def websocket(socket: WebSocket):
    hub: WebSocketHub = socket.app.state.hub
    client = await hub.connect(socket)
    try:
        await socket.send_json({"topic": "system", "data": {"status": "connected"}})
        while True:
            message = json.loads(await socket.receive_text())
            if "subscribe" in message and isinstance(message["subscribe"], list):
                client.subscriptions = set(message["subscribe"])
                await socket.send_json({"topic": "system", "data": {"subscriptions": sorted(client.subscriptions)}})
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        await hub.disconnect(client)
