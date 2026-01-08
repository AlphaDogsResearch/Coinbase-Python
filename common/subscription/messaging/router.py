import json
import logging
import threading
import time
from typing import Type

import zmq

from common.config_logging import to_stdout
from common.interface_book import OrderBook, PriceLevel
from common.interface_order import Order, Side
from common.interface_req_res import WalletRequest
from common.seriallization import Serializable
from common.subscription.messaging.event_handler import EventHandler
from common.subscription.messaging.gateway_server_handler import EventHandlerImpl
from common.time_utils import current_milli_time


class RouterServer:
    def __init__(self, name: str, handler: EventHandler, host: str, port: int):
        self.name = name
        self.ctx = zmq.Context()
        self.socket = self.ctx.socket(zmq.ROUTER)
        self.address = "tcp://{}:{}".format(host, port)

        # For high-volume applications, use even larger values
        self.socket.setsockopt(zmq.SNDHWM, 1000)  # Send buffer: 1000 messages
        self.socket.setsockopt(zmq.RCVHWM, 1000)  # Receive buffer: 1000 messages
        # If using TCP transport
        self.socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 30)
        self.socket.setsockopt(zmq.LINGER, 0)

        self.socket.bind(self.address)
        self.socket.setsockopt(zmq.ROUTER_MANDATORY, 1)

        self._running = True  # <-- shutdown flag
        self.handler = handler

        self.bg_thread = threading.Thread(target=self.run, daemon=True)
        self.bg_thread.start()

        logging.info(f"[{self.name} Server] Ready on {self.address}")

        self.clients = {}  # ident -> logon time

    def stop(self):
        """Gracefully stop server thread and close resources."""
        logging.info(f"{self.name}[Server] Stopping...")
        self._running = False
        # allow thread to break recv loop
        self.socket.close(0)
        self.ctx.term()
        self.bg_thread.join(timeout=2.0)  # optional
        logging.info(f"[{self.name}Server] Stopped.")

    def send(self, ident: str, msg: Serializable):
        """Send message to server."""
        self.send_internal(ident, json.dumps(msg.to_dict()).encode())

    def send_internal(self, ident: str, msg: bytes):
        if self._running:
            try:
                self.socket.send_multipart([ident, b"", msg])
            except zmq.ZMQError as e:
                logging.error(f"Failed to send to identity {ident} {msg} ", exc_info=e)
                logging.info(f"[{self.name} Server] Unable to connect removing {ident} from clients")
                self.clients.pop(ident, None)
                logging.info(f"Clients {self.clients}")

    '''
    b"" empty bytes delimiter for router only 
    '''

    def handle_message(self, ident, payload):
        logging.info(f"[{self.name} Server] From {ident}: {payload}")

        if payload == b"LOGON_REQUEST":
            self.socket.send_multipart([ident, b"", b"LOGON_RESPONSE"])
            logging.info(f"[{self.name} Server] -> LOGON_RESPONSE to {ident}")
            now = time.time()
            self.clients[ident] = now

        elif payload == b"PING":
            self.socket.send_multipart([ident, b"", b"PONG"])
            logging.info(f"[{self.name}Server] -> PONG")

        else:
            self.handler.handle(ident, payload)
            # TODO do we need the ACK ??
            # self.socket.send_multipart([ident, b"", b"ACK:" + payload])

    def send_to_all(self, msg: Serializable):
        self.send_to_all_clients(json.dumps(msg.to_dict()).encode())

    def send_to_all_clients(self, message: bytes):
        for ident in list(self.clients):
            self.send_internal(ident, message)

    def run(self):
        while self._running:
            try:
                parts = self.socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                # no message yet
                time.sleep(0.01)
                continue
            except zmq.error.ZMQError:
                # socket closed -> exit thread
                break

            if len(parts) == 3:
                ident, _, payload = parts
                self.handle_message(ident, payload)
            else:
                logging.error(f"[{self.name} Server] Invalid message: {parts}")


if __name__ == "__main__":
    to_stdout()


    def callback(ident: str, obj: object):
        logging.info(f"Received event: {ident} {obj}")
        handle_message(ident, obj)


    MESSAGE_TYPES: tuple[Type[object], ...] = (
        # WalletRequest,
        # AccountRequest,
        # PositionRequest,
        # MarginInfoRequest,
        # CommissionRateRequest,
        # TradesRequest,
        # ReferenceDataRequest,
        Order,
        # Side
    )

    server_handler = EventHandlerImpl(callback, *MESSAGE_TYPES)
    server = RouterServer("Order Connection", server_handler, "localhost", 5555)


    def handle_message(ident: str, msg: object):
        side = Side.BUY
        if isinstance(msg, Order):
            logging.info(f"Received order: {ident} {msg}")
        if isinstance(msg, WalletRequest):
            balance = {'test': 123}
            response = msg.handle(balance)
            server.send_internal(ident, json.dumps(response.to_dict()).encode())


    try:
        while True:
            reference_data_dict = {}
            symbol = "BTCUSDT"
            bid = PriceLevel(123.1, 100, "123")
            ask = PriceLevel(223.1, 100, "223")
            order_book = OrderBook(current_milli_time(), symbol, [bid], [ask])
            logging.info(f"Sending OrderBook {order_book}")
            server.send_to_all_clients(json.dumps(order_book.to_dict()).encode())
            time.sleep(5)
    except KeyboardInterrupt:
        server.stop()
