import logging
from collections import deque
import numpy as np
from datetime import datetime
from typing import Callable, List, Optional
from engine.market_data.candle import MidPriceCandle


class SMACrossoverInflectionStrategy:
    def __init__(
        self, short_window: int = 5, long_window: int = 200, smoothing_window: int = 10
    ):
        self.name = f"InflectionSMA({short_window},{long_window},{smoothing_window})"
        self.short_window = short_window
        self.long_window = long_window
        self.smoothing_window = smoothing_window

        self.prices = deque(maxlen=long_window + 2)
        self.short_smas = deque(maxlen=2)
        self.long_smas = deque(maxlen=smoothing_window + 2)
        self.long_diffs = deque(maxlen=smoothing_window + 2)

        self.last_smoothed_diff = None
        self.last_position = 0  # Current held position: 1 (long), -1 (short), 0 (flat)

        self.signal_history = []  # Optional for inspection
        self.listeners: List[Callable[[int, float], None]] = []

    def add_signal_listener(self, callback: Callable[[int, float], None]):
        self.listeners.append(callback)

    def on_signal(self, signal: int, price: float):
        for listener in self.listeners:
            try:
                listener(signal, price)
            except Exception as e:
                logging.warning(f"{self.name} listener raised an exception: %s", e)

    def on_candle_created(self, candle: MidPriceCandle):
        logging.info("SMACrossoverInflectionStrategy on_candle_created %s", candle)
        self.update(candle.start_time, candle.close)

    def update(self, timestamp: datetime, price: float) -> Optional[int]:
        self.prices.append(price)

        if len(self.prices) < self.long_window + 1:
            return None

        short_sma = np.mean(list(self.prices)[-self.short_window :])
        long_sma = np.mean(list(self.prices)[-self.long_window :])

        self.short_smas.append(short_sma)
        self.long_smas.append(long_sma)

        if len(self.long_smas) >= 2:
            diff = self.long_smas[-1] - self.long_smas[-2]
            self.long_diffs.append(diff)

        if len(self.long_diffs) < self.smoothing_window + 1:
            return None

        smoothed_diff = np.mean(list(self.long_diffs)[-self.smoothing_window :])
        self.on_signal(0, price)

        if self.last_smoothed_diff is not None:
            inflection_up = self.last_smoothed_diff < 0 and smoothed_diff > 0
            inflection_down = self.last_smoothed_diff > 0 and smoothed_diff < 0

            if inflection_up:
                signal = 1
                self.on_signal(1, price)

            elif inflection_down:
                signal = -1
                self.on_signal(-1, price)
