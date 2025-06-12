from collections import deque
import numpy as np
import datetime


class InflectionSMACrossoverStrategy:
    def __init__(self, long_window=200, smoothing_window=10):
        self.long_window = long_window
        self.smoothing_window = smoothing_window

        self.long_sma_history = deque(maxlen=long_window + 1)
        self.slope_history = deque(maxlen=smoothing_window + 2)

        self.last_smoothed_slope = None
        self.last_signal = 0
        self.signals = []  # (timestamp, signal)

    def _update(self, timestamp: datetime, close_price: float):
        self.long_sma_history.append(close_price)

        if len(self.long_sma_history) < self.long_window + 1:
            return

        sma_current = np.mean(list(self.long_sma_history)[-self.long_window :])
        sma_prev = np.mean(list(self.long_sma_history)[-self.long_window - 1 : -1])

        slope = sma_current - sma_prev
        self.slope_history.append(slope)

        if len(self.slope_history) < self.smoothing_window + 1:
            return

        smoothed_slope = np.mean(list(self.slope_history)[-self.smoothing_window :])

        signal = 0
        if self.last_smoothed_slope is not None:
            if self.last_smoothed_slope < 0 and smoothed_slope > 0:
                signal = 1
            elif self.last_smoothed_slope > 0 and smoothed_slope < 0:
                signal = -1

        self.last_smoothed_slope = smoothed_slope

        if signal != 0 and signal != self.last_signal:
            self.signals.append((timestamp, signal))
            self.last_signal = signal
