"""
Executor class for executing orders using various strategies.
"""
import logging

from common.interface_order import Order, OrderType
from engine.core.trade_execution import TradeExecution
from engine.remote.remote_order_service_client import RemoteOrderClient

class Executor(TradeExecution):
    def __init__(self, order_type: OrderType, remote_order_client: RemoteOrderClient):
        self.remote_order_client = remote_order_client

        self.order_type = order_type

    def on_signal(self, order: Order):
        logging.info(f"TradeExecution Submitted Order {order} ")
        #TODO slice order in the future or hit the watched price
        self.place_orders(order)

    def place_orders(self, order: Order):
        """
        Place orders using the specified execution strategy.

        :param order: A dictionary of orders to be executed.
        """

        order.order_type = self.order_type
        return self.remote_order_client.submit_order(order)

    def query_order(self, symbol: str, order_id: str):
        """
        Query the status of an order.

        :param order_id: The ID of the order to query.
        :return: The status of the order.
        """

    def place_and_query_order(self, symbol: str, quantity: float, side: bool):
        """
        Place an order and query its status.

        :param symbol: The trading pair symbol.
        :param quantity: The quantity of the asset to trade.
        :param side: True for buy, False for sell.
        :return: The status of the order.
        """
        order_response = self.place_orders(symbol, quantity, side)
        order_id = order_response["orderId"]
        if order_id:
            return self.query_order(symbol, order_id)
        else:
            logging.error("Order placement failed.")
            return None
