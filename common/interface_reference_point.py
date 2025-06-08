# mark price of symbol
class MarkPrice:
    def __init__(self, symbol: str, price: float):
        self.symbol = symbol
        self.price = float(price)

    def __str__(self):
        return '[' + str(self.symbol) + " @ " + str(self.price) + ']'