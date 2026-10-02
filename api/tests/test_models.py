import pytest
from pydantic import ValidationError

from api.app.models import OrderCreate


def test_limit_requires_price():
    with pytest.raises(ValidationError):
        OrderCreate(account_id=1, symbol="AAPL", side="BUY", order_type="LIMIT", quantity=10)


def test_market_rejects_price():
    with pytest.raises(ValidationError):
        OrderCreate(account_id=1, symbol="AAPL", side="BUY", order_type="MARKET", quantity=10, price_ticks=100)


def test_valid_limit_order():
    value = OrderCreate(account_id=1, symbol="AAPL", side="SELL", order_type="LIMIT", quantity=10, price_ticks=100)
    assert value.symbol == "AAPL" and value.quantity == 10
