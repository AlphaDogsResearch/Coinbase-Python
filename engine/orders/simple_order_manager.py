from typing import Callable, List

from common.interface_order import OrderEvent
from engine.core.order_manager import OrderManager

class SimpleOrderManager(OrderManager):



    def __init__(self):
        self.queue = {}
        self.open_orders = {}
        self.call_back_listeners = List[Callable[[OrderEvent], None]] = []

    def on_order_event(self, order: OrderEvent):
        for call_back in self.call_back_listeners:
            call_back(order)

    def register_order_event_callbacks(self, callback: Callable[[OrderEvent], None]):
        """Register a callback to receive OrderBook updates"""
        self.call_back_listeners.append(callback)
