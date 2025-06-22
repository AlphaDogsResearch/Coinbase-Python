class TradingCost:
    def __init__(self, symbol:str, maker_fee:float, taker_fee:float):
        self.symbol = symbol
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee


    def __str__(self):
        return "Symbol=" + self.symbol + \
                ", Maker Fee=" + str(self.maker_fee) + \
                ", Taker Fee=" + str(self.taker_fee)