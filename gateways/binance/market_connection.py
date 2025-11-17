import logging

from common.interface_book import VenueOrderBook
from common.interface_reference_point import MarkPrice
from common.subscription.single_pair_connection.single_pair import PairConnection

from gateways.gateway_interface import GatewayInterface


class MarketDataConnection:
    def __init__(self,name:str, port: int, gateway: GatewayInterface):
        self.name = name + " Market Data Connection"
        self.market_data_server = PairConnection(port, True, self.name)
        self.market_data_server.start_receiving(self.on_event)
        self.gateway = gateway
        self.gateway.register_depth_callback(self.publish_order_book)
        self.gateway.register_mark_price_callback(self.publish_mark_price)

    def on_event(self, obj: object):
        logging.info("Received event: {}".format(obj))


    def publish_order_book(self, exchange: str, venue_order_book: VenueOrderBook):
        # logging.info("Exchange %s " % exchange)
        order_book = venue_order_book.get_book()
        self.market_data_server.publish_market_data_event(order_book)

    def publish_mark_price(self, symbol: str, price: float):
        self.market_data_server.publish_mark_price(MarkPrice(symbol, price))
