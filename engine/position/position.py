import logging


class Position:
    def __init__(self, symbol: str, position_amount: float, entry_price: float, unrealised_pnl: float,
                 maint_margin: float):
        self.symbol = symbol
        self.position_amount = position_amount
        self.entry_price = entry_price
        self.unrealised_pnl = unrealised_pnl
        self.maint_margin = maint_margin
        self.unrealised_pnl_decimal_place = 4
        self.maint_margin_decimal_place = 4

    def get_notional_amount(self,mark_price:float):
        return abs(self.position_amount) * mark_price

    def update_unrealised_pnl(self, mark_price:float):
        #long
        if self.position_amount > 0:
            self.unrealised_pnl = (mark_price - self.entry_price) * abs(self.position_amount)
        #short
        elif self.position_amount < 0:
            self.unrealised_pnl = (self.entry_price -mark_price) * abs(self.position_amount)
        else:
            self.unrealised_pnl = 0
        self.unrealised_pnl = round(self.unrealised_pnl, self.unrealised_pnl_decimal_place)
        logging.debug("Updated Unrealized Pnl for %s: %s", self.symbol, self)
        return self.unrealised_pnl

    def update_maintenance_margin(self, mark_price: float, maint_margin_rate: float, maint_amount: float):
        notional_value = abs(self.position_amount) * mark_price
        self.maint_margin = (notional_value * maint_margin_rate) + maint_amount
        self.maint_margin = round(self.maint_margin,self.maint_margin_decimal_place)
        logging.debug("Updated Maint Margin for %s: %s", self.symbol, self)
        return self.maint_margin

    def add_trade(self, trade_qty: float, trade_price: float):
        """
        Updates the position amount and entry price based on a new trade.

        :param trade_qty: Quantity of the trade (positive for buy, negative for sell)
        :param trade_price: Executed trade price
        """
        old_qty = self.position_amount
        new_qty = round(old_qty + trade_qty, 7)

        # Check if trade is increasing or reducing the position
        if old_qty == 0 or (old_qty * trade_qty > 0):
            # Increasing position in the same direction or opening a new one
            total_cost = self.entry_price * abs(old_qty) + trade_price * abs(trade_qty)
            self.entry_price = total_cost / abs(new_qty)
        elif old_qty * trade_qty < 0:
            # Reducing the position, entry price remains the same
            if abs(trade_qty) > abs(old_qty):
                # If trade flips the position direction
                remaining_qty = trade_qty + old_qty  # carryover to new side
                self.entry_price = trade_price  # new side's entry price
                new_qty = remaining_qty

        self.position_amount = round(new_qty, 7)
        logging.info("Updated Position Amount: %s",self)

    def recycle(self):
        self.symbol = ""
        self.position_amount = 0
        self.entry_price = 0
        self.unrealised_pnl = 0
        self.maint_margin = 0

    def __str__(self):
        return ", Symbol=" + self.symbol + \
                ", Position Amount=" + str(self.position_amount) + \
                ", Entry Price=" + str(self.entry_price) + \
                ", Unrealized PNL=" + str(self.unrealised_pnl) + \
                ", Maint Margin=" + str(self.maint_margin)

