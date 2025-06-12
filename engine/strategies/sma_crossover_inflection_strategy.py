from collections import deque
import numpy as np
from datetime import datetime
from typing import Optional

from engine.core.strategy import Strategy


class SMACrossoverInflectionStrategy(Strategy):
    def __init__(
        self, short_window: int = 5, long_window: int = 200, smoothing_window: int = 10
    ):
        self.short_window = short_window
        self.long_window = long_window
        self.smoothing_window = smoothing_window

        self.prices = deque(maxlen=long_window + 2)
        self.short_smas = deque(maxlen=2)
        self.long_smas = deque(maxlen=smoothing_window + 2)
        self.long_diffs = deque(maxlen=smoothing_window + 2)

        self.last_smoothed_diff = None
        self.last_position = 0  # Current held position: 1 (long), -1 (short), 0 (flat)

        self.signal_history = []  # Optional for debugging or inspection

    def update(self, timestamp: datetime, price: float) -> Optional[int]:
        self.prices.append(price)

        if len(self.prices) < self.long_window:
            return None  # Not enough data to compute SMAs

        short_sma = np.mean(list(self.prices)[-self.short_window :])
        long_sma = np.mean(list(self.prices)[-self.long_window :])

        self.short_smas.append(short_sma)
        self.long_smas.append(long_sma)

        # Compute long_diff = long_sma_t - long_sma_t-1
        if len(self.long_smas) >= 2:
            diff = self.long_smas[-1] - self.long_smas[-2]
            self.long_diffs.append(diff)

        if len(self.long_diffs) < self.smoothing_window + 1:
            return None  # Not enough data to compute smoothed diff

        smoothed_diff = np.mean(list(self.long_diffs)[-self.smoothing_window :])

        signal = 0
        if self.last_smoothed_diff is not None:
            inflection_up = self.last_smoothed_diff < 0 and smoothed_diff > 0
            inflection_down = self.last_smoothed_diff > 0 and smoothed_diff < 0

            if inflection_up:
                signal = 1
            elif inflection_down:
                signal = -1

        self.last_smoothed_diff = smoothed_diff

        if signal != 0:
            self.last_position = signal
            self.signal_history.append((timestamp, signal))
            return signal  # Emit position change
        else:
            return None  # No new signal this step

    def current_position(self):
        return self.last_position
