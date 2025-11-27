from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from decimal import Decimal
from common.interface_order import Side


class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class TimeInForce(Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class Price(float):
    def __new__(cls, value, precision=None):
        return super().__new__(cls, value)

    @classmethod
    def from_str(cls, value: str):
        return cls(float(value))


class Quantity(float):
    def __new__(cls, value, precision=None):
        return super().__new__(cls, value)

    @classmethod
    def from_str(cls, value: str):
        return cls(float(value))

    def as_double(self):
        return float(self)


@dataclass
class Instrument:
    id: str
    symbol: str
    price_precision: int = 2
    quantity_precision: int = 4
    min_quantity: float = 0.001


@dataclass
class Bar:
    ts_event: int  # Unix timestamp in nanoseconds or milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def timestamp(self) -> int:
        return self.ts_event


@dataclass
class Order:
    id: str
    instrument_id: str
    side: Side  # Using common.interface_order.Side instead of OrderSide
    quantity: float
    type: OrderType
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    tags: List[str] = field(default_factory=list)
    status: str = "PENDING"


@dataclass
class Position:
    instrument_id: str
    side: PositionSide
    quantity: float
    entry_price: float
    unrealized_pnl: float = 0.0

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT

    @property
    def is_flat(self) -> bool:
        return self.side == PositionSide.FLAT or self.quantity == 0


@dataclass
class Trade:
    id: str
    order_id: str
    instrument_id: str
    side: Side  # Using common.interface_order.Side instead of OrderSide
    quantity: float
    price: float
    timestamp: int
    commission: float = 0.0
