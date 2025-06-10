from abc import ABC, abstractmethod
from .order import Order

class ExecutionLogger(ABC):
    @abstractmethod
    def log_trade(self, order: Order, status: str, fill_price: float = None):
        """
        Record trade execution results.
        """
        pass
``