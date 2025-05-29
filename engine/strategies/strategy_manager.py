import logging

from common.interface_book import OrderBook
from common.interface_order import Side
from engine.core.strategy import Strategy
from engine.execution.executor import Executor


class StrategyManager:
    def __init__(self, executor: Executor):
        self.strategies = {}
        self.name = "StrategyManager"
        self.executor = executor

    def add_strategy(self, strategy: Strategy):
        strategy_id = strategy.name
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
    def on_signal(self, signal: int):
        if signal == 1:
            self.executor.place_orders("BTCUSDT", 0.1, Side.BUY)
        elif signal == -1:
            self.executor.place_orders("BTCUSDT", 0.1, Side.SELL)

    def on_event(self, mid_price: float):
        for strategy_name, strategy in self.strategies.items():
            try:
                strategy.update(mid_price)
            except Exception as e:
                logging.warning(self.name + " Listener raised an exception: %s", e)
