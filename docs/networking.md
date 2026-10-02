# Networking and event contracts

## Public interfaces

The browser uses JSON REST on port 8000 and `/ws` for push events. CORS permits the local
Vite/nginx development origins. WebSocket clients send, for example,
`{"subscribe":["market","trades","risk"]}`. Server frames have
`{"topic":"trades","data":{...}}`; dead sockets are removed without affecting commits.

The REST schema and interactive contract are generated at `/docs`. Important response
codes are 201 for accepted orders, 422 for engine/domain validation, 409 for state or cash
conflicts, 404 for missing records, and 503 for matching-engine unavailability.

## API-to-engine protocol

The private engine interface is newline framed over TCP port 9001. Fields are pipe
separated because the bounded domain values cannot contain that character; replies are
one-line JSON. `api/app/engine.py` opens a connection, sends one command, reads one line,
and applies a timeout.

```text
PING
NEW|engine_id|client_uuid|account|symbol|BUY|LIMIT|quantity|price_ticks
CANCEL|symbol|engine_id
GET|symbol|engine_id
BOOK|symbol|depth
STATS
```

This explicit service protocol keeps C++ in its own failure/process boundary and is easier
to observe and containerize than in-process bindings. Production evolution would use a
versioned binary schema and authenticated/mTLS network.

## Internal routing

Compose DNS names (`postgres`, `matching-engine`, `risk-service`, `api`) are used inside a
single bridge network. Only developer-facing ports are published. API risk delivery is
post-commit and best-effort; trading remains available during risk outages. The database
outbox is the durable basis for replacing this HTTP notification with Kafka/NATS later.
