import logging
from typing import Callable, List
import threading
import queue
import time

from common.interface_book import OrderBook
from common.interface_order import Order
from common.subscription.single_pair_connection.single_pair import PairConnection


class RemoteOrderClient:
    def __init__(self):
        # make port configurable
        self.port = 8081
        self.name = "Remote Order Order Connection"
        self.listeners: List[Callable[[str], None]] = []  # list of callbacks

        self.remote_order_server = PairConnection(self.port, False, self.name)
        self.remote_order_server.start_receiving(self.on_event)

        # Queue to hold orders to send
        self._order_queue = queue.Queue()
        self._running = True
        self._sender_thread = threading.Thread(target=self._send_orders_loop, daemon=True)
        self._sender_thread.start()

    def submit_order(self, order: Order):
        """Add an order to the sending queue."""
        self._order_queue.put(order)

    def _send_orders_loop(self):
        """Background thread to send orders from the queue."""
        while self._running:
            try:
                order = self._order_queue.get(timeout=0.1)  # wait for an order or timeout
                self.remote_order_server.send_order(order)
                self._order_queue.task_done()
            except queue.Empty:
                continue  # no orders, loop again

    def add_listener(self, callback: Callable[[str], None]):
        """Register a callback to receive OrderBook updates"""
        self.listeners.append(callback)

    def on_event(self, order_id: str):
        logging.info("[%s] Received Order ID: %s", self.name, order_id)

        for listener in self.listeners:
            try:
                listener(order_id)
            except Exception as e:
                logging.warning(self.name+" Listener raised an exception: %s", e)

    def stop(self):
        """Stop the sender thread cleanly."""
        self._running = False
        self._sender_thread.join(timeout=1)
