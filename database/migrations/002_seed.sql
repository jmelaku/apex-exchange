INSERT INTO users (email, display_name) VALUES
  ('alice@apex.local', 'Alice Trader'),
  ('bob@apex.local', 'Bob Trader'),
  ('sim-maker@apex.local', 'Simulation Market Maker'),
  ('sim-taker@apex.local', 'Simulation Liquidity Taker')
ON CONFLICT (email) DO NOTHING;

INSERT INTO accounts (user_id, name, available_balance_cents)
SELECT id, 'Primary', 100000000 FROM users WHERE email = 'alice@apex.local'
ON CONFLICT (user_id, name) DO NOTHING;
INSERT INTO accounts (user_id, name, available_balance_cents)
SELECT id, 'Market Making', 100000000 FROM users WHERE email = 'bob@apex.local'
ON CONFLICT (user_id, name) DO NOTHING;
INSERT INTO accounts (user_id, name, available_balance_cents)
SELECT id, 'Simulation Maker', 1000000000 FROM users WHERE email = 'sim-maker@apex.local'
ON CONFLICT (user_id, name) DO NOTHING;
INSERT INTO accounts (user_id, name, available_balance_cents)
SELECT id, 'Simulation Taker', 1000000000 FROM users WHERE email = 'sim-taker@apex.local'
ON CONFLICT (user_id, name) DO NOTHING;

INSERT INTO instruments (symbol, name, tick_size_cents) VALUES
  ('AAPL', 'Apple Inc.', 1), ('MSFT', 'Microsoft Corp.', 1),
  ('NVDA', 'NVIDIA Corp.', 1), ('BTCUSD', 'Bitcoin / US Dollar', 1)
ON CONFLICT (symbol) DO NOTHING;

WITH holdings(email,symbol,quantity,average_price_ticks) AS (VALUES
  ('alice@apex.local','AAPL',1000::bigint,20000::numeric),
  ('alice@apex.local','MSFT',1000::bigint,18500::numeric),
  ('alice@apex.local','NVDA',1000::bigint,20000::numeric),
  ('alice@apex.local','BTCUSD',10::bigint,6000000::numeric),
  ('bob@apex.local','AAPL',1000::bigint,20000::numeric),
  ('bob@apex.local','MSFT',1000::bigint,18500::numeric),
  ('bob@apex.local','NVDA',1000::bigint,20000::numeric),
  ('bob@apex.local','BTCUSD',10::bigint,6000000::numeric),
  ('sim-maker@apex.local','AAPL',100000::bigint,20000::numeric),
  ('sim-maker@apex.local','MSFT',100000::bigint,18500::numeric),
  ('sim-maker@apex.local','NVDA',100000::bigint,20000::numeric),
  ('sim-maker@apex.local','BTCUSD',1000::bigint,6000000::numeric),
  ('sim-taker@apex.local','AAPL',100000::bigint,20000::numeric),
  ('sim-taker@apex.local','MSFT',100000::bigint,18500::numeric),
  ('sim-taker@apex.local','NVDA',100000::bigint,20000::numeric),
  ('sim-taker@apex.local','BTCUSD',1000::bigint,6000000::numeric)
)
INSERT INTO positions(account_id,instrument_id,quantity,average_price_ticks)
SELECT a.id,i.id,h.quantity,h.average_price_ticks
FROM holdings h
JOIN users u ON u.email=h.email
JOIN accounts a ON a.user_id=u.id
JOIN instruments i ON i.symbol=h.symbol
ON CONFLICT (account_id,instrument_id) DO NOTHING;
