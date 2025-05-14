from abc import ABC, abstractmethod
from .order import Order

class PortfolioManager(ABC):
    @abstractmethod
    def evaluate_signals(self, signals: dict, aum: float) -> dict:
        """
        Determine position sizing and filter based on capital and risk.
        Returns: dict of Order objects: {"BTCUSDT": Order(...), ...}
        """
        pass

    @abstractmethod
    def rollback_unplaced_orders(self):
        """
        Revert or clear unexecuted orders.
        """
        pass
