from core.order_manager import OrderManager

class SimpleOrderManager(OrderManager):
    def __init__(self):
        self.queue = {}

    def queue_orders(self, orders: dict):
        self.queue.update(orders)

    def cancel_order(self, asset: str):
        if asset in self.queue:
            del self.queue[asset]

    def get_queued_orders(self) -> dict:
        return self.queue
