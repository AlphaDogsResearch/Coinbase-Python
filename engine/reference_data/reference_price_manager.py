from typing import Callable, List

from common.interface_reference_point import MarkPrice


class ReferencePriceManager:
    def __init__(self):
        self.mark_price_dict = {}
        self.mark_price_listener: List[Callable[[MarkPrice], None]] = []

    def on_reference_data_event(self, mark_price: MarkPrice):
        symbol = mark_price.symbol
        price = float(mark_price.price)
        self.mark_price_dict[symbol] = price

        for listener in self.mark_price_listener:
            listener(mark_price)

    def get_mark_price(self, symbol: str) -> float | None:
        return self.mark_price_dict[symbol]

    def attach_mark_price_listener(self, callback: Callable[[MarkPrice], None]):
        self.mark_price_listener.append(callback)
