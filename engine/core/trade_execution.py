from abc import ABC, abstractmethod

from common.interface_order import Order


class TradeExecution(ABC):
    @abstractmethod
    def place_orders(self, order: Order):
        """
        Send orders to the exchange or broker.
        """
        pass

    @abstractmethod
    def query_order(self, symbol: str, order_id: str):
        """
        Query the status of an order.
        """
        pass

    @abstractmethod
    def place_and_query_order(self, symbol: str, quantity: float, side: bool):
        """
        Place an order and query its status.
        """
        pass
