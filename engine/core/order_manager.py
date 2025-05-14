from abc import ABC, abstractmethod
from .order import Order

class OrderManager(ABC):
    @abstractmethod
    def queue_orders(self, orders: dict):
        """
        Add new orders to execution queue.
        """
        pass

    @abstractmethod
    def cancel_order(self, asset: str):
        """
        Cancel a specific order if it hasn't been placed.
        """
        pass

    @abstractmethod
    def get_queued_orders(self) -> dict:
        """
        Return all orders pending execution.
        """
        pass
