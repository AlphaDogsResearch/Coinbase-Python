import logging

from engine.core.order_manager import OrderManager
from engine.core.strategy import Strategy, StrategyMarketDataType
from engine.execution.executor import Executor
from engine.remote.remote_market_data_client import RemoteMarketDataClient
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode


class StrategyManager:
    def __init__(self, remote_market_data_client: RemoteMarketDataClient, order_manager: OrderManager):
        self.strategies = {}
        self.name = "StrategyManager"
        # todo should change to support different venue
        self.remote_market_data_client = remote_market_data_client

        self.order_manager = order_manager

    def add_strategy(self, strategy: Strategy):
        strategy_id = strategy.name
        if self.strategies.get(strategy_id) is None:
            # add strategy
            self.strategies[strategy_id] = strategy
            strategy.add_signal_listener(self.on_signal)

            if strategy.strategy_market_data_type ==  StrategyMarketDataType.CANDLE:
                candle_agg = strategy.candle_aggregator
                # add tick listener to candle aggregator
                self.remote_market_data_client.add_order_book_listener(strategy.symbol,candle_agg.on_order_book)
                # add candle agg to strategy listener
                candle_agg.add_candle_created_listener(strategy.on_candle_created)
            elif strategy.strategy_market_data_type == StrategyMarketDataType.TICK:
                # add tick listener to strategy directly
                self.remote_market_data_client.add_order_book_listener(strategy.symbol,strategy.on_update)


            logging.info("Added Strategy %s" % strategy_id)
        else:
            logging.info("Strategy already exist, Unable to add Strategy %s" % strategy_id)
            raise ValueError("Strategy already exist, Unable to add Strategy")

    def remove_strategy(self, strategy_id: str):
        self.strategies.pop(strategy_id)
        logging.info("Removed Strategy %s" % strategy_id)

    def on_signal(self, strategy_id: str, signal: int, price: float, symbol: str,
                  strategy_actions: StrategyAction, strategy_order_mode: StrategyOrderMode):
        logging.info("%s on_signal %s price %s symbol %s strategy_actions %s strategy_order_mode %s",
                     strategy_id, signal,
                     price, symbol, strategy_actions,strategy_order_mode)
        self.order_manager.on_signal(strategy_id=strategy_id, signal=signal, price=price, symbol=symbol,
                                     strategy_actions=strategy_actions,strategy_order_mode=strategy_order_mode)
