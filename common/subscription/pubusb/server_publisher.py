import logging

import zmq
import time

from common.interface_book import OrderBook


class Publisher:
    def __init__(self, port: int, name: str):
        self.name = name
        self.port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{port}")
        print(f"[{self.name}] Bound to port {port}")

    def publish(self, message: OrderBook):
        full_message = f"{self.name}: {message}"
        self.socket.send_pyobj(message)
        print(f"[{self.name}] Published: {message}")

    def depth_callback(self, exchange, book: OrderBook):
        # logging.info("Exchange %s " % exchange)
        self.publish(book)

    def close(self):
        self.socket.close()
        self.context.term()
        print(f"[{self.name}] Closed publisher.")
