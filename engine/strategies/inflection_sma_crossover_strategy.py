from collections import deque
from typing import Callable
from engine.core.strategy import Strategy
from engine.market_data.candle import MidPriceCandle

import logging


class InflectionSMACrossoverStrategy(Strategy):
    def __init__(self, short_window: int = 5, long_window: int = 200):
        super().__init__()
        self.name = f"SMA({short_window},{long_window})"
        self.short_window = short_window
        self.long_window = long_window
        self.prices = deque(maxlen=long_window)
        self.last_short_sma = None
        self.last_long_sma = None
        self.listeners = []
        self.last_signal = 0  # Track to avoid duplicate signal spam

    def add_signal_listener(self, callback: Callable[[int, float], None]):
        self.listeners.append(callback)

    def on_signal(self, signal: int, price: float):
        for callback in self.listeners:
            callback(signal, price)

    def on_candle_created(self, candle: MidPriceCandle):
        logging.info("InflectionSMACrossoverStrategy on_candle_created %s", candle)
        self._update(candle.close)

    def _update(self, price: float):
        self.prices.append(price)

        if len(self.prices) < self.long_window:
            self.signal = 0
            return  # Not enough data to compute both SMAs

        short_sma = sum(list(self.prices)[-self.short_window :]) / self.short_window
        long_sma = sum(self.prices) / self.long_window

        # Determine crossover
        signal = 0
        if self.last_short_sma is not None and self.last_long_sma is not None:
            crossed_above = (
                self.last_short_sma < self.last_long_sma and short_sma > long_sma
            )
            crossed_below = (
                self.last_short_sma > self.last_long_sma and short_sma < long_sma
            )

            if crossed_above:
                signal = 1  # Buy
            elif crossed_below:
                signal = -1  # Sell

        self.last_short_sma = short_sma
        self.last_long_sma = long_sma

        if signal != 0 and signal != self.last_signal:
            self.signal = signal
            self.last_signal = signal
            self.on_signal(signal, price)
        else:
            self.signal = 0  # No action
