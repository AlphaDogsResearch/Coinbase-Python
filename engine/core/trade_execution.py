from abc import ABC, abstractmethod
from .order import Order

class TradeExecution(ABC):
    @abstractmethod
    def place_orders(self, orders: dict):
        """
        Send orders to the exchange or broker.
        """
        pass
