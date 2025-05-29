import logging
from typing import Callable, List

from engine.core.strategy import Strategy


class SMAStrategy(Strategy):
    def __init__(self, short_window: int, long_window: int):
        super().__init__()
        self.short_window = short_window
        self.long_window = long_window
        self.name = "SMA-" + str(self.short_window) + "-" + str(self.long_window)
        self.prices = []
        self.listeners: List[Callable[[int], None]] = []  # list of callbacks
        self.signal = 0

    def moving_average(self, window: int):
        if len(self.prices) < window:
            return None
        return sum(self.prices[-window:]) / window

    def add_listener(self, callback: Callable[[int], None]):
        self.listeners.append(callback)

    def on_signal(self, signal: int):
        for listener in self.listeners:
            try:
                listener(signal)
            except Exception as e:
                logging.warning(self.name + " Listener raised an exception: %s", e)

    def update(self, price: float):
        self.prices.append(price)

        short_sma = self.moving_average(self.short_window)
        long_sma = self.moving_average(self.long_window)

        if short_sma is None or long_sma is None:
            self.signal = 0
        elif short_sma > long_sma:
            if self.signal == 1:
                return
            self.signal = 1
            logging.info("%s changed signal to %d, current short %f current long %f", self.name, self.signal, short_sma,
                         long_sma)
            self.on_signal(self.signal)

        elif short_sma < long_sma:
            if self.signal == -1:
                return
            self.signal = -1
            logging.info("%s changed signal to %d, current short %f current long %f", self.name, self.signal, short_sma,
                         long_sma)
            self.on_signal(self.signal)

        else:
            self.signal = 0
