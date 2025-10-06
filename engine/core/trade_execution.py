from abc import ABC, abstractmethod


class TradeExecution(ABC):
    @abstractmethod
    def place_orders(self, strategy_id: str, symbol: str, quantity: float, side: bool, price: float):
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
