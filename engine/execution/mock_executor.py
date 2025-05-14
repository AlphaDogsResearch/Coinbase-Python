from core.trade_execution import TradeExecution

class MockExecutor(TradeExecution):
    def place_orders(self, orders: dict):
        for symbol, order in orders.items():
            print(f"Mock placing order: {order}")
