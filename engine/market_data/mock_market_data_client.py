from engine.market_data.market_data_client import MarketDataClient
from typing import Callable, List
from common.interface_book import OrderBook, PriceLevel

import time
import random


class MockMarketDataClient(MarketDataClient):
    def __init__(self):
        self.listeners: List[Callable[[OrderBook], None]] = []

    def add_order_book_listener(self, callback: Callable[[OrderBook], None]):
        self.listeners.append(callback)

    def notify_order_book_listeners(self, book: OrderBook):
        for listener in self.listeners:
            listener(book)

    def start_publishing_mock_orderbook_events(
        self, count: int, frequency_seconds: float
    ):
        # Publish 1 event per second for 1 minute
        for _ in range(count):
            timestamp = time.time()
            book = MockOrderBook(timestamp)
            self.notify_order_book_listeners(book)
            time.sleep(frequency_seconds)


class MockOrderBook(OrderBook):
    def __init__(self, timestamp: float):
        contract = "BTCUSD"
        bids = [PriceLevel(100 - i * 0.5, random.uniform(-1.5, 1.5)) for i in range(5)]
        asks = [PriceLevel(100 + i * 0.5, random.uniform(-1.5, 1.5)) for i in range(5)]
        super().__init__(timestamp, contract, bids, asks)
