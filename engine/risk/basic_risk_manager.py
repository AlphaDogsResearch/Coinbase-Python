from core.risk_manager import RiskManager
from core.order import Order

class BasicRiskManager(RiskManager):
    def __init__(self, max_order_value=5000):
        self.max_order_value = max_order_value

    def validate_order(self, order: Order, aum: float) -> bool:
        estimated_value = order.quantity * 1000  # assume fixed price for logic
        return estimated_value <= self.max_order_value
