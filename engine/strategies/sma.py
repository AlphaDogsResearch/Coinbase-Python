import logging
from concurrent.futures import ThreadPoolExecutor
import datetime
from typing import Callable, List

from common.interface_book import OrderBook
from common.time_utils import convert_epoch_time_to_datetime_millis
from engine.core.strategy import Strategy
from engine.market_data.candle import MidPriceCandle


class SMAStrategy(Strategy):
    def __init__(self,symbol:str,trade_unit:float, short_window: int, long_window: int):
        super().__init__(symbol,trade_unit)
        self.short_window = short_window
        self.long_window = long_window
        self.name = "SMA-" +str(symbol) +"-" + str(self.short_window) + "-" + str(self.long_window)
        self.prices = []
        self.listeners: List[Callable[[str,int,float,str,float], None]] = []  # list of callbacks
        self.plot_signal_listeners: List[Callable[[datetime.datetime, int, float], None]] = []  # list of callbacks
        self.plot_sma_listeners: List[Callable[[datetime.datetime, float], None]] = []  # list of callbacks
        self.plot_sma2_listeners: List[Callable[[datetime.datetime, float], None]] = []  # list of callbacks
        self.signal = 0
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="SMA")

    def moving_average(self, window: int):
        if len(self.prices) < window:
            return None
        return sum(self.prices[-window:]) / window

    def on_candle_created(self, candle: MidPriceCandle):
        pass

    def add_signal_listener(self, callback: Callable[[str,int, float,str,float], None]):
        self.listeners.append(callback)

    def add_plot_signal_listener(self, callback: Callable[[datetime, int, float], None]):
        self.plot_signal_listeners.append(callback)

    def add_plot_sma_listener(self, callback: Callable[[datetime.datetime, float], None]):
        self.plot_sma_listeners.append(callback)

    def add_plot_sma2_listener(self, callback: Callable[[datetime.datetime, float], None]):
        self.plot_sma2_listeners.append(callback)

    def on_signal(self, signal: int,price:float):
        for listener in self.listeners:
            try:
                listener(self.name,signal,price,self.symbol,self.trade_unit)
            except Exception as e:
                logging.error(self.name + " on_signal Listener raised an exception: %s", e)

    def on_tick_signal(self,timestamp:float, signal: int, price: float):
        def run():
            dt = convert_epoch_time_to_datetime_millis(timestamp)
            for listener in self.plot_signal_listeners:
                try:
                    listener(dt,signal, price)
                except Exception as e:
                    logging.error(self.name + " Listener raised an exception: %s", e)
        self.executor.submit(run)

    def on_sma_signal(self,timestamp:float, sma: float):
        def run():
            dt = convert_epoch_time_to_datetime_millis(timestamp)
            for listener in self.plot_sma_listeners:
                try:
                    listener(dt, sma)
                except Exception as e:
                    logging.error(self.name + " Listener raised an exception: %s", e)
        self.executor.submit(run)

    def on_sma2_signal(self,timestamp:float, sma2: float):
        def run():
            dt = convert_epoch_time_to_datetime_millis(timestamp)
            for listener in self.plot_sma2_listeners:
                try:
                    listener(dt, sma2)
                except Exception as e:
                    logging.error(self.name + " Listener raised an exception: %s", e)
        self.executor.submit(run)

    def on_update(self, order_book: OrderBook):
        price = order_book.get_best_mid()
        self.prices.append(price)

        short_sma = self.moving_average(self.short_window)
        long_sma = self.moving_average(self.long_window)

        if short_sma is not None:
            self.on_sma_signal(order_book.timestamp,short_sma)
        if long_sma is not None:
            self.on_sma2_signal(order_book.timestamp,long_sma)

        if short_sma is None or long_sma is None:
            self.signal = 0
        elif short_sma > long_sma:
            if self.signal == 1:
                return
            self.signal = 1
            logging.info(
                "%s changed signal to %d, current short %f current long %f",
                self.name,
                self.signal,
                short_sma,
                long_sma,
            )
            self.on_signal(self.signal,price)
            self.on_tick_signal(order_book.timestamp, self.signal, price)
        elif short_sma < long_sma:
            if self.signal == -1:
                return
            self.signal = -1
            logging.info(
                "%s changed signal to %d, current short %f current long %f",
                self.name,
                self.signal,
                short_sma,
                long_sma,
            )
            self.on_signal(self.signal,price)
            self.on_tick_signal(order_book.timestamp,self.signal,price)
        else:
            self.signal = 0
