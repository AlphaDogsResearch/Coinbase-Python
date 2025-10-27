import datetime
from abc import abstractmethod, ABC
from enum import Enum
from typing import Callable, Optional

from common.interface_book import OrderBook
from engine.market_data.candle import MidPriceCandle, CandleAggregator
from engine.strategies.strategy_action import StrategyAction
from engine.strategies.strategy_order_mode import StrategyOrderMode


class Strategy(ABC):
    def __init__(self, symbol: str, strategy_actions: StrategyAction,
                 strategy_order_mode: StrategyOrderMode,
                 candle_aggregator: Optional[CandleAggregator] = None):
        self.signal = 0  # -1 = sell, 0 = hold, 1 = buy
        self.name = ""
        '''
        trade unit is different from qty as min qty can change by price
        e.g.  ETHUSDC min qty is 0.006 whereas XRPUSDC min qty is 0.001 due to min notional differences so we standardise by using trade unit
        '''
        self.strategy_order_mode = strategy_order_mode
        self.strategy_actions = strategy_actions


        self.symbol = symbol
        self.candle_aggregator = candle_aggregator
        if candle_aggregator is None:
            self.strategy_market_data_type = StrategyMarketDataType.TICK
        else:
            self.strategy_market_data_type = StrategyMarketDataType.CANDLE

    @abstractmethod
    def on_candle_created(self, candle: MidPriceCandle):
        raise NotImplementedError("Must implement on_candle_created() in subclass")

    @abstractmethod
    def add_signal_listener(self, callback: Callable[[str, int, float, str, StrategyAction,StrategyOrderMode], None]):
        raise NotImplementedError("Must implement add_signal_listener() in subclass")

    @abstractmethod
    def add_plot_signal_listener(self, callback: Callable[[datetime.datetime, int, float], None]):
        raise NotImplementedError(
            "Must implement _notify_signal_generated() in subclass"
        )

    @abstractmethod
    def on_update(self, order_book: OrderBook):
        raise NotImplementedError("Must implement on_update() in subclass")

    def start(self):
        pass

    def stop(self):
        pass


class StrategyMarketDataType(Enum):
    TICK = "TICK"
    CANDLE = "CANDLE"
