import json
import logging
import threading
import time
import uuid

import zmq

from common.interface_book import OrderBook
from common.interface_order import Order, Trade
from common.seriallization import Serializable
from common.subscription.registry import Registry, Ack


class Router:
    def __init__(self, port: int, bind: bool = True, name: str = None, identity: str = None):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.setsockopt(zmq.SNDHWM, 1)

        self.identity = identity or f"router-{uuid.uuid4().hex[:8]}"
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
        self.registry = Registry()

    def start_receiving(self, callback):
        if self.receiver_thread is not None:
            raise RuntimeError("Receiver already started.")
        self.running = True

        def receive_loop():
            while self.running:
                try:
                    parts = self.socket.recv_multipart(flags=zmq.NOBLOCK)
                    if len(parts) < 3:
                        continue
                    identity, empty, msg = parts
                    try:
                        data = json.loads(msg.decode())
                        cls_name = data.get("__class__")
                        if cls_name == "Register":
                            self.registry.register(identity)
                            self.send(identity, Ack("registered"))
                            continue
                        elif cls_name == "Unregister":
                            self.registry.unregister(identity)
                            continue
                        elif cls_name == "OrderBook":
                            obj = OrderBook.from_dict(data)
                        elif cls_name == "Order":
                            obj = Order.from_dict(data)
                        elif cls_name == "Trade":
                            obj = Trade.from_dict(data)
                        else:
                            obj = data
                    except Exception:
                        obj = msg.decode()
                    print(f"[{self.name}] Received from {identity}: {obj}")
                    callback(identity, obj)
                except zmq.Again:
                    time.sleep(0.01)

        self.receiver_thread = threading.Thread(target=receive_loop, daemon=True)
        self.receiver_thread.start()

    def send(self, identity, obj):
        msg = json.dumps(obj.to_dict()) if isinstance(obj, Serializable) else json.dumps(obj) if isinstance(obj, dict) else str(obj)
        print(f"[{self.name}] Sending to {identity}: {msg}")
        self.socket.send_multipart([identity, b"", msg.encode()], flags=zmq.NOBLOCK)

    def broadcast(self, obj):
        for identity in self.registry.get_all():
            self.send(identity, obj)

    def list_known_dealers(self):
        return self.registry.get_all()

    def stop(self):
        self.running = False
        if self.receiver_thread:
            self.receiver_thread.join(timeout=1)
        self.socket.close()
        self.context.term()
