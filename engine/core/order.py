from dataclasses import dataclass

@dataclass
class Order:
    symbol: str
    side: str
    quantity: float
    price: float = None
    order_type: str = "market"

    def __getitem__(self, item):
        return getattr(self, item)