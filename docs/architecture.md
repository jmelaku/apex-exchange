# Architecture

## Runtime services

`frontend` is an nginx-served React bundle. `api` is the public control plane and owns
validation, idempotency, reservation, durable settlement, event fan-out, and dependency
health. `matching-engine` is the only component that decides matches. `risk-service`
maintains rolling account features and writes alerts. PostgreSQL is the durable ledger.
The opt-in simulator is deliberately process-oriented rather than another permanent
microservice.

## Submit flow

```mermaid
sequenceDiagram
  participant C as Client
  participant A as FastAPI
  participant D as PostgreSQL
  participant E as C++ engine
  participant R as Risk
  C->>A: POST /orders (client_order_id)
  A->>D: transaction: account FOR UPDATE, reserve, insert PENDING
  D-->>A: database order ID
  A->>A: acquire per-symbol lock
  A->>E: NEW with database ID
  E->>E: enqueue on symbol shard; match FIFO
  E-->>A: order state + trades
  A->>D: transaction: sorted account locks, cash, orders, trades, positions, outbox
  D-->>A: commit
  A-->>C: 201 durable result
  A-->>C: WebSocket committed events
  A->>R: actual account activity
  R->>D: insert risk event when anomalous
```

The first transaction never spans a network call. It makes `client_order_id` idempotent,
reserves limit-buy cash or validates uncommitted long inventory for a sell, and publishes
the future engine ID. Active sell orders and their remaining quantities form the share
reservation ledger. The per-symbol lock in `api/app/main.py` ensures engine processing and
database settlement preserve the same symbol order. Engine worker sharding still permits
unrelated symbols to proceed in parallel. Settlement in `api/app/database.py` locks all
affected accounts in ascending ID order and performs cash, trade, order, position, and
outbox changes atomically.

## Failure boundaries

- An unreachable engine causes the pending order to become `REJECTED` and releases cash.
- PostgreSQL constraints prevent negative balances or positions, invalid quantities,
  invalid states, and duplicate IDs. Failed settlement rolls back as a unit.
- Risk notification is after commit and best-effort; matching remains available if risk is
  down. The durable trading result never depends on an optional model/API.
- WebSocket failures remove the dead client and do not roll back committed business data.
- `client_order_id` suppresses duplicate engine routing.
- A transaction failure after the engine accepts but before settlement is the difficult
  dual-write window. The outbox provides durable committed events, but full engine command
  replay/reconciliation is future work.

## Why these boundaries

One engine service keeps matching deterministic and reviewable. FastAPI is well suited to
I/O coordination and WebSockets but does no matching. PostgreSQL is used where durability
and contention correctness matter. Risk is separated because analysis can scale/fail
independently. The simulator uses processes because it models isolated external feeds and
demonstrates lifecycle isolation that threads cannot provide.
