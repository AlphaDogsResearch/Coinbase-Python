import datetime
from enum import Enum
from typing import Callable, Optional

from common.interface_book import OrderBook
from engine.market_data.candle import MidPriceCandle, CandleAggregator


class Strategy:
    def __init__(self,symbol:str,candle_aggregator: Optional[CandleAggregator] = None):
        self.signal = 0  # -1 = sell, 0 = hold, 1 = buy
        self.name = ""
        self.symbol = symbol
        self.candle_aggregator = candle_aggregator
        if candle_aggregator is None:
            self.strategy_market_data_type = StrategyMarketDataType.TICK
        else:
            self.strategy_market_data_type = StrategyMarketDataType.CANDLE

    def on_candle_created(self, candle: MidPriceCandle):
        raise NotImplementedError("Must implement on_candle_created() in subclass")

    def add_signal_listener(self, callback: Callable[[str,int, float], None]):
        raise NotImplementedError("Must implement add_signal_listener() in subclass")

    def add_tick_signal_listener(self, callback: Callable[[datetime.datetime,int, float], None]):
        raise NotImplementedError(
            "Must implement _notify_signal_generated() in subclass"
        )

    def on_update(self, order_book: OrderBook):
        raise NotImplementedError("Must implement on_update() in subclass")

class StrategyMarketDataType(Enum):
    TICK = "TICK"
    CANDLE = "CANDLE"