import logging
import queue
import threading
import time
from typing import Callable, List

from common.interface_order import Order, Trade, OrderEvent
from common.interface_req_res import WalletResponse, AccountResponse, AccountRequest, PositionResponse, \
    PositionRequest, MarginInfoRequest, MarginInfoResponse, CommissionRateRequest, CommissionRateResponse, \
    TradesRequest, TradesResponse, ReferenceDataRequest, ReferenceDataResponse
from common.subscription.single_pair_connection.single_pair import PairConnection
from engine.account.account import Account
from engine.margin.margin_info_manager import MarginInfoManager
from engine.position.position_manager import PositionManager
from engine.reference_data.reference_data_manager import ReferenceDataManager
from engine.trades.trades_manager import TradesManager

from common.config_symbols import TRADING_SYMBOLS
from engine.trading_cost.trading_cost_manager import TradingCostManager


class RemoteOrderClient:
    def __init__(self, margin_manager: MarginInfoManager, position_manager: PositionManager, account: Account,
                 trading_cost_manager: TradingCostManager, trade_manager: TradesManager, reference_data_manager: ReferenceDataManager):
        # make port configurable
        self.port = 8081
        self.name = "Remote Order Order Connection"
        self.order_event_listeners: List[Callable[[OrderEvent], None]] = []  # list of callbacks

        self.remote_order_server = PairConnection(self.port, False, self.name)
        self.remote_order_server.start_receiving(self.on_event)

        self.margin_manager = margin_manager
        self.position_manager = position_manager
        self.account = account
        self.trading_cost_manager = trading_cost_manager

        # trade manager
        self.trade_manager = trade_manager

        self.add_order_event_listener(self.position_manager.on_order_event)
        self.add_order_event_listener(self.trade_manager.on_order_event)
        self.reference_data_manager = reference_data_manager



        # init request
        self.init_request()

        # tradable
        self.tradable = True

        # Queue to hold orders to send
        self._order_queue = queue.Queue()
        self._running = True
        self._sender_thread = threading.Thread(target=self._send_orders_loop, daemon=True)
        self._sender_thread.start()

    def init_request(self):
        # try for 10 times
        count  = 0
        while count < 100:
            try:
                count +=1
                time.sleep(1)
                # request for account
                self.request_for_account()
                # request for margin info
                self.request_for_margin()
                # request for reference data
                self.request_for_reference_data()
                # request for trades
                self.request_for_trades()
                # request for commission rate
                self.request_for_commission_rate()
                # request for position
                self.request_for_position()
                break
            except Exception as e:
                logging.error(f"Error occurred,unable to send request: {e}")


    def set_tradable_status(self, new_status):
        logging.info("Setting Tradable Status OLD=%s NEW=%s", self.tradable, new_status)
        self.tradable = new_status

    def submit_order(self, order: Order):
        if not self.tradable:
            logging.info("Unable to trade, Trading rights is turned off")
        """Add an order to the sending queue."""
        self._order_queue.put(order)

    def request_for_account(self):
        self.remote_order_server.send_account_request(AccountRequest())

    def request_for_position(self):
        self.remote_order_server.send_position_request(PositionRequest())

    def request_for_margin(self):
        for asset in TRADING_SYMBOLS:
            self.remote_order_server.send_margin_info_request(MarginInfoRequest(asset))

    def request_for_commission_rate(self):
        for asset in TRADING_SYMBOLS:
            self.remote_order_server.send_commission_rate_request(CommissionRateRequest(asset))

    def request_for_trades(self):
        for asset in TRADING_SYMBOLS:
            self.remote_order_server.send_trades_request(TradesRequest(asset))

    def request_for_reference_data(self):
        self.remote_order_server.send_reference_data_request(ReferenceDataRequest())

    def _send_orders_loop(self):
        """Background thread to send orders from the queue."""
        while self._running:
            try:
                order = self._order_queue.get(timeout=0.1)  # wait for an order or timeout
                self.remote_order_server.send_order(order)
                self._order_queue.task_done()
            except queue.Empty:
                continue  # no orders, loop again

    def add_order_event_listener(self, callback: Callable[[OrderEvent], None]):
        """Register a callback to receive OrderBook updates"""
        self.order_event_listeners.append(callback)

    def on_event(self, obj: object):
        if isinstance(obj, OrderEvent):
            self.received_order_event(obj)
        elif isinstance(obj, WalletResponse):
            self.received_wallet_response(obj)
        elif isinstance(obj, AccountResponse):
            self.received_account_response(obj)
        elif isinstance(obj, PositionResponse):
            self.received_position_response(obj)
        elif isinstance(obj, MarginInfoResponse):
            self.received_margin_info_response(obj)
        elif isinstance(obj, CommissionRateResponse):
            self.received_commission_rate_response(obj)
        elif isinstance(obj, TradesResponse):
            self.received_trades_response(obj)
        elif isinstance(obj, ReferenceDataResponse):
            self.received_reference_data_response(obj)

    def received_reference_data_response(self, reference_data_response: ReferenceDataResponse):
        logging.info(f"Received ReferenceDataResponse: {reference_data_response}")
        self.reference_data_manager.init_reference_data(reference_data_response.reference_data)


    def received_wallet_response(self, wallet_response: WalletResponse):
        logging.info("Received Wallet Response %s" % wallet_response)

    def received_account_response(self, account_response: AccountResponse):
        logging.info("Received Account Response %s" % account_response)
        self.account.init_account(account_response)

    def received_position_response(self, position_response: PositionResponse):
        logging.info("Received Position Response %s" % position_response)
        self.position_manager.inital_position(position_response)

    def received_margin_info_response(self, margin_info_response: MarginInfoResponse):
        logging.info("Received Margin Response %s" % margin_info_response)
        self.margin_manager.update_margin(margin_info_response)

    def received_commission_rate_response(self, commission_rate_response: CommissionRateResponse):
        logging.info("Received Commission Response %s" % commission_rate_response)
        self.trading_cost_manager.add_trading_cost(commission_rate_response)

    def received_trades_response(self, trades_response: TradesResponse):
        logging.info("Received Trades Response %s" % trades_response)
        symbol = trades_response.symbol
        trades = trades_response.trades
        self.trade_manager.load_trades(symbol,trades)

    def received_order_event(self, order_event : OrderEvent):
        logging.info("[%s] Received %s Order Event: \n %s", self.name,order_event.status, order_event)

        for oe_listener in self.order_event_listeners:
            try:
                oe_listener(order_event)
            except Exception as e:
                logging.error(self.name + " Listener raised an exception: %s", e)

    def stop(self):
        """Stop the sender thread cleanly."""
        self._running = False
        self._sender_thread.join(timeout=1)
