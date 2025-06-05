import logging


class Position:
    def __init__(self, symbol: str, position_amount: float, entry_price: float, unrealised_pnl: float,
                 maint_margin: float):
        self.symbol = symbol
        self.position_amount = position_amount
        self.entry_price = entry_price
        self.unrealised_pnl = unrealised_pnl
        self.maint_margin = maint_margin

    def update_unrealised_pnl(self, new_unrealised_pnl):
        self.unrealised_pnl = new_unrealised_pnl

    def add_position_amount(self, new_position_amount):
        self.position_amount += new_position_amount
        logging.info("New Position for %s is %s",self.symbol,self.position_amount)

    def is_position_closed(self) -> bool:
        is_closed = self.position_amount == 0
        if is_closed:
            self.update_unrealised_pnl(0)
        return is_closed

    def __str__(self):
        return ", Symbol=" + self.symbol + \
                ", Position Amount=" + str(self.position_amount) + \
                ", Entry Price=" + str(self.entry_price) + \
                ", Unrealized PNL=" + str(self.unrealised_pnl) + \
                ", Maint Margin=" + str(self.maint_margin)

