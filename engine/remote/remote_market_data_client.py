import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Dict

from common.interface_book import OrderBook
from common.interface_reference_point import MarkPrice
from common.processor.sequential_queue_processor import SelfMonitoringQueueProcessor
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


        #queue size to adjust accordingly base on instrument
        self.market_data_queue_processor = SelfMonitoringQueueProcessor(
            name="MarketDataProcessor",
            max_queue_size=128
        )


        self.mark_price_queue_processor = SelfMonitoringQueueProcessor(
            name="MarkPriceProcessor",
            max_queue_size=8
        )

        # Register event handlers
        self.market_data_queue_processor.register_handler(OrderBook, self._handle_order_book)
        self.mark_price_queue_processor.register_handler(MarkPrice, self._handle_mark_price)

        # Start the processor
        self.market_data_queue_processor.start()
        self.mark_price_queue_processor.start()

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

    def _handle_order_book(self, order_book: OrderBook):
        """Handle OrderBook events sequentially"""
        self.notify_order_book_listeners(order_book)
        self.notify_tick_listeners(order_book)

    def _handle_mark_price(self, mark_price: MarkPrice):
        """Handle MarkPrice events sequentially"""
        self.update_mark_price(mark_price)

    # dont block the thread
    def on_event(self, obj: object):
        if isinstance(obj, OrderBook):
            self.market_data_queue_processor.submit(obj)
        elif isinstance(obj, MarkPrice):
            self.mark_price_queue_processor.submit(obj)
