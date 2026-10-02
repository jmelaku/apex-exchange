# API and WebSocket reference

FastAPI publishes the authoritative OpenAPI document at `/openapi.json` and interactive UI
at `/docs`. All bodies are JSON. Prices are integer cents/ticks and quantities are integer
units.

## Submit an order

`POST /orders`

```json
{
  "client_order_id": "optional UUID idempotency key",
  "account_id": 1,
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": 100,
  "price_ticks": 18500
}
```

`price_ticks` is required for `LIMIT` and forbidden for `MARKET`. The response is the
durable order plus a `trades` array. Repeating a `client_order_id` returns the original
durable order without rerouting it. Unfilled market quantity expires with `CANCELLED`
status and never rests.

## Read and control endpoints

- `DELETE /orders/{id}` cancels `NEW` or `PARTIALLY_FILLED` orders.
- `GET /orders/{id}` and `GET /orders?account_id=&limit=` read order state.
- `GET /orderbook/{symbol}?depth=` reads live aggregated levels from C++.
- `GET /trades?limit=` and `GET /trades/{symbol}?limit=` read durable trades.
- `GET /positions/{account_id}`, `/accounts/{account_id}`, `/instruments`, and
  `/risk-events?limit=` read ledger/reference data.
- `GET /health` checks database, engine, and risk; `GET /metrics` returns Prometheus text.

## WebSocket

Connect to `/ws`, consume the initial `system` frame, then send:

```json
{"subscribe": ["market", "trades", "orders", "risk"]}
```

Frames contain `topic` and `data`. `market` is an aggregated snapshot, `trades` is one
committed execution, `orders` is a durable order state, and `risk` is a persisted alert.
Only events sent after commit are broadcast.
