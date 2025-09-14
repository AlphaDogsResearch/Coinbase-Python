from common.config_symbols import TRADING_SYMBOLS
import pandas as pd
import time
from typing import Callable, List
from engine.market_data.market_data_client import MarketDataClient, OrderBook
from common.interface_book import PriceLevel
import logging


class CSVBacktestOrderBook(OrderBook):
    def __init__(self, timestamp: float, price: float):
        contract = TRADING_SYMBOLS[0]
        bids = [PriceLevel(price - 0.5, 1.0)]  # mock one level bid/ask depth
        asks = [PriceLevel(price + 0.5, 1.0)]
        super().__init__(timestamp, contract, bids, asks)


class CSVBacktestMarketDataClient(MarketDataClient):
    def __init__(self, csv_path: str):
        self.listeners: List[Callable[[OrderBook], None]] = []
        self.df = pd.read_csv(csv_path)
        self.df["timestamp"] = (
            pd.to_datetime(self.df["timestamp"]).astype(int) / 1e9
        )  # convert to epoch seconds

    def add_order_book_listener(self, callback: Callable[[OrderBook], None]):
        logging.info("add_order_book_listener added")
        self.listeners.append(callback)

    def notify_order_book_listeners(self, book: OrderBook):
        logging.info(book)
        for listener in self.listeners:
            logging.info("publishing")
            listener(book)

    def start_publishing(self, frequency_milliseconds: int = 10):
        """
        Simulates publishing order book updates from CSV at the given frequency.
        :param frequency_milliseconds: Time between updates in milliseconds.
        """
        delay = frequency_milliseconds / 1000.0
        for _, row in self.df.iterrows():
            book = CSVBacktestOrderBook(timestamp=row["timestamp"], price=row["price"])
            self.notify_order_book_listeners(book)
            time.sleep(delay)
