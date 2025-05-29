"""
Executor class for executing orders using various strategies.
"""
import logging

from common.identifier import OrderIdGenerator
from common.interface_order import Side, Order, OrderType
from engine.core.trade_execution import TradeExecution
from engine.remote.remote_order_service_client import RemoteOrderClient


class Executor(TradeExecution):
    def __init__(self, remote_order_client: RemoteOrderClient):
        self.remote_order_client = remote_order_client
        self.id_generator = OrderIdGenerator("STRAT")

    def place_orders(self, symbol: str, quantity: float, side: Side):
        """
        Place orders using the specified execution strategy.

        :param order: A dictionary of orders to be executed.
        """

        order_id = self.id_generator.next()
        order = Order(order_id, side, 0.1, "BTCUSDT", None, OrderType.Market)
        self.remote_order_client.submit_order(order)

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
        order_id = order_response['orderId']
        if order_id:
            return self.query_order(symbol, order_id)
        else:
            logging.error("Order placement failed.")
            return None
