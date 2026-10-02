from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class OrderCreate(BaseModel):
    client_order_id: UUID = Field(default_factory=uuid4)
    account_id: int = Field(gt=0)
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.]{0,15}$")
    side: Literal["BUY", "SELL"]
    order_type: Literal["LIMIT", "MARKET"]
    quantity: int = Field(gt=0, le=10_000_000)
    price_ticks: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def price_matches_type(self):
        if self.order_type == "LIMIT" and self.price_ticks is None:
            raise ValueError("limit orders require price_ticks")
        if self.order_type == "MARKET" and self.price_ticks is not None:
            raise ValueError("market orders cannot specify price_ticks")
        return self


class Health(BaseModel):
    status: str
    database: str
    matching_engine: str
    risk_service: str


def jsonable_record(row) -> dict:
    value = dict(row)
    for key, item in tuple(value.items()):
        if isinstance(item, datetime):
            value[key] = item.isoformat()
        elif isinstance(item, UUID):
            value[key] = str(item)
        elif key == "metrics" and isinstance(item, str):
            value[key] = json.loads(item)
    return value
