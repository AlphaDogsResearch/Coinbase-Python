import json
import logging
import threading
import time

import zmq

from common.interface_book import OrderBook
from common.interface_order import Order, Trade
from common.seriallization import Serializable


class JsonMessenger:
    def __init__(self, port: int, bind: bool = False, name: str = "Peer"):
        self.context = zmq.Context()
        self.type = zmq.PAIR
        self.socket = self.context.socket(self.type)
        self.socket.setsockopt(zmq.SNDHWM, 1)
        self.name = name

        if bind:
            address = f"tcp://*:{port}"
            self.socket.bind(address)
            logging.info("Created ROUTER")
        else:
            address = f"tcp://localhost:{port}"
            self.socket.connect(address)
            logging.info("Created DEALER")

        self.running = False
        self.receiver_thread = None

    def start_receiving(self, callback):
        if self.receiver_thread is not None:
            raise RuntimeError("Receiver already started.")

        self.running = True

        def receive_loop():
            while self.running:
                try:
                    msg = self.socket.recv_string(flags=zmq.NOBLOCK)
                    try:
                        data = json.loads(msg)
                        class_name = data.get("__class__")
                        if class_name == "OrderBook":
                            obj = OrderBook.from_dict(data)
                        elif class_name == "Order":
                            obj = Order.from_dict(data)
                        elif class_name == "Trade":
                            obj = Trade.from_dict(data)
                        else:
                            obj = data  # generic dict
                    except (json.JSONDecodeError, KeyError, TypeError):
                        obj = msg  # plain string fallback
                    logging.info("%s Received %s"%self.name %obj)

                    callback(obj)

                except zmq.Again:
                    time.sleep(0.01)

        self.receiver_thread = threading.Thread(target=receive_loop, daemon=True)
        self.receiver_thread.start()

    def send_string(self, msg: str):
        print(f"[{self.name}] Sending plain string: {msg}")
        try:
            self.socket.send_string(msg, flags=zmq.NOBLOCK)
        except zmq.Again:
            print(f"Dropped string message: {msg}")
            time.sleep(1)

    def send_serializable(self, obj: Serializable):
        print(f"[{self.name}] Sending: {obj}")
        try:
            self.socket.send_string(json.dumps(obj.to_dict()), flags=zmq.NOBLOCK)
        except zmq.Again:
            print(f"Dropped message {obj}")
            time.sleep(1)

    def stop(self):
        self.running = False
        if self.receiver_thread:
            self.receiver_thread.join(timeout=1)
        self.socket.close()
        self.context.term()
