# Processes and IPC

The opt-in simulator in `simulator/src/main.cpp` models isolated external market-data/order
feeds. Its parent creates a pipe for each feed and then calls `fork()`. The child closes the
read end, owns a subset of configured symbols, maintains a bounded random-walk midpoint,
and writes newline-framed order/cancellation intents smaller than `PIPE_BUF`. Demo children
run continuously; finite process tests set `SIM_EVENTS_PER_CHILD` and exit with `_exit()`.

The parent closes every write end and uses `poll()` across read descriptors, so a slow feed
does not block other children. Complete frames are transformed into JSON and sent to
real `POST /orders` or `DELETE /orders/{id}` requests over TCP HTTP. The parent records IDs
of resting orders returned by FastAPI so child cancellation intents target genuine engine
orders. The supervisor logs parent/child PIDs, closes
descriptors at EOF, calls `waitpid()`, records exit status, and restarts abnormal children
at most twice. On SIGINT/SIGTERM it signals remaining children, closes pipes, and reaps
them, avoiding zombies and descriptor leaks.

```text
supervisor
  ├─ fork → feed child 0 ─ write(pipe 0) ─┐
  ├─ fork → feed child 1 ─ write(pipe 1) ─┼─ poll/read → HTTP → API
  └─ waitpid/restart/terminate             ┘
```

Processes are appropriate here because feeds have independent failure domains and may
later host native vendor libraries. A crashing generator cannot corrupt the supervisor's
address space. Threads are used inside the engine instead, where low-cost shared in-memory
access is valuable.

Each symbol starts with several bid and ask levels from the configured maker account
(account 3 by default). Thereafter the feed mixes resting liquidity, tracked cancellations,
crossing orders, and occasional market orders from the configured taker account (account 4
by default). Both have separately seeded demo cash and long inventory, and neither bypasses
the normal reservation rules. Every execution therefore comes from the matching engine;
the simulator never writes PostgreSQL or publishes WebSocket messages. Reference prices
are synthetic and intentionally bounded around AAPL $200, MSFT $185, NVDA $200, and
BTCUSD $60,000.

Run the deterministic IPC test with `make test-process`. It verifies frames, reaping,
abnormal-child recovery, cancellation intents, and bounded AAPL prices. Run the live demo
with `make demo`. Set `SIMULATE_CHILD_FAILURE=1` to exercise bounded restart behavior.
