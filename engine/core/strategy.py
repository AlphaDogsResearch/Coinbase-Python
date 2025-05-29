from typing import Callable


class Strategy:
    def __init__(self):
        self.signal = 0  # -1 = sell, 0 = hold, 1 = buy
        self.name = ""

    def update(self, price: float):
        raise NotImplementedError("Must implement update() in subclass")

    def add_listener(self, callback: Callable[[int], None]):
        raise NotImplementedError("Must implement update() in subclass")

    def on_signal(self,signal :int):
        raise NotImplementedError("Must implement update() in subclass")
