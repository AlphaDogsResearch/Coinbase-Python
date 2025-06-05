import logging
import pickle
import time

import zmq
import threading

from common.interface_book import OrderBook
from common.interface_order import Order, Trade
from common.interface_req_res import WalletResponse, WalletRequest, AccountResponse, AccountRequest, PositionResponse, \
    PositionRequest


class PairConnection:
    def __init__(self, port: int,bind: bool = False, name: str = "Peer"):
        self.context = zmq.Context()

        if bind:
            # server
            self.type = zmq.PAIR
            logging.info("Created ROUTER")
        else:
            # client
            self.type = zmq.PAIR
            logging.info("Created DEALER")
        self.socket = self.context.socket(self.type)
        self.socket.setsockopt(zmq.SNDHWM, 1)
        self.name = name

        if bind:
            address = f"tcp://*:{port}"
            self.socket.bind(address)
        else:
            address = f"tcp://localhost:{port}"
            self.socket.connect(address)

        self.running = False
        self.receiver_thread = None

    def start_receiving(self, callback):
        """
        Start a background thread to receive messages.
        The callback will be called with each received message.
        """
        if self.receiver_thread is not None:
            raise RuntimeError("Receiver already started.")

        self.running = True

        def receive_loop():
            while self.running:
                try:
                    if self.type == zmq.ROUTER:
                        # ROUTER receives multipart: [identity, empty, payload]
                        parts = self.socket.recv_multipart(flags=zmq.NOBLOCK)
                        if len(parts) < 3:
                            continue  # incomplete message or malformed
                        identity, empty, payload = parts
                        msg = pickle.loads(payload)
                        print(f"[{self.name}] Received from {identity}: {msg}")
                        callback(msg)
                    else:
                        # DEALER or others receive single part pickled msg

                        try:
                            msg = self.socket.recv_pyobj()
                            # print(f"[{self.name}] Received: {msg}")
                            callback(msg)
                        except Exception as e:
                            if hasattr(e, 'message'):
                                print(e.message)
                            else:
                                print(e)


                except zmq.Again:
                    time.sleep(0.01)  # sleep 10ms to avoid CPU burn
                    continue

        self.receiver_thread = threading.Thread(target=receive_loop, daemon=True)
        self.receiver_thread.start()

    def send(self, message: str):
        """Send a message to the peer."""
        print(f"[{self.name}] Sending Message: {message}")
        self.socket.send_string(message,flags=zmq.NOBLOCK)

    def send_wallet_response(self,wallet_response:WalletResponse):
        print(f"[{self.name}] Sending Wallet Response: {wallet_response}")
        self.socket.send_pyobj(wallet_response,flags=zmq.NOBLOCK)

    def send_wallet_request(self, wallet_request:WalletRequest):
        print(f"[{self.name}] Sending Wallet Request: {wallet_request}")
        self.socket.send_pyobj(wallet_request, flags=zmq.NOBLOCK)

    def send_account_response(self, account_response: AccountResponse):
        print(f"[{self.name}] Sending Account Response: {account_response}")
        self.socket.send_pyobj(account_response, flags=zmq.NOBLOCK)

    def send_account_request(self, account_request: AccountRequest):
        print(f"[{self.name}] Sending Account Request: {account_request}")
        self.socket.send_pyobj(account_request, flags=zmq.NOBLOCK)

    def send_position_response(self, position_response: PositionResponse):
        print(f"[{self.name}] Sending Position Response: {position_response}")
        self.socket.send_pyobj(position_response, flags=zmq.NOBLOCK)

    def send_position_request(self, position_request: PositionRequest):
        print(f"[{self.name}] Sending Position Request: {position_request}")
        self.socket.send_pyobj(position_request, flags=zmq.NOBLOCK)

    def send_trade(self,trade:Trade):
        print(f"[{self.name}] Sending Trade: {trade}")
        self.socket.send_pyobj(trade,flags=zmq.NOBLOCK)

    def send_order(self, order: Order):
        """Send an order to the peer."""
        print(f"[{self.name}] Sending Order: {order}")
        self.socket.send_pyobj(order,flags=zmq.NOBLOCK)

    def send_market_data(self, order_book: OrderBook):
        """Send a market data to the peer."""
        print(f"[{self.name}] Sending Market Data: {order_book}")
        try:
            self.socket.send_pyobj(order_book,flags=zmq.NOBLOCK)
        except zmq.Again:
            print(f"Dropped message {order_book}")
            time.sleep(1)

    def stop(self):
        """Stop the background receiver and clean up."""
        self.running = False
        if self.receiver_thread:
            self.receiver_thread.join(timeout=1)
        self.socket.close()
        self.context.term()
