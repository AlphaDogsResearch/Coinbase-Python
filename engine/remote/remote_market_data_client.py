import logging
from typing import Callable, List

from common.interface_book import OrderBook
from common.subscription.messaging.dealer import Dealer
from common.subscription.single_pair_connection.json_message import JsonMessenger
from common.subscription.single_pair_connection.single_pair import PairConnection


class RemoteMarketDataClient:
    def __init__(self):
        self.port = 8080
        self.name = "Remote Market Data Connection"
        self.listeners: List[Callable[[OrderBook], None]] = []  # list of callbacks

        self.remote_market_data_server = PairConnection(self.port, False, self.name)
        self.remote_market_data_server.start_receiving(self.on_event)

    def add_listener(self, callback: Callable[[OrderBook], None]):
        """Register a callback to receive OrderBook updates"""
        self.listeners.append(callback)

    def on_event(self, book: OrderBook):
        for listener in self.listeners:
            try:
                listener(book)
            except Exception as e:
                logging.warning(self.name+" Listener raised an exception: %s", e)
