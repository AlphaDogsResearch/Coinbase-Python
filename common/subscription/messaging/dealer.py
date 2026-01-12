import json
import logging
from typing import Type

import zmq
import time
import uuid
import random
import threading

from common.config_logging import to_stdout
from common.interface_book import PriceLevel, OrderBook
from common.interface_reference_data import ReferenceData
from common.interface_reference_point import MarkPrice
from common.interface_req_res import WalletResponse, AccountResponse, PositionResponse, \
    MarginInfoResponse, CommissionRateResponse, TradesResponse, ReferenceDataResponse
from common.seriallization import Serializable
from common.subscription.messaging.event_handler import EventHandler
from common.subscription.messaging.gateway_server_handler import EventHandlerImpl

REQUEST_TIMEOUT_MS = 2000
HEARTBEAT_INTERVAL_SEC = 5
HEARTBEAT_TIMEOUT_SEC = 10
BACKOFF_MIN = 1
BACKOFF_MAX = 60


class DealerClient:
    def __init__(self, name: str, host: str, port: int):
        self.ctx = zmq.Context()
        self.identity = uuid.uuid4().hex.encode()
        self.socket = None

        self.last_contact = time.time()
        self.backoff = BACKOFF_MIN
        self.connected = False
        self.name = name
        self.address = "tcp://{}:{}".format(host, port)
        self.lock = threading.Lock()
        self.running = True

        # user-defined message handlers
        self.handlers : dict[bytes, EventHandler] = {}
        self.connection_handler = []

        self.connect()
        self.bg_thread = threading.Thread(target=self._run, daemon=True)
        self.bg_thread.start()


    def register_on_connected(self,callback):
        self.connection_handler.append(callback)

    def change_connection_state(self,connection_state :bool):
        if self.connected!= connection_state:
            logging.info(f"[{self.name}] Connection state changed to {connection_state}")
            self.connected = connection_state
            for listener in self.connection_handler:
                listener(self.connected)

    def register_handler(self, msg_type: bytes, callback :EventHandler):
        """Register a callback for a specific message type"""
        self.handlers[msg_type] = callback

    def connect(self):
        if self.socket:
            self.socket.close()

        self.socket = self.ctx.socket(zmq.DEALER)

        # For high-volume applications, use even larger values
        self.socket.setsockopt(zmq.SNDHWM, 1000)  # Send buffer: 1000 messages
        self.socket.setsockopt(zmq.RCVHWM, 1000)  # Receive buffer: 1000 messages
        # If using TCP transport
        self.socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 30)
        self.socket.setsockopt(zmq.LINGER, 0)

        self.socket.setsockopt(zmq.IDENTITY, self.identity)
        self.socket.connect(self.address)

        logging.info(f"[{self.name}] [Client] Connected TCP as {self.identity} to {self.address}")

        self.change_connection_state(False)
        self.last_contact = time.time()
        self.send_logon()

    def send_logon(self):
        try:
            self.socket.send_multipart([b"", b"LOGON_REQUEST"])
            logging.info(f"[{self.name}] [Client] -> LOGON_REQUEST")
            self.last_contact = time.time()
        except zmq.ZMQError:
            pass

    def sleep_with_backoff(self):
        delay = self.backoff + random.random()
        logging.info(f"[{self.name}] [Client] Reconnect wait: {delay:.1f} sec")
        time.sleep(delay)
        self.backoff = min(self.backoff * 2, BACKOFF_MAX)

    def send_heartbeat(self):
        try:
            self.socket.send_multipart([b"", b"PING"])
            logging.debug(f"[{self.name}] [Client] -> PING")
            self.last_contact = time.time()
        except zmq.ZMQError:
            pass

    def _run(self):
        while self.running:
            # Receive messages
            try:
                parts = self.socket.recv_multipart(flags=zmq.NOBLOCK)
                payload = parts[-1]

                logging.debug(f"[{self.name}] [Client] -> {payload}")
                self.last_contact = time.time()

                handled = False

                # LOGON_RESPONSE
                if payload == b"LOGON_RESPONSE":
                    logging.info(f"[{self.name}] [Client] <- LOGON_RESPONSE")
                    with self.lock:
                        self.change_connection_state(True)
                        self.backoff = BACKOFF_MIN
                    if b"LOGON_RESPONSE" in self.handlers:
                        self.handlers[b"LOGON_RESPONSE"].handle(identity="",payload=payload)
                        handled = True

                # PONG
                elif payload == b"PONG":
                    logging.debug(f"[{self.name}] [Client] <- PONG")
                    if b"PONG" in self.handlers:
                        self.handlers[b"PONG"].handle(identity="",payload=payload)
                        handled = True

                # Other business messages
                else:
                    logging.debug(f"[{self.name}] [Client] Reply: {parts}")
                    if b"*" in self.handlers:
                        # wildcard handler
                        self.handlers[b"*"].handle(identity="", payload=payload)
                        handled = True

                if not handled:
                    pass  # message not handled, default logging.info()ed

            except zmq.Again:
                pass

            # Heartbeat if idle and logged on
            with self.lock:
                idle = time.time() - self.last_contact
                if idle >= HEARTBEAT_INTERVAL_SEC and self.connected:
                    self.send_heartbeat()

                # Detect lost connection
                if time.time() - self.last_contact > HEARTBEAT_TIMEOUT_SEC:
                    logging.info(f"[{self.name}] [Client] LOST — reconnecting…")
                    self.change_connection_state(False)
                    self.connect()
                    self.sleep_with_backoff()

            time.sleep(0.1)

    def send(self, msg:Serializable):
        """Send message to server."""
        self.send_request(json.dumps(msg.to_dict()).encode())

    def send_request(self, data: bytes):
        with self.lock:
            if not self.connected:
                logging.info(f"[{self.name}] [Client] Waiting for LOGON_RESPONSE before sending…")
                return
            self.socket.send_multipart([b"", data])
            logging.info(f"[Client] Send: {data}")
            # self.last_contact = time.time()

    def stop(self):
        self.running = False
        self.bg_thread.join(timeout=1)
        self.socket.close()
        self.ctx.term()
        logging.info(f"[{self.name}] [Client] Stopped")



if __name__ == "__main__":
    def callback(ident:str,obj:object):
        logging.info(f"Received event: {ident} {obj}")
        handle_message(ident,obj)

    def handle_message(ident: str, msg: object):
       if isinstance(msg, OrderBook):
           logging.info(f"Received OrderBook: {ident} {msg}")

    to_stdout()
    client = DealerClient("Remote Order Order Connection","localhost",5555)

    MESSAGE_TYPES: tuple[Type[Serializable], ...] = (
        OrderBook,
        MarkPrice,
        PriceLevel
    )

    business_message_handler = EventHandlerImpl(callback, *MESSAGE_TYPES)
    # Register handlers
    client.register_handler(b"*", business_message_handler)  # wildcard for all other messages

    # Send business messages in main thread
    try:
        while True:
            pass
            # order = Order("A123",Side.BUY,0,"BTCUSDT",current_milli_time(),OrderType.Limit,123,)
            # logging.info(f"Submitted Order: {order}")
            # client.send_request(json.dumps(order.to_dict()).encode())
            # time.sleep(3)
    except KeyboardInterrupt:
        client.stop()
