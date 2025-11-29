import logging
import pickle
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Dict, Any, Optional
import zmq
import threading

from common.interface_book import OrderBook
from common.interface_order import Order, Trade, OrderEvent
from common.interface_reference_point import MarkPrice
from common.interface_req_res import WalletResponse, WalletRequest, AccountResponse, AccountRequest, PositionResponse, \
    PositionRequest, MarginInfoResponse, MarginInfoRequest, CommissionRateResponse, CommissionRateRequest, \
    TradesResponse, TradesRequest, ReferenceDataResponse, ReferenceDataRequest


@dataclass
class ConnectionStats:
    """Statistics for monitoring connection health"""
    messages_sent: int = 0
    messages_received: int = 0
    messages_dropped: int = 0
    send_errors: int = 0
    receive_errors: int = 0
    avg_send_latency: float = 0.0
    last_send_time: float = 0.0
    last_receive_time: float = 0.0
    message_types_sent: Dict[str, int] = None
    message_types_received: Dict[str, int] = None
    zmq_again_errors: int = 0  # Track NOBLOCK failures specifically

    def __post_init__(self):
        if self.message_types_sent is None:
            self.message_types_sent = defaultdict(int)
        if self.message_types_received is None:
            self.message_types_received = defaultdict(int)


class PairConnection:
    def __init__(self, port: int, bind: bool = False, name: str = "Peer"):
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

        # For high-volume applications, use even larger values
        self.socket.setsockopt(zmq.SNDHWM, 1000)  # Send buffer: 1000 messages
        self.socket.setsockopt(zmq.RCVHWM, 1000)  # Receive buffer: 1000 messages
        # If using TCP transport
        self.socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 30)

        # Monitoring setup
        self.stats = ConnectionStats()
        self.latency_history = deque(maxlen=1000)  # Keep last 1000 latencies
        self.drop_history = deque(maxlen=500)  # Keep last 500 drop events
        self.monitoring_enabled = True
        self.stats_log_interval = 300  # Log stats every 5 minute

        self.name = name

        if bind:
            address = f"tcp://*:{port}"
            self.socket.bind(address)
        else:
            address = f"tcp://localhost:{port}"
            self.socket.connect(address)

        self.running = False
        self.receiver_thread = None
        self.stats_thread = None

    def _update_send_stats(self, message_type: str, success: bool, latency: float = 0.0, zmq_again: bool = False):
        """Update monitoring statistics for sent messages"""
        if not self.monitoring_enabled:
            return

        current_time = time.time()
        self.stats.last_send_time = current_time

        if success:
            self.stats.messages_sent += 1
            self.stats.message_types_sent[message_type] += 1
            if latency > 0:
                self.latency_history.append(latency)
                self.stats.avg_send_latency = sum(self.latency_history) / len(self.latency_history)
        else:
            self.stats.messages_dropped += 1
            self.stats.send_errors += 1
            if zmq_again:
                self.stats.zmq_again_errors += 1
            self.drop_history.append({
                'time': current_time,
                'type': message_type,
                'zmq_again': zmq_again
            })

    def _update_receive_stats(self, message_type: str):
        """Update monitoring statistics for received messages"""
        if not self.monitoring_enabled:
            return

        self.stats.messages_received += 1
        self.stats.message_types_received[message_type] += 1
        self.stats.last_receive_time = time.time()

    def _stats_monitor_loop(self):
        """Background thread to periodically log statistics"""
        while self.running:
            time.sleep(self.stats_log_interval)
            if self.monitoring_enabled:
                self.log_current_stats()

    def log_current_stats(self):
        """Log current connection statistics"""
        total_operations = self.stats.messages_sent + self.stats.messages_dropped
        drop_rate = (self.stats.messages_dropped / total_operations * 100) if total_operations > 0 else 0
        zmq_again_rate = (self.stats.zmq_again_errors / total_operations * 100) if total_operations > 0 else 0

        # Calculate time since last activity
        current_time = time.time()
        time_since_last_send = current_time - self.stats.last_send_time if self.stats.last_send_time > 0 else float(
            'inf')
        time_since_last_receive = current_time - self.stats.last_receive_time if self.stats.last_receive_time > 0 else float(
            'inf')

        logging.info(f"[{self.name}] === Connection Statistics ===")
        logging.info(f"  Messages Sent: {self.stats.messages_sent}")
        logging.info(f"  Messages Received: {self.stats.messages_received}")
        logging.info(f"  Messages Dropped: {self.stats.messages_dropped} ({drop_rate:.2f}%)")
        logging.info(f"  ZMQ Again Errors: {self.stats.zmq_again_errors} ({zmq_again_rate:.2f}%)")
        logging.info(f"  Average Send Latency: {self.stats.avg_send_latency * 1000:.2f}ms")
        logging.info(f"  Time since last send: {time_since_last_send:.2f}s")
        logging.info(f"  Time since last receive: {time_since_last_receive:.2f}s")

        if self.stats.message_types_sent:
            logging.info("  Message Types Sent:")
            for msg_type, count in sorted(self.stats.message_types_sent.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / self.stats.messages_sent * 100) if self.stats.messages_sent > 0 else 0
                logging.info(f"    {msg_type}: {count} ({percentage:.1f}%)")

        if self.stats.message_types_received:
            logging.info("  Message Types Received:")
            for msg_type, count in sorted(self.stats.message_types_received.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / self.stats.messages_received * 100) if self.stats.messages_received > 0 else 0
                logging.info(f"    {msg_type}: {count} ({percentage:.1f}%)")

        # Log recent drop events if any
        if self.drop_history:
            recent_drops = list(self.drop_history)[-5:]  # Last 5 drop events
            logging.info("  Recent Drop Events:")
            for drop in recent_drops:
                time_str = time.strftime("%H:%M:%S", time.localtime(drop['time']))
                logging.info(f"    {time_str} - {drop['type']} (ZMQ.Again: {drop['zmq_again']})")

        logging.info(f"[{self.name}] === End Statistics ===\n")

    def get_socket_status(self) -> Dict[str, Any]:
        """Get current socket status and metrics"""
        try:
            sndhwm = self.socket.get(zmq.SNDHWM)
            rcvhwm = self.socket.get(zmq.RCVHWM)
            events = self.socket.get(zmq.EVENTS)

            return {
                'sndhwm': sndhwm,
                'rcvhwm': rcvhwm,
                'events': events,
                'zmq_again_errors': self.stats.zmq_again_errors,
                'drop_rate': (self.stats.messages_dropped / max(self.stats.messages_sent + self.stats.messages_dropped,
                                                                1)) * 100,
                'messages_in_flight': self.stats.messages_sent - self.stats.messages_received,
                'current_time': time.time(),
                'last_send': self.stats.last_send_time,
                'last_receive': self.stats.last_receive_time
            }
        except Exception as e:
            logging.error(f"Error getting socket status: {e}")
            return {}

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
                        message_type = type(msg).__name__
                        self._update_receive_stats(message_type)
                        logging.info(f"[{self.name}] Received from {identity}: {msg}")
                        callback(msg)
                    else:
                        # DEALER or others receive single part pickled msg
                        try:
                            msg = self.socket.recv_pyobj()
                            message_type = type(msg).__name__
                            self._update_receive_stats(message_type)
                            # logging.info(f"[{self.name}] Received: {msg}")
                            callback(msg)
                        except Exception as e:
                            self.stats.receive_errors += 1
                            if hasattr(e, 'message'):
                                logging.error("Receiver loop %s",e.message)
                            else:
                                logging.error("Receiver loop %s",e)

                except zmq.Again:
                    # No messages available, sleep to avoid CPU burn
                    time.sleep(0.01)
                    continue

        self.receiver_thread = threading.Thread(target=receive_loop, daemon=True)
        self.receiver_thread.start()

        # Start stats monitoring thread
        self.stats_thread = threading.Thread(target=self._stats_monitor_loop, daemon=True,name=self.name)
        self.stats_thread.start()

        logging.info(f"[{self.name}] Started receiver and stats monitor threads")

    def _send_with_monitoring(self, obj: Any, obj_type: str = "Unknown"):
        """Send an object with monitoring"""
        start_time = time.time()
        try:
            self.socket.send_pyobj(obj, flags=zmq.NOBLOCK)
            latency = time.time() - start_time
            self._update_send_stats(obj_type, success=True, latency=latency)
            return True
        except zmq.Again:
            latency = time.time() - start_time
            self._update_send_stats(obj_type, success=False, latency=latency, zmq_again=True)
            logging.error(f"[{self.name}] ZMQ.Again - Dropped {obj_type}: {obj}")
            return False
        except Exception as e:
            latency = time.time() - start_time
            self._update_send_stats(obj_type, success=False, latency=latency)
            logging.error(f"[{self.name}] Error sending {obj_type}: {e}")
            return False

    def send(self, message: str):
        """Send a message to the peer."""
        logging.info(f"[{self.name}] Sending Message: {message}")
        success = self._send_with_monitoring(message, "StringMessage")
        if not success:
            logging.error(f"Dropped string message: {message}")

    def send_wallet_response(self, wallet_response: WalletResponse):
        logging.info(f"[{self.name}] Sending Wallet Response: {wallet_response}")
        success = self._send_with_monitoring(wallet_response, "WalletResponse")
        if not success:
            logging.error(f"Dropped WalletResponse: {wallet_response}")

    def send_wallet_request(self, wallet_request: WalletRequest):
        logging.info(f"[{self.name}] Sending Wallet Request: {wallet_request}")
        success = self._send_with_monitoring(wallet_request, "WalletRequest")
        if not success:
            logging.error(f"Dropped WalletRequest: {wallet_request}")

    def send_account_response(self, account_response: AccountResponse):
        logging.info(f"[{self.name}] Sending Account Response: {account_response}")
        success = self._send_with_monitoring(account_response, "AccountResponse")
        if not success:
            logging.error(f"Dropped AccountResponse: {account_response}")

    def send_account_request(self, account_request: AccountRequest):
        logging.info(f"[{self.name}] Sending Account Request: {account_request}")
        success = self._send_with_monitoring(account_request, "AccountRequest")
        if not success:
            logging.error(f"Dropped AccountRequest: {account_request}")

    def send_position_response(self, position_response: PositionResponse):
        logging.info(f"[{self.name}] Sending Position Response: {position_response}")
        success = self._send_with_monitoring(position_response, "PositionResponse")
        if not success:
            logging.error(f"Dropped PositionResponse: {position_response}")

    def send_position_request(self, position_request: PositionRequest):
        logging.info(f"[{self.name}] Sending Position Request: {position_request}")
        success = self._send_with_monitoring(position_request, "PositionRequest")
        if not success:
            logging.error(f"Dropped PositionRequest: {position_request}")

    def send_margin_info_response(self, margin_info_response: MarginInfoResponse):
        logging.info(f"[{self.name}] Sending Margin Info Response: {margin_info_response}")
        success = self._send_with_monitoring(margin_info_response, "MarginInfoResponse")
        if not success:
            logging.error(f"Dropped MarginInfoResponse: {margin_info_response}")

    def send_margin_info_request(self, margin_info_request: MarginInfoRequest):
        logging.info(f"[{self.name}] Sending Margin Info Request: {margin_info_request}")
        success = self._send_with_monitoring(margin_info_request, "MarginInfoRequest")
        if not success:
            logging.error(f"Dropped MarginInfoRequest: {margin_info_request}")

    def send_commission_rate_response(self, commission_rate_response: CommissionRateResponse):
        logging.info(f"[{self.name}] Sending Commission Rate Response: {commission_rate_response}")
        success = self._send_with_monitoring(commission_rate_response, "CommissionRateResponse")
        if not success:
            logging.error(f"Dropped CommissionRateResponse: {commission_rate_response}")

    def send_commission_rate_request(self, commission_rate_request: CommissionRateRequest):
        logging.info(f"[{self.name}] Sending Commission Rate Request: {commission_rate_request}")
        success = self._send_with_monitoring(commission_rate_request, "CommissionRateRequest")
        if not success:
            logging.error(f"Dropped CommissionRateRequest: {commission_rate_request}")

    def send_trades_response(self, trades_response: TradesResponse):
        logging.info(f"[{self.name}] Sending Trades Response: {trades_response}")
        success = self._send_with_monitoring(trades_response, "TradesResponse")
        if not success:
            logging.error(f"Dropped TradesResponse: {trades_response}")

    def send_trades_request(self, trades_request: TradesRequest):
        logging.info(f"[{self.name}] Sending Trades Request: {trades_request}")
        success = self._send_with_monitoring(trades_request, "TradesRequest")
        if not success:
            logging.error(f"Dropped TradesRequest: {trades_request}")


    def send_reference_data_response(self, reference_data_response: ReferenceDataResponse):
        logging.info(f"[{self.name}] Sending Reference Data Response: {reference_data_response}")
        success = self._send_with_monitoring(reference_data_response, "ReferenceDataResponse")
        if not success:
            logging.error(f"Dropped ReferenceDataResponse: {reference_data_response}")

    def send_reference_data_request(self, reference_data_request: ReferenceDataRequest):
        logging.info(f"[{self.name}] Sending Reference Data Request: {reference_data_request}")
        success = self._send_with_monitoring(reference_data_request, "ReferenceDataRequest")
        if not success:
            logging.error(f"Dropped Reference Data Request: {reference_data_request}")

    def send_trade(self, trade: Trade):
        logging.info(f"[{self.name}] Sending Trade: {trade}")
        success = self._send_with_monitoring(trade, "Trade")
        if not success:
            logging.error(f"Dropped Trade: {trade}")

    def send_order(self, order: Order):
        """Send an order to the peer."""
        logging.info(f"[{self.name}] Sending Order: {order}")
        success = self._send_with_monitoring(order, "Order")
        if not success:
            logging.error(f"Dropped Order: {order}")

    def publish_order_event(self, order_event: OrderEvent):
        logging.info(f"[{self.name}] Sending Order: {order_event}")
        success = self._send_with_monitoring(order_event, "OrderEvent")
        if not success:
            logging.error(f"Dropped OrderEvent: {order_event}")

    def publish_market_data_event(self, order_book: OrderBook):
        """Send a market data to the peer."""
        logging.debug(f"[{self.name}] Sending Market Data: {order_book}")
        success = self._send_with_monitoring(order_book, "OrderBook")
        if not success:
            logging.error(f"Dropped OrderBook: {order_book}")

    def publish_mark_price(self, mark_price: MarkPrice):
        """Send a mark price to the peer."""
        logging.debug(f"[{self.name}] Sending Mark Price: {mark_price}")
        success = self._send_with_monitoring(mark_price, "MarkPrice")
        if not success:
            logging.error(f"Dropped MarkPrice: {mark_price}")

    def enable_monitoring(self, enabled: bool = True):
        """Enable or disable monitoring"""
        self.monitoring_enabled = enabled
        if enabled:
            logging.info(f"[{self.name}] Monitoring enabled")
        else:
            logging.info(f"[{self.name}] Monitoring disabled")

    def set_stats_interval(self, interval_seconds: int):
        """Change the statistics logging interval"""
        self.stats_log_interval = interval_seconds
        logging.info(f"[{self.name}] Stats logging interval set to {interval_seconds} seconds")

    def stop(self):
        """Stop the background receiver and clean up."""
        self.running = False
        # Log final statistics before stopping
        if self.monitoring_enabled:
            self.log_current_stats()
        if self.receiver_thread:
            self.receiver_thread.join(timeout=1)
        if self.stats_thread:
            self.stats_thread.join(timeout=1)
        self.socket.close()
        self.context.term()
        logging.info(f"[{self.name}] Connection stopped")