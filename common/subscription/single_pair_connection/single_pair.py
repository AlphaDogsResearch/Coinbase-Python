import logging
import pickle
import time

import zmq
import threading

from common.interface_book import OrderBook
from common.interface_order import Order, Trade, OrderEvent
from common.interface_reference_point import MarkPrice
from common.interface_req_res import WalletResponse, WalletRequest, AccountResponse, AccountRequest, PositionResponse, \
    PositionRequest, MarginInfoResponse, MarginInfoRequest, CommissionRateResponse, CommissionRateRequest, \
    TradesResponse, TradesRequest


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
                        logging.info(f"[{self.name}] Received from {identity}: {msg}")
                        callback(msg)
                    else:
                        # DEALER or others receive single part pickled msg

                        try:
                            msg = self.socket.recv_pyobj()
                            # logging.info(f"[{self.name}] Received: {msg}")
                            callback(msg)
                        except Exception as e:
                            if hasattr(e, 'message'):
                                logging.info(e.message)
                            else:
                                logging.info(e)


                except zmq.Again:
                    time.sleep(0.01)  # sleep 10ms to avoid CPU burn
                    continue

        self.receiver_thread = threading.Thread(target=receive_loop, daemon=True)
        self.receiver_thread.start()

    def send(self, message: str):
        """Send a message to the peer."""
        logging.info(f"[{self.name}] Sending Message: {message}")
        self.socket.send_string(message,flags=zmq.NOBLOCK)

    def send_wallet_response(self,wallet_response:WalletResponse):
        logging.info(f"[{self.name}] Sending Wallet Response: {wallet_response}")
        self.socket.send_pyobj(wallet_response,flags=zmq.NOBLOCK)

    def send_wallet_request(self, wallet_request:WalletRequest):
        logging.info(f"[{self.name}] Sending Wallet Request: {wallet_request}")
        self.socket.send_pyobj(wallet_request, flags=zmq.NOBLOCK)

    def send_account_response(self, account_response: AccountResponse):
        logging.info(f"[{self.name}] Sending Account Response: {account_response}")
        self.socket.send_pyobj(account_response, flags=zmq.NOBLOCK)

    def send_account_request(self, account_request: AccountRequest):
        logging.info(f"[{self.name}] Sending Account Request: {account_request}")
        self.socket.send_pyobj(account_request, flags=zmq.NOBLOCK)

    def send_position_response(self, position_response: PositionResponse):
        logging.info(f"[{self.name}] Sending Position Response: {position_response}")
        self.socket.send_pyobj(position_response, flags=zmq.NOBLOCK)

    def send_position_request(self, position_request: PositionRequest):
        logging.info(f"[{self.name}] Sending Position Request: {position_request}")
        self.socket.send_pyobj(position_request, flags=zmq.NOBLOCK)

    def send_margin_info_response(self, margin_info_response: MarginInfoResponse):
        logging.info(f"[{self.name}] Sending Margin Info Response: {margin_info_response}")
        self.socket.send_pyobj(margin_info_response, flags=zmq.NOBLOCK)

    def send_margin_info_request(self, margin_info_request: MarginInfoRequest):
        logging.info(f"[{self.name}] Sending Margin Info Request: {margin_info_request}")
        self.socket.send_pyobj(margin_info_request, flags=zmq.NOBLOCK)

    def send_commission_rate_response(self, commission_rate_response: CommissionRateResponse):
        logging.info(f"[{self.name}] Sending Commission Rate Response: {commission_rate_response}")
        self.socket.send_pyobj(commission_rate_response, flags=zmq.NOBLOCK)

    def send_commission_rate_request(self, commission_rate_request: CommissionRateRequest):
        logging.info(f"[{self.name}] Sending Commission Rate Request: {commission_rate_request}")
        self.socket.send_pyobj(commission_rate_request, flags=zmq.NOBLOCK)

    def send_trades_response(self, trades_response: TradesResponse):
        logging.info(f"[{self.name}] Sending Trades Response: {trades_response}")
        self.socket.send_pyobj(trades_response, flags=zmq.NOBLOCK)

    def send_trades_request(self, trades_request: TradesRequest):
        logging.info(f"[{self.name}] Sending Trades Request: {trades_request}")
        self.socket.send_pyobj(trades_request, flags=zmq.NOBLOCK)

    def send_trade(self,trade:Trade):
        logging.info(f"[{self.name}] Sending Trade: {trade}")
        self.socket.send_pyobj(trade,flags=zmq.NOBLOCK)

    def send_order(self, order: Order):
        """Send an order to the peer."""
        logging.info(f"[{self.name}] Sending Order: {order}")
        self.socket.send_pyobj(order,flags=zmq.NOBLOCK)

    def publish_order_event(self,order_event: OrderEvent):
        logging.info(f"[{self.name}] Sending Order: {order_event}")
        self.socket.send_pyobj(order_event,flags=zmq.NOBLOCK)

    def publish_market_data_event(self, order_book: OrderBook):
        """Send a market data to the peer."""
        logging.debug(f"[{self.name}] Sending Market Data: {order_book}")
        try:
            self.socket.send_pyobj(order_book,flags=zmq.NOBLOCK)
        except zmq.Again:
            logging.error(f"Dropped message {order_book}")
            time.sleep(1)

    def publish_mark_price(self, mark_price: MarkPrice):
        """Send a mark price to the peer."""
        logging.debug(f"[{self.name}] Sending Mark Price: {mark_price}")
        try:
            self.socket.send_pyobj(mark_price,flags=zmq.NOBLOCK)
        except zmq.Again:
            logging.error(f"Dropped message {mark_price}")
            time.sleep(1)

    def stop(self):
        """Stop the background receiver and clean up."""
        self.running = False
        if self.receiver_thread:
            self.receiver_thread.join(timeout=1)
        self.socket.close()
        self.context.term()
