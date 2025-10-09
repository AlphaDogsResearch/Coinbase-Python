import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Dict

from common.interface_book import OrderBook
from common.interface_reference_point import MarkPrice
from common.subscription.single_pair_connection.single_pair import PairConnection
from common.time_utils import convert_epoch_time_to_datetime_millis
from engine.market_data.market_data_client import MarketDataClient


class RemoteMarketDataClient(MarketDataClient):
    def __init__(self):
        self.port = 8080
        self.name = "Remote Market Data Connection"
        self.order_book_listeners: Dict[str, List[Callable[[OrderBook], None]]] = {}  # list of callbacks
        self.mark_price_listener: List[Callable[[MarkPrice], None]] = []

        self.tick_price_listener: List[Callable[[datetime.datetime,float], None]] = (
            []
        )  # list of callbacks

        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="MD")
        self.tick_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TICK")

        self.remote_market_data_server = PairConnection(self.port, False, self.name)
        self.remote_market_data_server.start_receiving(self.on_event)

    def add_order_book_listener(self,symbol:str, callback: Callable[[OrderBook], None]):
        """Register a callback to receive OrderBook updates"""
        if symbol not in self.order_book_listeners:
            self.order_book_listeners[symbol] = []
        self.order_book_listeners[symbol].append(callback)

    def add_tick_price(self, callback: Callable[[datetime.datetime,float], None]):
        """Register a callback to receive OrderBook updates"""
        self.tick_price_listener.append(callback)


    def add_mark_price_listener(self, callback: Callable[[MarkPrice], None]):
        """Register a callback to receive MarkPrice updates"""
        self.mark_price_listener.append(callback)

    def notify_order_book_listeners(self, order_book: OrderBook):
        symbol = order_book.contract_name
        for listener in self.order_book_listeners.get(symbol, []):
            try:
                listener(order_book)
            except Exception as e:
                logging.error(
                    self.name + "[Market Data] Listener raised an exception: %s", e
                )
    def notify_tick_listeners(self, order_book: OrderBook):
        timestamp = order_book.timestamp
        dt = convert_epoch_time_to_datetime_millis(timestamp)
        mid_price = order_book.get_best_mid()
        for listener in self.tick_price_listener:
            try:
                listener(dt,mid_price)
            except Exception as e:
                logging.error(
                    self.name + "[Market Data] Listener raised an exception: %s", e
                )

    def update_mark_price(self, mark_price: MarkPrice):
        for listener in self.mark_price_listener:
            try:
                listener(mark_price)
            except Exception as e:
                logging.error(
                    self.name + "[Mark Price] Listener raised an exception: %s", e
                )

    # dont block the thread
    def on_event(self, obj: object):
        if isinstance(obj, OrderBook):
            self.executor.submit(self.notify_order_book_listeners, obj)
            self.tick_executor.submit(self.notify_tick_listeners, obj)
        elif isinstance(obj, MarkPrice):
            self.executor.submit(self.update_mark_price, obj)
