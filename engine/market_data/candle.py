from datetime import datetime, timedelta
from typing import Optional, List, Set
from common.interface_book import OrderBook
from typing import Callable
import logging

from common.seriallization import Serializable
from common.time_utils import current_milli_time, convert_epoch_time_to_datetime_millis


class HistoricalMidPriceCandle(Serializable):
    def __init__(self, start_time: int,open,high,low,close):
        self.start_time = start_time
        self.open = open
        self.high = high
        self.low = low
        self.close = close




class MidPriceCandle:
    def __init__(self, start_time: datetime):
        self.start_time = start_time
        self.open: Optional[float] = None
        self.high = float("-inf")
        self.low = float("inf")
        self.close: Optional[float] = None

    def add_tick(self, mid_price: float):
        if self.open is None:
            self.open = mid_price
        self.high = max(self.high, mid_price)
        self.low = min(self.low, mid_price)
        self.close = mid_price

    def to_dict(self) -> dict:
        return {
            "time": self.start_time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }

    def __str__(self):
        def fmt(value):
            return f"{value:.2f}" if value is not None else "None"

        return (
            f"Candle({self.start_time.strftime('%H:%M:%S')} | "
            f"O:{fmt(self.open)} H:{fmt(self.high)} L:{fmt(self.low)} C:{fmt(self.close)})"
        )

def convert_historical_candle_to_mid_candle(historical_candle:HistoricalMidPriceCandle)->MidPriceCandle:
    candle = MidPriceCandle(convert_epoch_time_to_datetime_millis(historical_candle.start_time))
    candle.open = historical_candle.open
    candle.high = historical_candle.high
    candle.low = historical_candle.low
    candle.close = historical_candle.close

    return candle

class CandleAggregator:
    def __init__(self, symbol:str="TEST_SYMBOL", interval_seconds: float = None, interval_milliseconds: int = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        if interval_milliseconds is not None:
            self.interval = timedelta(milliseconds=interval_milliseconds)
        elif interval_seconds is not None:
            self.interval = timedelta(seconds=interval_seconds)
        else:
            raise ValueError("Must provide either interval_seconds or interval_milliseconds")
        self.current_candle: Optional[MidPriceCandle] = None
        # Initialize as an empty set
        self.candle_callbacks: Set[Callable[[MidPriceCandle], None]] = set()

        self.tick_candle_listener: List[Callable[[datetime, float, float, float, float], None]] = []
        self.symbol = symbol

    def on_order_book(self, order_book: OrderBook):
        mid_price = (order_book.get_best_bid() + order_book.get_best_ask()) / 2
        timestamp_sec = order_book.timestamp / 1000.0  # Convert from ms to sec
        self.logger.debug(
            f"Received OrderBook: mid_price={mid_price:.2f}, "
            f"timestamp={timestamp_sec}"
        )
        completed_candle = self._update(timestamp_sec, mid_price)

        if completed_candle:
            self.logger.debug(f"Notifying callback for completed candle")
            self._notify_candle_created(completed_candle)

    def _update(self, timestamp: float, mid_price: float) -> Optional[MidPriceCandle]:
        ts = datetime.fromtimestamp(timestamp)
        interval_sec = self.interval.total_seconds()  # use float, not int

        if interval_sec <= 0:
            raise ValueError("Candle interval must be > 0")

        # Align timestamp to nearest lower multiple of the interval
        candle_start_ts = (ts.timestamp() // interval_sec) * interval_sec
        candle_start = datetime.fromtimestamp(candle_start_ts)

        if self.current_candle is None or candle_start > self.current_candle.start_time:
            finished = self.current_candle
            self.current_candle = MidPriceCandle(start_time=candle_start)
            self.current_candle.add_tick(mid_price)
            if finished:
                self.logger.info(f"🕯️ [{self.symbol}] Completed candle: {finished}")
            return finished
        else:
            self.current_candle.add_tick(mid_price)
            return None

    def pre_load_current_candle(self,current_candle:HistoricalMidPriceCandle):
        converted_candle = convert_historical_candle_to_mid_candle(current_candle)
        self.logger.info(f"Preload current candle [{self.symbol}] candle: {converted_candle}")
        self.current_candle = converted_candle

    def add_candle_created_listener(self, callback: Callable[[MidPriceCandle], None]):
        self.candle_callbacks.add(callback)
        self.logger.info(f"Number of candle callbacks added: %d", len(self.candle_callbacks))

    def replay_candles(self,completed_candle: HistoricalMidPriceCandle):
        converted_candle = convert_historical_candle_to_mid_candle(completed_candle)
        self.logger.info(f"Replaying candle [{self.symbol}] Completed candle: {converted_candle}")
        self._notify_candle_created(converted_candle)

    def _notify_candle_created(self, completed_candle: MidPriceCandle):
        try:
            for callback in self.candle_callbacks:
                callback(completed_candle)
        except Exception as e:
            self.logger.error("Notify Candle Listener raised an exception: %s", e,stack_info=True)


    def add_tick_candle_listener(
        self, callback: Callable[[datetime, float, float, float, float], None]
    ):
        """Register a callback to receive OrderBook updates"""
        self.tick_candle_listener.append(callback)

    def on_candle_update(self, completed_candle: MidPriceCandle):
        timestamp = convert_epoch_time_to_datetime_millis(current_milli_time())
        c_open = completed_candle.open
        c_high = completed_candle.high
        c_low = completed_candle.low
        c_close = completed_candle.close
        for listener in self.tick_candle_listener:
            try:
                listener(timestamp, c_open, c_high, c_low, c_close)
            except Exception as e:
                self.logger.error("Candle Aggregator Listener raised an exception: %s", e)
