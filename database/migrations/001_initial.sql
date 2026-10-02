BEGIN;

CREATE TABLE users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE accounts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')),
    available_balance_cents BIGINT NOT NULL CHECK (available_balance_cents >= 0),
    reserved_balance_cents BIGINT NOT NULL DEFAULT 0 CHECK (reserved_balance_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE TABLE instruments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE CHECK (symbol ~ '^[A-Z][A-Z0-9.]{0,15}$'),
    name TEXT NOT NULL,
    tick_size_cents BIGINT NOT NULL DEFAULT 1 CHECK (tick_size_cents > 0),
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    engine_order_id BIGINT UNIQUE,
    client_order_id UUID NOT NULL UNIQUE,
    account_id BIGINT NOT NULL REFERENCES accounts(id),
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type TEXT NOT NULL CHECK (order_type IN ('LIMIT', 'MARKET')),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    remaining_quantity BIGINT NOT NULL CHECK (remaining_quantity >= 0 AND remaining_quantity <= quantity),
    price_ticks BIGINT CHECK (price_ticks > 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED')),
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((order_type = 'LIMIT' AND price_ticks IS NOT NULL) OR (order_type = 'MARKET' AND price_ticks IS NULL))
);

CREATE TABLE trades (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    engine_trade_id BIGINT NOT NULL UNIQUE,
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    buy_order_id BIGINT NOT NULL REFERENCES orders(id),
    sell_order_id BIGINT NOT NULL REFERENCES orders(id),
    buyer_account_id BIGINT NOT NULL REFERENCES accounts(id),
    seller_account_id BIGINT NOT NULL REFERENCES accounts(id),
    price_ticks BIGINT NOT NULL CHECK (price_ticks > 0),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    executed_at TIMESTAMPTZ NOT NULL,
    CHECK (buyer_account_id <> seller_account_id)
);

CREATE TABLE positions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES accounts(id),
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    quantity BIGINT NOT NULL DEFAULT 0,
    average_price_ticks NUMERIC(20,4) NOT NULL DEFAULT 0 CHECK (average_price_ticks >= 0),
    realized_pnl_cents BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, instrument_id)
);

CREATE TABLE risk_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES accounts(id),
    category TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    explanation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE outbox_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

CREATE INDEX orders_account_status_idx ON orders(account_id, status);
CREATE INDEX orders_instrument_created_idx ON orders(instrument_id, created_at DESC);
CREATE INDEX trades_instrument_executed_idx ON trades(instrument_id, executed_at DESC);
CREATE INDEX trades_buyer_idx ON trades(buyer_account_id, executed_at DESC);
CREATE INDEX trades_seller_idx ON trades(seller_account_id, executed_at DESC);
CREATE INDEX risk_events_account_created_idx ON risk_events(account_id, created_at DESC);
CREATE INDEX outbox_unpublished_idx ON outbox_events(id) WHERE published_at IS NULL;

COMMIT;
