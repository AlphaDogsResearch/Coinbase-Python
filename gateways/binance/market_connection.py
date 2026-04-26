import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Type

from common.interface_book import VenueOrderBook, OrderBook
from common.interface_reference_point import MarkPrice
from common.interface_req_res import HistoricalCandleRequest
from common.processor.sequential_queue_processor import SelfMonitoringQueueProcessor
from common.questdb_writer import QuestDbWriter
from common.seriallization import Serializable
from common.subscription.messaging.gateway_server_handler import EventHandlerImpl
from common.subscription.messaging.router import RouterServer

from gateways.gateway_interface import GatewayInterface


class MarketDataConnection:
    def __init__(self,name:str, port: int, gateway: GatewayInterface,is_quest_db_enabled=False):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.name = name + " Market Data Connection"
        MESSAGE_TYPES: tuple[Type[Serializable], ...] = (
            HistoricalCandleRequest,
        )

        server_handler = EventHandlerImpl(self.name,self.on_event, *MESSAGE_TYPES)

        self.market_data_server = RouterServer(self.name,server_handler,"localhost",port)

        '''
        Mark Price and Order Book is being published from the gateway by multiple thread, zmq can only take 1 thread at a time so all goes through the queue
        '''
        self.tick_queue_processor = SelfMonitoringQueueProcessor(
            name="TickSequentialProcessor",
            max_queue_size=256
        )

        # Register event handlers
        self.tick_queue_processor.register_handler(MarkPrice, self._handle_mark_price)
        self.tick_queue_processor.register_handler(OrderBook, self._handle_order_book)
        self.tick_queue_processor.start()

        self.tick_executor = ThreadPoolExecutor(max_workers=1)
        self.quest_db_executor = ThreadPoolExecutor(max_workers=1)

        self.gateway = gateway
        self.gateway.register_depth_callback(self.publish_order_book)
        self.gateway.register_mark_price_callback(self.publish_mark_price)
        self.is_quest_db_enabled = is_quest_db_enabled
        if self.is_quest_db_enabled:
            self.questdb_writer = QuestDbWriter()

    def on_event(self,ident:str,obj:object):
        self.logger.info(f"Received event: {ident} {type(obj)}")
        if isinstance(obj, HistoricalCandleRequest):
            self.get_historical_candle(ident,obj)

    def publish_order_book(self, exchange: str, venue_order_book: VenueOrderBook):
        # logging.info("Exchange %s " % exchange)
        order_book = venue_order_book.get_book()
        self.logger.debug(f"Order Book {order_book}")

        self.tick_queue_processor.submit(order_book)
        if self.is_quest_db_enabled:
            # write to quest db in another thread
            self.quest_db_executor.submit(self.questdb_writer.write_order_book,exchange, order_book.contract_name, order_book.asks, order_book.bids,
                                                 order_book.timestamp)


    def publish_mark_price(self, symbol: str, price: float):
        # logging.info(f"[{symbol}] MarkPrice {price} ")
        mark_price = MarkPrice(symbol, price)
        self.tick_queue_processor.submit(mark_price)

    def _handle_order_book(self, order_book: OrderBook):
        """Handle MarkPrice events sequentially"""
        self.tick_executor.submit(self.market_data_server.send_to_all,order_book)

    def _handle_mark_price(self, mark_price: MarkPrice):
        """Handle MarkPrice events sequentially"""
        self.tick_executor.submit(self.market_data_server.send_to_all,mark_price)


    def get_historical_candle(self, ident:str, historical_candle_request:HistoricalCandleRequest):
        self.logger.info("Received Historical Candle Request %s" % historical_candle_request)
        interval = historical_candle_request.interval
        symbol = historical_candle_request.symbol
        interval_unit = historical_candle_request.interval_unit
        candles = self.gateway.get_klines(symbol=symbol,interval_unit=interval_unit,past_interval=interval)
        historical_candles = historical_candle_request.handle(candles)
        self.market_data_server.send(ident, historical_candles)
