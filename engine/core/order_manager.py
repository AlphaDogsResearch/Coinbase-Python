from abc import ABC, abstractmethod
from typing import Optional

from .order import Order
from engine.strategies.strategy_action import StrategyAction


class OrderManager(ABC):

    @abstractmethod
    def on_signal(self, strategy_id: str, signal: int, price: float, symbol: str, trade_unit: float,
                  strategy_actions:StrategyAction) -> bool:
        """
        Do Something on signal
        """
        pass

    @abstractmethod
    def _process_orders(self):
        """
        Add new orders to execution queue.
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[str]:
        """
        Cancel a specific order if it hasn't been placed.
        """
        pass
