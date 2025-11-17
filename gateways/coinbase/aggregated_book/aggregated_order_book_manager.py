import datetime
from typing import Optional

from common.interface_book import PriceLevel, OrderBook
from gateways.coinbase.aggregated_book.aggregated_order_book import AggregatedOrderBook


class AggregatedOrderBookManager:
    def __init__(self):
        self.books = {}

    def _now(self):
        return datetime.now(datetime.timezone.utc)

    def get_order_book(self, symbol: Optional[str] = None, book_level=3) -> Optional["OrderBook"]:
        """Return a snapshot OrderBook for a given symbol, or None if not found."""
        symbol = symbol or (next(iter(self.books)) if self.books else None)
        if not symbol or symbol not in self.books:
            return None

        book = self.books[symbol]
        bids = [PriceLevel(price=p, size=s) for (p, s, _, _) in book.get_bids()[:book_level]]
        asks = [PriceLevel(price=p, size=s) for (p, s, _, _) in book.get_asks()[:book_level]]

        # Determine the latest received_time among all levels
        all_times = [r for _, _, r, _ in (book.get_bids() + book.get_asks())]
        last_update = max(all_times) if all_times else self._now()

        return OrderBook(
            timestamp=last_update, # use gateway time instead of exchange time
            contract_name=symbol,
            bids=bids,
            asks=asks
        )

    def get_book(self, instrument: str) -> "AggregatedOrderBook":
        if instrument not in self.books:
            self.books[instrument] = AggregatedOrderBook()
        return self.books[instrument]

    def add_bid(self, instrument, price, size, event_time=None):
        self.get_book(instrument).add_bid(price, size, event_time)

    def add_ask(self, instrument, price, size, event_time=None):
        self.get_book(instrument).add_ask(price, size, event_time)

    def update_bid(self, instrument, price, size, event_time=None):
        self.get_book(instrument).update_bid(price, size, event_time)

    def update_ask(self, instrument, price, size, event_time=None):
        self.get_book(instrument).update_ask(price, size, event_time)

    def remove_bid(self, instrument, price, size=None, event_time=None):
        self.get_book(instrument).remove_bid(price, size, event_time)

    def remove_ask(self, instrument, price, size=None, event_time=None):
        self.get_book(instrument).remove_ask(price, size, event_time)

    def best_bid(self, instrument):
        return self.get_book(instrument).best_bid()

    def best_ask(self, instrument):
        return self.get_book(instrument).best_ask()

    def __str__(self):
        out = []
        for inst, book in self.books.items():
            out.append(f"--- {inst} ---\n{book}")
        return "\n".join(out)
