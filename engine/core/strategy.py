import datetime
from abc import abstractmethod, ABC
from enum import Enum
from typing import Callable, Optional, List
from common.interface_order import Side, OrderType

from common.interface_book import OrderBook
from engine.market_data.candle import MidPriceCandle, CandleAggregator


class Strategy(ABC):
    def __init__(
        self,
        symbol: str,
        candle_aggregator: Optional[CandleAggregator] = None,
    ):

        self.signal = 0  # -1 = sell, 0 = hold, 1 = buy
        self.name = ""
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
    def add_submit_order_listener(
        self,
        callback: Callable[[str, Side, OrderType, float, float, str, List[str]], bool],
    ):
        raise NotImplementedError("Must implement add_submit_order_listener() in subclass")

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
