from dataclasses import dataclass

@dataclass
class Order:
    asset: str
    quantity: float
    price: float = None
    order_type: str = "market"
