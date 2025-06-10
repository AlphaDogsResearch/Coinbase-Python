from abc import ABC, abstractmethod

from typing import Callable
from common.interface_book import OrderBook


class MarketDataClient(ABC):

    @abstractmethod
    def add_order_book_listener(self, callback: Callable[[OrderBook], None]):
        """
        Register a callback that will be invoked with new OrderBook data.
        """
        pass

    @abstractmethod
    def notify_order_book_listeners(self, book: OrderBook):
        """
        Method to be called when a new OrderBook event is received.
        """
        pass
