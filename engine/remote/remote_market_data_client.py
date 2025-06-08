import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

from common.interface_book import OrderBook
from common.interface_reference_point import MarkPrice
from common.subscription.single_pair_connection.single_pair import PairConnection


class RemoteMarketDataClient:
    def __init__(self):
        self.port = 8080
        self.name = "Remote Market Data Connection"
        self.market_data_listener: List[Callable[[OrderBook], None]] = []  # list of callbacks
        self.mark_price_listener: List[Callable[[MarkPrice], None]] = []

        self.executor = ThreadPoolExecutor(max_workers=10)

        self.remote_market_data_server = PairConnection(self.port, False, self.name)
        self.remote_market_data_server.start_receiving(self.on_event)

    def add_market_data_listener(self, callback: Callable[[OrderBook], None]):
        """Register a callback to receive OrderBook updates"""
        self.market_data_listener.append(callback)

    def add_mark_price_listener(self, callback: Callable[[MarkPrice], None]):
        """Register a callback to receive MarkPrice updates"""
        self.mark_price_listener.append(callback)

    def update_market_data(self,order_book:OrderBook):
        for listener in self.market_data_listener:
            try:
                listener(order_book)
            except Exception as e:
                logging.warning(self.name + "[Market Data] Listener raised an exception: %s", e)

    def update_mark_price(self,mark_price:MarkPrice):
        for listener in self.mark_price_listener:
            try:
                listener(mark_price)
            except Exception as e:
                logging.error(self.name + "[Mark Price] Listener raised an exception: %s", e)

    # dont block the thread
    def on_event(self, obj: object):
        if isinstance(obj, OrderBook):
            self.executor.submit(self.update_market_data, obj)
        elif isinstance(obj, MarkPrice):
            self.executor.submit(self.update_mark_price, obj)

