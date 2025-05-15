import logging

import zmq
import time

class Publisher:
    def __init__(self, port: int, name: str):
        self.name = name
        self.port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{port}")
        print(f"[{self.name}] Bound to port {port}")
        time.sleep(1)  # Give time for subscribers to connect

    def publish(self, message: str):
        full_message = f"{self.name}: {message}"
        self.socket.send_string(full_message)
        print(f"[{self.name}] Published: {full_message}")

    def depth_callback(self, exchange, book):
        logging.info("Exchange %s " % exchange)
        self.publish(book)

    def close(self):
        self.socket.close()
        self.context.term()
        print(f"[{self.name}] Closed publisher.")
