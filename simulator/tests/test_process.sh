#!/bin/sh
set -eu
output="$(SIM_CHILDREN=2 SIM_EVENTS_PER_CHILD=3 SIM_INTERVAL_MS=1 SIM_DRY_RUN=1 "$1" 2>&1)"
events="$(printf '%s\n' "$output" | grep -cE '^ORDER\|[34]\|(AAPL|MSFT|NVDA|BTCUSD)\|(BUY|SELL)\|(LIMIT|MARKET)\|')"
reaped="$(printf '%s\n' "$output" | grep -c 'child_reaped')"
[ "$events" -eq 6 ]
[ "$reaped" -eq 2 ]
printf '%s\n' "fork/pipe process test passed: $events events, $reaped children reaped"

recovery="$(SIM_CHILDREN=1 SIM_EVENTS_PER_CHILD=3 SIM_INTERVAL_MS=1 SIM_DRY_RUN=1 SIMULATE_CHILD_FAILURE=1 "$1" 2>&1)"
restarted="$(printf '%s\n' "$recovery" | grep -c 'child_started')"
reaped="$(printf '%s\n' "$recovery" | grep -c 'child_reaped')"
[ "$restarted" -eq 2 ]
[ "$reaped" -eq 2 ]
printf '%s\n' "abnormal-child recovery passed: $restarted starts, $reaped children reaped"

market="$(SIM_CHILDREN=1 SIM_SYMBOLS=AAPL SIM_EVENTS_PER_CHILD=80 SIM_INTERVAL_MS=1 \
  SIM_DRY_RUN=1 SIM_SEED=7 "$1" 2>&1)"
cancels="$(printf '%s\n' "$market" | grep -c '^CANCEL|3|AAPL')"
out_of_range="$(printf '%s\n' "$market" | awk -F'|' \
  '/^ORDER/ && $5 == "LIMIT" && ($7 < 19500 || $7 > 20500) { count++ } END { print count + 0 }')"
[ "$cancels" -gt 0 ]
[ "$out_of_range" -eq 0 ]
printf '%s\n' "bounded-market policy passed: $cancels cancellation intents, no extreme AAPL prices"
