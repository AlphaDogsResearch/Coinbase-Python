import string

from core.portfolio_manager import PortfolioManager
from core.order import Order

class BasicPortfolioManager(PortfolioManager):
    def __init__(self, capital_fraction=0.1):
        self.capital_fraction = capital_fraction
        self.unplaced_orders = {}

    def evaluate_signals(self, symbol: string, signals: float, aum: float) -> dict:
        orders = {}
        allocation = aum * self.capital_fraction
        if signals > 0:
            orders[symbol] = Order(
                symbol=symbol,
                quantity= allocation / 1000,  # dummy quantity logic
                order_type="market",
                side = "buy"
            )
        elif signals < 0:
            orders[symbol] = Order(
                symbol=symbol,
                quantity= -allocation / 1000,  # dummy quantity logic
                order_type="market",
                side = "sell"
            )
        self.unplaced_orders[symbol] = orders[symbol]
        return orders

    def rollback_unplaced_orders(self):
        self.unplaced_orders.clear()
