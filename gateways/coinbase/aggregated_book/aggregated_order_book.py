from datetime import timezone, datetime


class AggregatedOrderBook:
    def __init__(self):
        # Store {price: (size, received_time, updated_time)}
        self.bids = {}
        self.asks = {}

    def _now(self):
        # Returns timezone-aware UTC datetime
        return datetime.now(timezone.utc)

    def _parse_event_time(self, event_time):
        """Parse event_time (ISO8601 with Z). If None/invalid, return current UTC."""
        if not event_time:
            return self._now()
        try:
            return datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except Exception:
            return self._now()

    def add_bid(self, price, size, event_time=None):
        price, size = float(price), float(size)
        received = self._now()
        exchange_update_time = self._parse_event_time(event_time)
        existing = self.bids.get(price, (0, received, exchange_update_time))[0]
        self.bids[price] = (existing + size, received, exchange_update_time)

    def add_ask(self, price, size, event_time=None):
        price, size = float(price), float(size)
        received = self._now()
        exchange_update_time = self._parse_event_time(event_time)
        existing = self.asks.get(price, (0, received, exchange_update_time))[0]
        self.asks[price] = (existing + size, received, exchange_update_time)

    def remove_bid(self, price, size=None, event_time=None):
        price = float(price)
        if price in self.bids:
            current_size, received, _ = self.bids[price]
            exchange_update_time = self._parse_event_time(event_time)
            if size is None or current_size <= float(size):
                del self.bids[price]
            else:
                self.bids[price] = (current_size - float(size), received, exchange_update_time)

    def remove_ask(self, price, size=None, event_time=None):
        price = float(price)
        if price in self.asks:
            current_size, received, _ = self.asks[price]
            exchange_update_time = self._parse_event_time(event_time)
            if size is None or current_size <= float(size):
                del self.asks[price]
            else:
                self.asks[price] = (current_size - float(size), received, exchange_update_time)

    def update_bid(self, price, size, event_time=None):
        price, size = float(price), float(size)
        received = self._now()
        exchange_update_time = self._parse_event_time(event_time)
        if size <= 0:
            self.bids.pop(price, None)
        else:
            old_received = self.bids.get(price, (0, received, exchange_update_time))[1]
            self.bids[price] = (size, old_received, exchange_update_time)

    def update_ask(self, price, size, event_time=None):
        price, size = float(price), float(size)
        received = self._now()
        exchange_update_time = self._parse_event_time(event_time)
        if size <= 0:
            self.asks.pop(price, None)
        else:
            old_received = self.asks.get(price, (0, received, exchange_update_time))[1]
            self.asks[price] = (size, old_received, exchange_update_time)

    def best_bid(self):
        return max(self.bids.items(), key=lambda x: x[0], default=None)

    def best_ask(self):
        return min(self.asks.items(), key=lambda x: x[0], default=None)

    def get_bids(self):
        return sorted([(p, s, r, u) for p, (s, r, u) in self.bids.items()],
                      key=lambda x: -x[0])

    def get_asks(self):
        return sorted([(p, s, r, u) for p, (s, r, u) in self.asks.items()],
                      key=lambda x: x[0])

    def __str__(self):
        book = "Bids:\n"
        for p, s, r, u in self.get_bids():
            book += f"  {p:.2f} x {s} (received {r}, exchange_update_time {u})\n"
        book += "Asks:\n"
        for p, s, r, u in self.get_asks():
            book += f"  {p:.2f} x {s} (received {r}, exchange_update_time {u})\n"
        return book