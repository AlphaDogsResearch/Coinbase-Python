from dataclasses import dataclass

from common.interface_order import OrderType

@dataclass
class Order:
    symbol: str
    side: str
    quantity: float
    price: float = None
    order_type: str = OrderType.Market

    def __getitem__(self, item):
        return getattr(self, item)