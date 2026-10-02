# Database concurrency

## Order reservation

`Database.create_pending` starts a transaction, checks the idempotency UUID, locks the
active account with `SELECT ... FOR UPDATE`, and validates the instrument. A limit buy
moves its maximum cost from available to reserved cash. A sell reads settled position and
sums remaining quantity on active sell orders; it is accepted only when the request is no
greater than `owned - reserved`. The account row serializes concurrent reservations for
that account, so two simultaneous sells cannot both consume the same inventory. The order
is inserted `PENDING` with a PostgreSQL identity. That identity is copied to
`engine_order_id` before commit, so any subsequent execution can resolve the durable maker.

The transaction commits before network I/O. Holding a database row lock while waiting for
another service would increase contention and make failure recovery harder. If the engine
is unavailable, `reject_pending` locks the order, releases its reservation, and marks it
rejected.

## Execution settlement

`Database.settle` runs one transaction for the incoming state, maker decrements, account
cash, both positions, every trade, and the outbox row. A rollback therefore exposes none
of a partial execution.

Affected accounts are locked by ascending ID:

```sql
SELECT id FROM accounts
WHERE id = ANY($1::bigint[])
ORDER BY id
FOR UPDATE;
```

Consistent lock ordering prevents opposing cross-symbol settlements from acquiring A then
B versus B then A. Limit buyers consume reservation at their limit and receive price
improvement back to available cash. Market buyers use a conditional available-cash debit.
Sellers receive an atomic credit.

Buyer position changes use `INSERT ... ON CONFLICT ... DO UPDATE` and expressions based on
the current locked row. Seller changes use a conditional `UPDATE ... WHERE quantity >=
executed_quantity`; this avoids constructing a transient negative insert row and provides
another long-only guard. Both avoid the naive read/compute/write lost update. Database
check constraints are a final backstop against negative balances, negative positions, and
impossible quantities.

The active order is the sell reservation ledger. A partial fill reduces both settled
position quantity and order remaining quantity by the execution amount, leaving available
quantity unchanged. A full fill removes the active reservation. Cancellation changes the
order status inside a locked transaction, making its remaining quantity immediately
available after commit. Rejection likewise leaves no active reservation.

## Executed race tests

`database/tests/test_concurrency.py` and `tests/test_sell_capacity.py` contain real
PostgreSQL/API concurrency tests:

1. 150 concurrent ten-cent debits target a 1,000-cent balance. The atomic update predicate
   permits exactly 100 and rejects 50; a naive application-side balance write could lose
   debits.
2. 200 concurrent upserts increment one position. The final quantity is exactly 200.
3. Two concurrent requests each try to sell an account's entire 100-share position.
   Exactly one receives `201`; the other receives `409`, and PostgreSQL reports 100 shares
   reserved with zero available.

The sell-capacity integration tests also cover insufficient and zero inventory, market
sells, cancellation release, partial and full fills, and the nonnegative-position check.

The tests restore their fixtures and run through `make integration-test` against real
PostgreSQL, not an in-memory replacement. PostgreSQL's default READ COMMITTED isolation is
used with explicit row locks and atomic statements; higher global isolation is not needed
for these invariants.
