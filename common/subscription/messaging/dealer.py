import json
import logging
import threading
import time
import uuid

import zmq

from common.interface_book import OrderBook
from common.interface_order import Trade, Order
from common.seriallization import Serializable
from common.subscription.registry import Register, Unregister


class Dealer:
    def __init__(self, port: int, bind: bool = False, name: str = None, identity: str = None):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt(zmq.SNDHWM, 1)

        self.identity = identity or f"dealer-{uuid.uuid4().hex[:8]}"
        self.socket.setsockopt(zmq.IDENTITY, self.identity.encode())
        self.name = name or self.identity

        address = f"tcp://*:{port}" if bind else f"tcp://localhost:{port}"
        if bind:
            logging.info("[%s] Binding to %s", self.name, address)
            self.socket.bind(address)
        else:
            logging.info("[%s] Connecting to %s", self.name, address)
            self.socket.connect(address)

        self.running = False
        self.receiver_thread = None
        self.registered = False

    def start_receiving(self, callback):
        if self.receiver_thread is not None:
            raise RuntimeError("Receiver already started.")
        self.running = True

        def receive_loop():
            self._try_register()
            while self.running:
                try:
                    msg = self.socket.recv(flags=zmq.NOBLOCK)
                    try:
                        data = json.loads(msg.decode())
                        cls_name = data.get("__class__")
                        if cls_name == "OrderBook":
                            obj = OrderBook.from_dict(data)
                        elif cls_name == "Order":
                            obj = Order.from_dict(data)
                        elif cls_name == "Trade":
                            obj = Trade.from_dict(data)
                        else:
                            obj = data
                    except Exception:
                        obj = msg.decode()
                    print(f"[{self.name}] Received: {obj}")
                    if isinstance(obj, dict) and obj.get("__class__") == "Ack":
                        print(f"[{self.name}] Registration acknowledged: {obj}")
                    callback(obj)
                except zmq.Again:
                    time.sleep(0.01)

        self.receiver_thread = threading.Thread(target=receive_loop, daemon=True)
        self.receiver_thread.start()

    def _try_register(self):
        if not self.registered:
            try:
                self.send(Register(self.identity))
                self.registered = True
            except Exception as e:
                logging.error("[%s] Registration failed: %s", self.name, e)

    def send(self, obj):
        msg = json.dumps(obj.to_dict()) if isinstance(obj, Serializable) else json.dumps(obj) if isinstance(obj, dict) else str(obj)
        print(f"[{self.name}] Sending: {msg}")
        self.socket.send(msg.encode(), flags=zmq.NOBLOCK)

    def stop(self):
        self.send(Unregister(self.identity))
        self.running = False
        if self.receiver_thread:
            self.receiver_thread.join(timeout=1)
        self.socket.close()
        self.context.term()


