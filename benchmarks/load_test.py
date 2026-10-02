#!/usr/bin/env python3
"""Concurrent HTTP benchmark. Writes only measurements observed in this run."""
import argparse
import asyncio
import json
import math
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1)]


async def run(args):
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies, statuses = [], {}
    trades = 0
    symbols = ["AAPL", "MSFT", "NVDA", "BTCUSD"][: args.symbols]
    async with httpx.AsyncClient(base_url=args.url, timeout=15) as client:
        health = await client.get("/health")
        health.raise_for_status()

        async def submit(index):
            nonlocal trades
            async with semaphore:
                side = "SELL" if index % 2 == 0 else "BUY"
                payload = {"client_order_id": str(uuid.uuid4()), "account_id": 2 if side == "SELL" else 1,
                           "symbol": symbols[(index // 2) % len(symbols)], "side": side,
                           "order_type": "LIMIT", "quantity": 1, "price_ticks": 20000}
                before = time.perf_counter_ns()
                response = await client.post("/orders", json=payload)
                latencies.append((time.perf_counter_ns() - before) / 1_000_000)
                statuses[str(response.status_code)] = statuses.get(str(response.status_code), 0) + 1
                if response.is_success:
                    trades += len(response.json().get("trades", []))

        started = time.perf_counter()
        await asyncio.gather(*(submit(i) for i in range(args.orders)))
        elapsed = time.perf_counter() - started
    result = {"measured_at": datetime.now(timezone.utc).isoformat(), "url": args.url,
              "orders_attempted": args.orders, "concurrency": args.concurrency,
              "symbol_count": len(symbols), "elapsed_seconds": round(elapsed, 6),
              "orders_per_second": round(args.orders / elapsed, 2),
              "trades_observed": trades, "trades_per_second": round(trades / elapsed, 2),
              "latency_ms": {"mean": round(statistics.mean(latencies), 3),
                             "p50": round(percentile(latencies, 50), 3),
                             "p95": round(percentile(latencies, 95), 3),
                             "p99": round(percentile(latencies, 99), 3)}, "http_statuses": statuses}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--orders", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--symbols", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--output", default="benchmark-results/latest.json")
    asyncio.run(run(parser.parse_args()))
