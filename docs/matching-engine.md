# Matching engine

## Model and data structures

`engine/include/apex/types.hpp` defines `Order`, `Trade`, `Instrument`, statuses, and book
snapshots. Prices and quantities are signed 64-bit integer ticks/units; the engine never
compares floating point prices.

`OrderBook` stores bids in `std::map<price, list<Order>, greater<>>` and asks in ascending
`std::map`. The first map node is therefore always the best price. Each price owns a
`std::list`, so insertion at the tail and removal from the head implement FIFO. An
`unordered_map<Id, Locator>` points to the exact list iterator for cancellation.

- best-price access: O(1) after map begin
- new/resting insertion: O(log P), where P is the number of price levels
- known-order cancellation: O(log P) plus constant-time list erase
- match: O(F + removed price levels log P), where F is fills produced
- depth snapshot: O(D + orders aggregated in those levels)

## Matching

`OrderBook::submit` validates the order, places it in the archive, and calls the templated
`match` against asks for a buy or bids for a sell. Market orders cross any available
price. Limits cross only when the resting price satisfies their limit. The trade price is
always the older resting order's price. Partial quantities update both orders; a zero
remaining quantity removes the resting locator and FIFO node.

An unfilled limit rests. An unfilled market remainder is cancelled immediately. If the
best resting order belongs to the incoming account, self-trade prevention cancels the
incoming order rather than creating artificial volume or jumping past FIFO priority.

## Invariants

`OrderBook::check_invariants` verifies positive prices/remaining quantities, remaining not
above original quantity, side/price consistency, a locator for every resting order, no
inactive resting state, and an uncrossed book. `tests/test_engine.cpp` covers price
priority, FIFO, partial fills, market expiry, cancellation, bad input, protocol IDs, and an
8-thread/8,000-order multi-symbol stress run.

`MatchingEngine` uses process-wide atomics for default order/trade IDs. Trade IDs reserve
one million sequence values per process-start epoch millisecond, avoiding collisions when
PostgreSQL persists across an engine restart. Public API orders
provide their durable database identity; a compare/exchange advances the local sequence
past explicit IDs. Every symbol is deterministically hashed to one worker, so the book is
single-writer without internal book locks while different shards execute concurrently.
