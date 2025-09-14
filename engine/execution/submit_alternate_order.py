import logging
import threading
import time

from common.identifier import OrderIdGenerator
from common.interface_order import Order, Side, OrderType
from engine.remote.remote_order_service_client import RemoteOrderClient


# class SubmitAlternateOrder:
#     def __init__(self, remote_order_client: RemoteOrderClient, interval: float = 1.0):
#         self.port = 8080
#         self.remote_order_client = remote_order_client
#         self.side = Side.SELL
#         self.id_generator = OrderIdGenerator("BTCUSDT")
#         self.interval = interval  # seconds
#         self._running = False
#         self._thread = None
#
#     def submit_alternate_side_order(self):
#         order_id = self.id_generator.next()
#         order = Order(order_id, self.side, 0.1, "BTCUSDT", None, OrderType.Market)
#         logging.info("Submitting order: %s", order)
#         self.remote_order_client.submit_order(order)
#         # Flip the side for next order
#         self.side = Side.BUY if self.side == Side.SELL else Side.SELL
#
#     def start(self):
#         if self._thread is not None and self._thread.is_alive():
#             logging.error("Submit loop already running.")
#             return
#
#         self._running = True
#
#         def loop():
#             while self._running:
#                 try:
#                     self.submit_alternate_side_order()
#                     time.sleep(self.interval)
#                 except Exception as e:
#                     logging.error("Error in order submission loop: %s", e)
#
#         self._thread = threading.Thread(target=loop, daemon=True)
#         self._thread.start()
#
#     def stop(self):
#         self._running = False
#         if self._thread:
#             self._thread.join(timeout=1)
