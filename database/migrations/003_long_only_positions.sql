BEGIN;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM positions WHERE quantity < 0) THEN
    RAISE EXCEPTION 'cannot enable long-only positions while negative positions exist'
      USING HINT = 'Reset disposable local demo data with make demo-reset, or reconcile production positions explicitly.';
  END IF;
END $$;

ALTER TABLE positions
  ADD CONSTRAINT positions_quantity_nonnegative CHECK (quantity >= 0);

CREATE INDEX orders_active_sell_reservation_idx
  ON orders(account_id,instrument_id) INCLUDE (remaining_quantity)
  WHERE side='SELL' AND status IN ('PENDING','NEW','PARTIALLY_FILLED');

COMMIT;
