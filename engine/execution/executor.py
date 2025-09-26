"""
Executor class for executing orders using various strategies.
"""
import logging
import math


from common.identifier import OrderIdGenerator
from common.interface_order import Side, Order, OrderType
from common.time_utils import current_milli_time
from engine.core.trade_execution import TradeExecution
from engine.remote.remote_order_service_client import RemoteOrderClient
from engine.risk.risk_manager import RiskManager
from common.config_symbols import TRADING_SYMBOLS


class Executor(TradeExecution):
    def __init__(self,order_type:OrderType, remote_order_client: RemoteOrderClient, risk_manager: RiskManager):
        self.remote_order_client = remote_order_client
        self.id_generator = OrderIdGenerator("STRAT")
        self.order_type = order_type
        self.risk_manager = risk_manager

    def on_signal(self, signal: int,price:float):
        print(f"TradeExecution on_signal: {signal} price {price}")
        # decide what to do with signal
        #round to 1 dp
        var_signal = self.risk_manager.get_portfolio_var_assessment() #TODO: Handle var signal
        symbol = TRADING_SYMBOLS[0]
        if signal == 1:
            rounded_down_price = math.floor(price * 10) / 10
            self.place_orders(symbol, 0.001, Side.BUY, rounded_down_price)
        elif signal == -1:
            rounded_up_price = math.ceil(price * 10) / 10
            self.place_orders(symbol, 0.001, Side.SELL, rounded_up_price)

    def place_orders(self, symbol: str, quantity: float, side: Side, price: float):
        """
        Place orders using the specified execution strategy.

        :param order: A dictionary of orders to be executed.
        """
        order_id = self.id_generator.next()
        order = Order(order_id, side, quantity, symbol, current_milli_time(), self.order_type, price)
        # Risk check before submitting order
        if self.risk_manager and not self.risk_manager.validate_order(order):
            logging.warning(f"Order blocked by risk manager: {order}")
            return None
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
