# Configuration reference

Copy `.env.example` to `.env` for overrides. Compose has safe local defaults.

| Variable | Default | Used by |
|---|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | local `apex` values | PostgreSQL |
| `DATABASE_URL` | Compose PostgreSQL DSN | API, risk |
| `POSTGRES_PORT` | `55432` | host mapping |
| `ENGINE_HOST`, `ENGINE_PORT`, `ENGINE_WORKERS` | `matching-engine`, `9001`, `4` | API/engine |
| `RISK_URL` | `http://risk-service:8001` | API |
| `RISK_WINDOW_SECONDS` | `60` | risk |
| `RISK_ORDER_RATE_THRESHOLD` | `30` | risk |
| `RISK_CANCEL_RATIO_THRESHOLD` | `0.80` | risk |
| `VITE_API_URL`, `VITE_WS_URL` | localhost public URLs | frontend build |
| `SIM_CHILDREN`, `SIM_EVENTS_PER_CHILD` | `2`, `0` (continuous) | simulator process count/lifetime |
| `SIM_EVENTS_PER_SECOND`, `SIM_VOLATILITY` | `4`, `1.0` | simulator pace/random-walk scale |
| `SIM_SYMBOLS`, `SIM_SEED` | `AAPL,MSFT,NVDA,BTCUSD`, `424242` | simulator markets/reproducibility |
| `SIM_DEPTH_LEVELS`, `SIM_MAX_OPEN_PER_SYMBOL` | `3`, `12` | simulator liquidity bounds |
| `SIM_MAKER_ACCOUNT`, `SIM_TAKER_ACCOUNT` | `3`, `4` | dedicated seeded simulator participants |
| `SIM_INTERVAL_MS` | derived from event rate | optional test/diagnostic pacing override |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | empty | optional explanations |

Never commit `.env`. Changing a Vite URL requires rebuilding the frontend because Vite
embeds it at compile time. Other service variables are read at process start.
