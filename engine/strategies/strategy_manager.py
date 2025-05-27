import logging

from common.identifier import OrderIdGenerator
from common.interface_book import OrderBook
from common.interface_order import Order, OrderType, Side
from engine.core.strategy import Strategy
from engine.remote.remote_order_service_client import RemoteOrderClient


class StrategyManager:
    def __init__(self,remote_order_connection: RemoteOrderClient):
        self.strategies = {}
        self.name = "StrategyManager"
        self.remote_order_connection = remote_order_connection
        self.id_generator = OrderIdGenerator("STRAT")

    def add_strategy(self, strategy_id, strategy: Strategy):

        if self.strategies.get(strategy_id) is None:
            self.strategies[strategy_id] = strategy
            strategy.add_listener(self.on_signal)
            logging.info("Added Strategy %s" % strategy_id)
        else:
            logging.info("Unable to add Strategy %s" % strategy_id)

    def remove_strategy(self, strategy_id: str):
        self.strategies.pop(strategy_id)
        logging.info("Removed Strategy %s" % strategy_id)

    def on_market_data_event(self, order_book: OrderBook):
        best_mid = order_book.get_best_mid()
        self.on_event(best_mid)

    # to be improved
    def on_signal(self,signal:int):
        if signal == 1:
            order_id = self.id_generator.next()
            side = Side.BUY
            order = Order(order_id, side, 0.1, "BTCUSDT", None, OrderType.Market)
            self.remote_order_connection.submit_order(order)
        elif signal == -1:
            order_id = self.id_generator.next()
            side = Side.SELL
            order = Order(order_id, side, 0.1, "BTCUSDT", None, OrderType.Market)
            self.remote_order_connection.submit_order(order)


    def on_event(self, mid_price: float):
        for strategy_name, strategy in self.strategies.items():
            try:
                strategy.update(mid_price)
            except Exception as e:
                logging.warning(self.name+" Listener raised an exception: %s", e)
