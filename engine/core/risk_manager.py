from abc import ABC, abstractmethod
from .order import Order

class RiskManager(ABC):
    @abstractmethod
    def validate_order(self, order: Order, aum: float) -> bool:
        """
        Return True if order is within risk limits.
        """
        pass
