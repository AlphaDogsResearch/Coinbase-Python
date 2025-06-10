import logging

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
            strategy.add_signal_listener(self.on_signal)
            logging.info("Added Strategy %s" % strategy_id)
        else:
            logging.info("Unable to add Strategy %s" % strategy_id)

    def remove_strategy(self, strategy_id: str):
        self.strategies.pop(strategy_id)
        logging.info("Removed Strategy %s" % strategy_id)

    def on_signal(self, signal: int, price: float):
        logging.info("StrategyManager on_signal %s", signal)
        self.executor.on_signal(signal=signal, price=price)
