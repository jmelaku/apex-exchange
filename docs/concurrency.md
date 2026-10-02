# Concurrency

## Engine threads

`MatchingEngine::Worker` owns a mutex, condition variable, FIFO of closures, book map, stop
flag, and thread. Submit/cancel/read calls create a `packaged_task`, lock only long enough
to enqueue it, notify the worker, and return a future. The worker waits with a predicate,
removes one task under RAII lock, releases the lock, then executes it. Work never runs
while the queue mutex is held.

Stable `hash(symbol) % workers` sharding gives one writer per book and concurrency across
symbols. Atomics count IDs, orders, and trades without putting global state behind the
book locks. Destruction marks every worker stopping, broadcasts, drains queued work, and
joins every thread.

Without the mutex, concurrent producers could corrupt `std::queue`; without the predicate
and condition variable, workers would either spin or miss wakeups. No task needs more than
one worker lock, which removes engine lock-order cycles.

## API and database concurrency

`api/app/main.py` has an asyncio lock per symbol covering engine submission through durable
settlement. This closed a real high-load race where order N+1 could match order N before
N's engine identity committed. Locks for different symbols are independent.

Within settlement, affected accounts are selected `ORDER BY id FOR UPDATE`. Consistent
ordering prevents A→B and B→A transactions from deadlocking. The same account lock also
serializes sell-capacity checks against the active-order reservation ledger, so concurrent
sells cannot reserve the same shares. Buyer position quantities use `INSERT ... ON
CONFLICT DO UPDATE`; seller quantities use a conditional nonnegative `UPDATE`, so
executions cannot overwrite one another or create a short position.

The `database/tests/test_concurrency.py` debit test explains the lost-update alternative:
two clients that read 100, both subtract 10 locally, and both write 90 lose one debit.
APEX instead issues an atomic conditional `UPDATE ... balance=balance-10 WHERE balance>=10`.
In the executed 150-client test, exactly 100 debits succeed against a 1,000-cent balance.

## Testing and race tooling

The normal engine test sends 8,000 synchronous futures from eight producer threads and
checks counters and uncrossed snapshots. CMake exposes `-DENABLE_TSAN=ON`, which adds
ThreadSanitizer compile/link instrumentation. Sanitizer execution is platform/toolchain-
dependent and was not part of the recorded final validation, so no TSan result is claimed.
