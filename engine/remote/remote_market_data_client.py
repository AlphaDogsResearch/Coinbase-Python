import datetime
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Dict, Type, Set

from common.interface_book import OrderBook, PriceLevel
from common.interface_reference_point import MarkPrice
from common.interface_req_res import HistoricalCandleResponse, HistoricalCandleRequest
from common.processor.sequential_queue_processor import SelfMonitoringQueueProcessor
from common.seriallization import Serializable
from common.subscription.messaging.dealer import DealerClient
from common.subscription.messaging.gateway_server_handler import EventHandlerImpl
from common.time_utils import convert_epoch_time_to_datetime_millis
from engine.market_data.candle import MidPriceCandle, HistoricalMidPriceCandle
from engine.market_data.market_data_client import MarketDataClient
from common.config_symbols import TRADING_SYMBOLS

class RemoteMarketDataClient(MarketDataClient):
    def __init__(self,port:int,name:str):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.port = port
        self.name = name
        self.logger.info(f"[{name}] connecting to port {port}")
        self.order_book_listeners: Dict[str, Set[Callable[[OrderBook], None]]] = {}  # list of callbacks
        self.mark_price_listener: List[Callable[[MarkPrice], None]] = []
        self.historical_price_listener : List[Callable[[HistoricalCandleResponse,], None]] = []

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
            max_queue_size=128
        )

        # Register event handlers
        self.market_data_queue_processor.register_handler(OrderBook, self._handle_order_book)
        self.mark_price_queue_processor.register_handler(MarkPrice, self._handle_mark_price)

        self.mark_price_executor = ThreadPoolExecutor(max_workers=1)
        self.tick_executor = ThreadPoolExecutor(max_workers=1)
        self.market_data_executor = ThreadPoolExecutor(max_workers=1)

        # Start the processor
        self.market_data_queue_processor.start()
        self.mark_price_queue_processor.start()


        # self.remote_market_data_server = PairConnection(self.port, False, self.name)
        # self.remote_market_data_server.start_receiving(self.on_event)

        self.remote_market_data_client = DealerClient(self.name, "localhost", self.port)

        MESSAGE_TYPES: tuple[Type[Serializable], ...] = (
            OrderBook,
            MarkPrice,
            PriceLevel,
            HistoricalCandleResponse,
            HistoricalMidPriceCandle
        )

        business_message_handler = EventHandlerImpl(self.name,self.on_event, *MESSAGE_TYPES)
        # Register handlers
        self.remote_market_data_client.register_handler(b"*", business_message_handler)  # wildcard for all other messages
        self.remote_market_data_client.register_on_connected(self.update_remote_connection_status)

        self.is_remote_connected = False

    def update_remote_connection_status(self,is_connected: bool):
        self.is_remote_connected = is_connected
        self.logger.info(f"Remote Market Client Connection Status {self.is_remote_connected}")

    def start(self):
        self.logger.info("Starting Remote Market Client.....")
        # init request
        self.init_request()

    def send_request(self):
        if not self.is_remote_connected:
            self.logger.info("Remote Market Client Connection Not Connected Yet...")

    def init_request(self):
        while not self.is_remote_connected:
            self.logger.info("Remote Market Client Connection Not Connected Yet...")
            self.logger.info("Waiting For 5 seconds for Remote Market Client...")
            time.sleep(5)

    def add_order_book_listener(self,symbol:str, callback: Callable[[OrderBook], None]):
        """Register a callback to receive OrderBook updates"""
        if symbol not in self.order_book_listeners:
            self.order_book_listeners[symbol] = set()
        self.order_book_listeners[symbol].add(callback)

    def add_tick_price(self, callback: Callable[[datetime.datetime,float], None]):
        """Register a callback to receive OrderBook updates"""
        self.tick_price_listener.append(callback)


    def add_mark_price_listener(self, callback: Callable[[MarkPrice], None]):
        """Register a callback to receive MarkPrice updates"""
        self.mark_price_listener.append(callback)

    def add_historical_price_listener(self, callback: Callable[[HistoricalCandleResponse], None]):
        """Register a callback to receive MarkPrice updates"""
        self.historical_price_listener.append(callback)

    def notify_order_book_listeners(self, order_book: OrderBook):
        symbol = order_book.contract_name
        for listener in self.order_book_listeners.get(symbol, []):
            try:
                listener(order_book)
            except Exception as e:
                self.logger.error(
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
                self.logger.error(
                    self.name + "[Market Data] Listener raised an exception: %s", e
                )

    def update_mark_price(self, mark_price: MarkPrice):
        for listener in self.mark_price_listener:
            try:
                listener(mark_price)
            except Exception as e:
                self.logger.error(
                    self.name + "[Mark Price] Listener raised an exception: %s", e
                )
    def request_for_historical_candle(self,symbol:str, interval_unit:str="1h", interval:int=10):
        self.remote_market_data_client.send(HistoricalCandleRequest(symbol, interval, interval_unit))

    def _handle_order_book(self, order_book: OrderBook):
        """Handle OrderBook events sequentially"""
        self.market_data_executor.submit(self.notify_order_book_listeners,order_book)
        self.tick_executor.submit(self.notify_tick_listeners,order_book)

    def _handle_mark_price(self, mark_price: MarkPrice):
        """Handle MarkPrice events sequentially"""
        self.mark_price_executor.submit(self.update_mark_price,mark_price)

    # dont block the thread
    def on_event(self, ident:str, obj: object):
        self.logger.debug(f"Received {obj}")
        if isinstance(obj, OrderBook):
            self.market_data_queue_processor.submit(obj)
        elif isinstance(obj, MarkPrice):
            self.mark_price_queue_processor.submit(obj)
        elif isinstance(obj, HistoricalCandleResponse):
            self.received_historical_candle_response(obj)

    def received_historical_candle_response(self, historical_candle_response: HistoricalCandleResponse):
        self.logger.info("Received Historical Candle Response %s" % historical_candle_response)
        for listener in self.historical_price_listener:
            try:
                listener(historical_candle_response)
            except Exception as e:
                self.logger.error(
                    self.name + "[Historical Candle Price] Listener raised an exception: %s", e
                )
