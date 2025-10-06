from engine.core.position_tracker import PositionTracker
from engine.core.order import Order
from engine.tracking.telegram_alert import telegramAlert

class InMemoryTracker(PositionTracker):
    def __init__(self, alert: telegramAlert):
        self.positions = {}
        self.pnl = {}
        self.alert = alert

    def update_position(self, order: Order, fill_price: float):
        symbol = order.symbol
        qty = order.leaves_quantity
        self.positions[symbol] = self.positions.get(symbol, 0) + qty
        self.pnl[symbol] = self.pnl.get(symbol, 0.0) + qty * fill_price
        self.alert.sendAlert(f"Position updated: {symbol} | Qty: {qty} | Fill Price: {fill_price}")

    def get_positions(self) -> dict:
        return self.positions

    def get_pnl(self) -> dict:
        return self.pnl
