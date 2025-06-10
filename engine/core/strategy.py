from typing import Callable
from engine.market_data.candle import MidPriceCandle


class Strategy:
    def __init__(self):
        self.signal = 0  # -1 = sell, 0 = hold, 1 = buy
        self.name = ""

    def on_candle_created(self, candle: MidPriceCandle):
        raise NotImplementedError("Must implement on_candle_created() in subclass")

    def add_signal_listener(self, callback: Callable[[int, float], None]):
        raise NotImplementedError("Must implement add_signal_listener() in subclass")

    def _notify_signal_generated(self, signal: int, price: float):
        raise NotImplementedError(
            "Must implement _notify_signal_generated() in subclass"
        )
