from abc import ABC, abstractmethod
from .order import Order

class PositionTracker(ABC):
    @abstractmethod
    def update_position(self, order: Order, fill_price: float):
        """
        Update live positions after a trade.
        """
        pass

    @abstractmethod
    def get_positions(self) -> dict:
        """
        Return current positions.
        """
        pass

    @abstractmethod
    def get_pnl(self) -> dict:
        """
        Return current PnL (realized/unrealized).
        """
        pass
