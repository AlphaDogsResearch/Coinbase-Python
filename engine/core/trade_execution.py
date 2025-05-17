from abc import ABC, abstractmethod
from .order import Order

class TradeExecution(ABC):
    @abstractmethod
    def place_orders(self, key: str, secret: str, sym: str, quantity: float, side: bool):
        """
        Send orders to the exchange or broker.
        """
        pass
