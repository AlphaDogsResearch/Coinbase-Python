from datetime import datetime, timedelta
from typing import Optional, List
from common.interface_book import OrderBook
from typing import Callable
import logging

from common.time_utils import current_milli_time, convert_epoch_time_to_datetime_millis


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


class CandleAggregator:
    def __init__(self, *, interval_seconds: float = None, interval_milliseconds: int = None):
        if interval_milliseconds is not None:
            self.interval = timedelta(milliseconds=interval_milliseconds)
        elif interval_seconds is not None:
            self.interval = timedelta(seconds=interval_seconds)
        else:
            raise ValueError("Must provide either interval_seconds or interval_milliseconds")
        self.current_candle: Optional[MidPriceCandle] = None
        self.candle_callback: Optional[Callable[[MidPriceCandle], None]] = None

        self.tick_candle_listener: List[Callable[[datetime, float, float, float, float], None]] = []

    def on_order_book(self, order_book: OrderBook):
        mid_price = (order_book.get_best_bid() + order_book.get_best_ask()) / 2
        timestamp_sec = order_book.timestamp / 1000.0  # Convert from ms to sec
        logging.debug(
            f"[CandleAggregator] Received OrderBook: mid_price={mid_price:.2f}, "
            f"timestamp={timestamp_sec}"
        )
        completed_candle = self._update(timestamp_sec, mid_price)

        if completed_candle:
            logging.debug(f"[CandleAggregator] Notifying callback for completed candle")
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
                logging.info(f"🕯️ [CandleAggregator] Completed candle: {finished}")
            return finished
        else:
            self.current_candle.add_tick(mid_price)
            return None

    def add_candle_created_listener(self, callback: Callable[[MidPriceCandle], None]):
        self.candle_callback = callback

    def _notify_candle_created(self, completed_candle: MidPriceCandle):
        if self.candle_callback:
            self.candle_callback(completed_candle)
            self.on_candle_update(completed_candle)

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
                logging.error("Candle Aggregator Listener raised an exception: %s", e)
