from common.interface_book import OrderBook
from common.subscription.single_pair_connection.single_pair import PairConnection

from gateways.binance.binance_gateway import BinanceGateway


class MarketDataConnection:
    def __init__(self, port: int, gateway: BinanceGateway):
        self.name = "Binance Market Data Connection"
        self.market_data_server = PairConnection(port, True, self.name)
        self.gateway = gateway
        self.gateway.register_depth_callback(self.publish_order_book)

    def publish_order_book(self, exchange, book: OrderBook):
        # logging.info("Exchange %s " % exchange)
        self.market_data_server.send_market_data(book)
