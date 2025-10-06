import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, List, Optional

import numpy as np

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
        self.listeners: List[Callable[[str,int, float], None]] = []

        self.tick_signal_listeners: List[Callable[[datetime, int, float], None]] = []  # list of callbacks
        self.tick_sma_listeners: List[Callable[[datetime, float], None]] = []  # list of callbacks
        self.tick_sma2_listeners: List[Callable[[datetime, float], None]] = []  # list of callbacks

        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="SMACROSS")

    def add_signal_listener(self, callback: Callable[[str,int, float], None]):
        self.listeners.append(callback)

    def add_tick_signal_listener(self, callback: Callable[[datetime, int, float], None]):
        self.tick_signal_listeners.append(callback)

    def add_tick_sma_listener(self, callback: Callable[[datetime, float], None]):
        self.tick_sma_listeners.append(callback)

    def add_tick_sma2_listener(self, callback: Callable[[datetime, float], None]):
        self.tick_sma2_listeners.append(callback)

    def on_signal(self, signal: int, price: float):
        for listener in self.listeners:
            try:
                listener(self.name,signal, price)
            except Exception as e:
                logging.error(f"{self.name} on_signal listener raised an exception: %s", e)

    def on_tick_signal(self, timestamp: datetime, signal: int, price: float):
        def run():
            for listener in self.tick_signal_listeners:
                try:
                    listener(timestamp, signal, price)
                except Exception as e:
                    logging.error(self.name + " on_tick_signal Listener raised an exception: %s", e)

        self.executor.submit(run)

    def on_sma_signal(self, timestamp: datetime, sma: float):
        logging.info(
            "%s sma %s",
            timestamp, sma
        )

        def run():
            for listener in self.tick_sma_listeners:
                try:
                    listener(timestamp, sma)
                except Exception as e:
                    logging.error(self.name + " on_sma_signal Listener raised an exception: %s", e)

        self.executor.submit(run)

    def on_sma2_signal(self, timestamp: datetime, sma2: float):
        logging.info(
            "%s sma2 %s",
            timestamp, sma2
        )

        def run():

            for listener in self.tick_sma2_listeners:
                try:
                    listener(timestamp, sma2)
                except Exception as e:
                    logging.error(self.name + " on_sma2_signal Listener raised an exception: %s", e)

        self.executor.submit(run)

    def on_candle_created(self, candle: MidPriceCandle):
        logging.info("SMACrossoverInflectionStrategy on_candle_created %s", candle)
        self.update(candle.start_time, candle.close)

    def update(self, timestamp: datetime, price: float):
        self.prices.append(price)

        if len(self.prices) < self.long_window + 1:
            return None

        short_sma = np.mean(list(self.prices)[-self.short_window:])
        long_sma = np.mean(list(self.prices)[-self.long_window:])

        if short_sma is not None:
            self.on_sma_signal(timestamp, float(short_sma))
        if long_sma is not None:
            self.on_sma2_signal(timestamp, float(long_sma))

        self.short_smas.append(short_sma)
        self.long_smas.append(long_sma)

        if len(self.long_smas) >= 2:
            diff = self.long_smas[-1] - self.long_smas[-2]
            self.long_diffs.append(diff)

        if len(self.long_diffs) < self.smoothing_window + 1:
            return None

        smoothed_diff = np.mean(list(self.long_diffs)[-self.smoothing_window:])
        # self.on_signal(0, price)

        if self.last_smoothed_diff is not None:
            inflection_up = self.last_smoothed_diff < 0 and smoothed_diff > 0
            inflection_down = self.last_smoothed_diff > 0 and smoothed_diff < 0

            if inflection_up:
                signal = 1
                self.on_signal(1, price)
                self.on_tick_signal(timestamp, signal, price)
                logging.info("On Inflection Up Signal")

            elif inflection_down:
                signal = -1
                self.on_signal(-1, price)
                self.on_tick_signal(timestamp, signal, price)
                logging.info("On Inflection Down Signal")

        self.last_smoothed_diff = smoothed_diff
        return None