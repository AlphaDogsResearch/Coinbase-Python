import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Type

from common.interface_book import VenueOrderBook, OrderBook
from common.interface_reference_point import MarkPrice
from common.processor.sequential_queue_processor import SelfMonitoringQueueProcessor
from common.seriallization import Serializable
from common.subscription.messaging.gateway_server_handler import EventHandlerImpl
from common.subscription.messaging.router import RouterServer

from gateways.gateway_interface import GatewayInterface


class MarketDataConnection:
    def __init__(self,name:str, port: int, gateway: GatewayInterface):
        self.name = name + " Market Data Connection"
        # self.market_data_server = PairConnection(port, True, self.name)
        # self.market_data_server.start_receiving(self.on_event)
        MESSAGE_TYPES: tuple[Type[Serializable], ...] = (

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

        self.gateway = gateway
        self.gateway.register_depth_callback(self.publish_order_book)
        self.gateway.register_mark_price_callback(self.publish_mark_price)

    def on_event(self,ident:str,obj:object):
        logging.info(f"Received event: {ident} {type(obj)}")


    def publish_order_book(self, exchange: str, venue_order_book: VenueOrderBook):
        # logging.info("Exchange %s " % exchange)
        order_book = venue_order_book.get_book()
        self.tick_queue_processor.submit(order_book)


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
